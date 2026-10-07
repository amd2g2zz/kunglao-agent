#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/priors.py — on-demand cross-workspace prior (issue 137, v0.1.6
promoted slice).

Issue #420 Phase 2: the implementation body moved here from
scripts/compute_priors.py (which stays a thin adapter: the CLI ``main``
plus re-exports; the prior math lives here).

A PURE function over EXPLICITLY-NAMED workspaces: sum each named
workspace's banked experience into one aggregate Beta prior, return it,
WRITE NOTHING anywhere, DISCARD everything after the call. No registry, no
ambient workspace discovery, no cache: the caller names every workspace it
wants summed and gets a number back.

Why (issue 137): a v0.2+ workspace should be able to START from the
experience of named historical workspaces without inheriting their state
files. The prior is COMPUTED on demand and never materialized — the
insurance against state leakage is that there is no state to leak.

Sum semantics (the documented contract, pinned by
tests/test_compute_priors_137.py):

  - The AGGREGATE gets ONE Beta(1,1) uniform base. Per-workspace bases
    never multiply — only observations sum. Zero workspaces (or
    zero-experience workspaces) = the base prior Beta(1, 1).
  - runs/case-bank.jsonl rows contribute per roi_class: POSITIVE -> +1
    alpha, NEGATIVE -> +1 beta, NEUTRAL / UNRESOLVED -> nothing. Rows are
    read tolerantly (kunglao_log.iter_jsonl); pre-#137 rows without the
    `schema` stamp are legacy and sum like any other row.
  - runs/rollout-ledger.jsonl settled rows (unified reward, U4) contribute per
    polarity: SETTLED_GREEN/HELPED -> +1 alpha, SETTLED_RED/ADVERSE ->
    +1 beta, NEUTRAL/pending -> nothing. Read through the ONE interface
    (reward.prior_observations over ledger.settled).
  - runs/rollout-ledger.jsonl settled EPISODE TIER SCALARS (issue 379,
    reward-rules v2) contribute a separate Normal-Gamma posterior under
    sources.scalar_ledger (n / mean / posterior) — the exponential-family
    form for a continuous scalar, NOT folded into the Beta counts.
  - runs/posteriors.yaml contributes the observations ON TOP of its own
    per-case uniform base: per CasePosterior max(alpha-1, 0) alpha and
    max(beta-1, 0) beta. The two namespaces count DIFFERENT observables
    (settled claim outcomes vs oracle-case runner verdicts); both are
    additive experience and the result decomposes them per source so a
    caller can see what went in.
  - LOUD on explicit inputs: a named path that does not exist or is not a
    directory raises ValueError naming it. A posterior ledger in an
    UNKNOWN schema version raises PosteriorSchemaError (the no-backcompat
    version wall — exactly what historical-format replay must detect). A
    DEGRADED (unreadable) ledger in a named workspace raises ValueError —
    silently summing that workspace as empty would fabricate a prior.
  - MISSING state files contribute zero (a workspace may legitimately
    have no bank / no ledger yet).
  - Determinism: same named inputs -> same prior. No clock, no rng, no
    ambient state. Float sums run in input order.

Result document (schema ``aggregate-prior/1``, self-describing like every
other persisted/computed surface — issue 137):

    {"schema": "aggregate-prior/1",
     "alpha": <aggregate alpha>, "beta": <aggregate beta>,
     "mean": alpha/(alpha+beta),
     "sources": {"case_bank":      {"alpha": .., "beta": ..},
                 "posteriors":     {"alpha": .., "beta": ..},
                 "rollout_ledger": {"alpha": .., "beta": ..},
                 "scalar_ledger":  {"n": .., "mean": ..,
                                    "posterior": {n/mu/kappa/alpha/beta/var}}},
     "workspaces": [<the named paths, as given>]}

numpy adoption (issue 420 Phase 2, scripts/rlvr/README.md rules 1-2):
the Beta aggregation loops moved off builtin ``sum()`` — float stats run
through ``_seq_sum`` (strictly left-to-right IEEE-754 double addition,
bit-identical to the former in-order loop and interpreter-stable where
builtin ``sum()`` is not since 3.12's Neumaier switch), and the integer
counts go through exact ``np.count_nonzero``. Pins:
tests/test_rlvr_bitexact.py (aggregate alpha/beta/mean + the per-source
decomposition).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np  # issue 420: ordered-float reductions + exact counts

from rlvr import reward, scalar

RESULT_SCHEMA = "aggregate-prior/1"

BASE_ALPHA = 1.0  # the ONE aggregate uniform base (Beta(1,1))
BASE_BETA = 1.0


def _seq_sum(values) -> float:
    """Input-order float64 reduction — the settlement determinism axiom
    ("float sums in input order") as a numpy primitive (issue 420).

    np.add.accumulate is strictly left-to-right IEEE-754 double addition;
    the prepended 0.0 seed makes it bit-identical to a Python in-order
    sum for every finite input, and — unlike builtin sum(), which
    switched floats to Neumaier compensation in 3.12 — identical on
    every interpreter. np.sum / np.add.reduce are FORBIDDEN on this
    path: pairwise summation reorders the bits, and the pins in
    tests/test_rlvr_bitexact.py are the wall.

    Canonical implementation: rlvr.scalar._seq_sum (the pattern-setter);
    redeclared here to keep this module's import face flat — the
    TERMINAL_FACT_STATUSES redeclaration precedent in rlvr.state.
    """
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.add.accumulate(np.concatenate(([0.0], arr)))[-1])


def _case_bank_obs(ws: Path) -> tuple[int, int]:
    """(alpha_obs, beta_obs) from the workspace's case bank.

    Tolerant read (kunglao_log.iter_jsonl): malformed lines skipped;
    pre-#137 rows without `schema` are legacy and count normally.
    Missing file -> (0, 0). Counts are exact INTEGER aggregation
    (issue 420 rule 2: np.count_nonzero over the roi_class stream).
    """
    from case_bank import read_entries, ROI_NEGATIVE
    rows = read_entries(ws)
    classes = np.asarray(
        [str(r.get("roi_class") or "") for r in rows], dtype=str)
    return (int(np.count_nonzero(classes == "POSITIVE")),
            int(np.count_nonzero(classes == ROI_NEGATIVE)))


def _posteriors_obs(ws: Path) -> tuple[float, float]:
    """(alpha_obs, beta_obs) from runs/posteriors.yaml — the observations
    on top of each case's own uniform base. Missing file -> (0.0, 0.0).
    Unknown schema -> PosteriorSchemaError (loud, version wall).
    Degraded/unreadable -> ValueError naming the workspace (loud).

    The float observation sums run through _seq_sum (issue 420 rule 1):
    input order over the ledger's case insertion order, bit-identical to
    the former builtin-sum loop, pinned by test_rlvr_bitexact.
    """
    from posteriors import LEDGER_REL, PosteriorLedger
    path = ws / LEDGER_REL
    if not path.exists():
        return 0.0, 0.0
    led = PosteriorLedger.load(ws)
    if led.degraded:
        raise ValueError(
            f"compute_priors: {ws}: runs/posteriors.yaml is unreadable "
            f"({'; '.join(led.warnings) or 'degraded'}) — refusing to sum "
            f"an explicitly-named workspace as empty (loud, not silent)")
    alpha = _seq_sum([max(c.alpha - 1.0, 0.0)
                      for c in led.cases.values()])
    beta = _seq_sum([max(c.beta - 1.0, 0.0)
                     for c in led.cases.values()])
    return alpha, beta


def _rollout_ledger_obs(ws: Path) -> tuple[int, int]:
    """(alpha_obs, beta_obs) from the unified rollout ledger (U4 —
    the ONE prior interface: reward.prior_observations reads through
    ledger.settled; polarity mapping lives there, the prior math here is
    untouched). Missing ledger -> (0, 0). Settled bands only:
    NEUTRAL/pending rows are not observations."""
    return reward.prior_observations(ws)


def _scalar_ledger_obs(ws: Path) -> dict:
    """Episode tier scalars (issue 379, reward-rules v2) as a Normal-Gamma
    posterior — the exponential-family conjugate form for a CONTINUOUS
    observation, deliberately NOT Beta-Bernoulli (that family counts
    binary outcomes, and squashing the {0, 0.4, 0.7, 1.0} tier scalars
    into win/lose counts would discard the measured efficiency gap the
    tiers exist to express). Exponential-family Thompson sampling is what
    has the regret grounding (Russo & Van Roy 2014, "Learning to Optimize
    via Posterior Sampling" — the information-ratio bound covers
    exponential-family posteriors). Additive source: read-only through
    scalar.scalar_observations. Missing ledger -> n=0 prior. The source
    mean runs through _seq_sum (issue 420 rule 1, pinned)."""
    observations = scalar.scalar_observations(ws)
    posterior = scalar.normal_gamma_update(observations)
    mean = (_seq_sum(observations) / len(observations)) \
        if observations else 0.0
    return {"n": len(observations), "mean": mean, "posterior": posterior}


def compute_priors(ws_paths: list[Path] | list[str]) -> dict:
    """Aggregate Beta prior over the EXPLICITLY-NAMED workspaces.

    Pure: reads the named workspaces, writes nothing, keeps nothing.
    Raises ValueError (loud) on a nonexistent/non-directory path or a
    degraded posterior ledger; PosteriorSchemaError propagates from an
    unknown ledger schema (no silent fold-in of foreign formats).

    The per-source float accumulations (posteriors pseudo-counts, scalar
    mean mass) run through _seq_sum in workspace input order (issue 420
    rule 1) — bit-identical to the former accumulation loop, pinned by
    tests/test_rlvr_bitexact.py.
    """
    paths = [Path(p) for p in (ws_paths or [])]
    for p in paths:
        if not p.exists():
            raise ValueError(
                f"compute_priors: workspace does not exist: {p} "
                f"(explicit paths only — no ambient discovery, no silent "
                f"scan, no silent zero)")
        if not p.is_dir():
            raise ValueError(
                f"compute_priors: not a workspace directory: {p}")

    cb_alpha = cb_beta = 0
    rl_alpha = rl_beta = 0
    sc_n_total = 0
    post_alphas: list[float] = []
    post_betas: list[float] = []
    sc_masses: list[float] = []
    sc_posts: list[dict] = []
    for p in paths:
        a, b = _case_bank_obs(p)
        cb_alpha += a
        cb_beta += b
        pa, pb = _posteriors_obs(p)
        post_alphas.append(pa)
        post_betas.append(pb)
        ua, ub = _rollout_ledger_obs(p)  # unified-reward prior feed (additive)
        rl_alpha += ua
        rl_beta += ub
        sc = _scalar_ledger_obs(p)  # issue-379 scalar feed (additive, Normal-Gamma)
        sc_n_total += sc["n"]
        sc_masses.append(sc["mean"] * sc["n"])
        sc_posts.append(sc["posterior"])

    post_alpha = _seq_sum(post_alphas)
    post_beta = _seq_sum(post_betas)
    sc_sum = _seq_sum(sc_masses)
    alpha = BASE_ALPHA + cb_alpha + post_alpha + rl_alpha
    beta = BASE_BETA + cb_beta + post_beta + rl_beta
    agg_mean = (sc_sum / sc_n_total) if sc_n_total else 0.0
    agg_post = scalar.merge_normal_gamma_posts(sc_posts)
    return {
        "schema": RESULT_SCHEMA,
        "alpha": alpha,
        "beta": beta,
        "mean": alpha / (alpha + beta),
        "sources": {
            "case_bank": {"alpha": cb_alpha, "beta": cb_beta},
            "posteriors": {"alpha": post_alpha, "beta": post_beta},
            "rollout_ledger": {"alpha": rl_alpha, "beta": rl_beta},
            "scalar_ledger": {"n": sc_n_total, "mean": agg_mean,
                              "posterior": agg_post},
        },
        "workspaces": [str(p) for p in paths],
    }


# ===========================================================================
# WS3 (#544): the cold-start intake seeding face — replaces the silent
# Beta(1,1) below n_min. EXP-WS3-A (experiments/exp-ws3-calibration.md,
# read-only, never committed): Spearman ρ = −0.3714 (n=6 task families,
# 44 transitions) < the 0.2 gate → BETA_SEED_CAP = 0.5 — near-uniform
# seeding. This face ships because it replaces SILENCE, not because the
# prior is known-good; the uniform SNIPS arm measures whatever signal
# exists from round 1 (no dead zone). The LLM self-assessment source is
# a schema consumer (the init worker fills it); the mechanical fallback
# here is keyword-hit scoring over the declared task features — zero
# invention, fully deterministic.
# ===========================================================================

SEED_SCHEMA = "llm-prior/1"
BETA_SEED_CAP = 0.5  # the ONLY new WS3 constant (EXP-WS3-A verdict)
SEED_SOURCES = ("heuristic-fallback", "llm-self-assessment")
_SEED_CALIBRATION = {"method": "exp-ws3-a", "rho": -0.3714, "n": 6}
_SEED_PROVENANCE = {"experiment": "experiments/exp-ws3-calibration.md"}
SEED_REL = "runs/llm-prior.json"


def _spec_text(spec: dict) -> str:
    """The declared task features as one lowercase scoring surface:
    every string VALUE, walked in sorted-key order (deterministic);
    keys never score (a key named `verification_method` is schema, not
    task content)."""
    parts: list[str] = []

    def _walk(node) -> None:
        if isinstance(node, dict):
            for key in sorted(node, key=str):
                _walk(node[key])
        elif isinstance(node, (list, tuple)):
            for item in node:
                _walk(item)
        elif isinstance(node, str):
            parts.append(node)
        else:
            parts.append(str(node))

    _walk(spec)
    return " ".join(parts).lower()


def heuristic_family_scores(spec: dict, families) -> dict[str, int]:
    """Mechanical keyword scoring: each family's OWN token words (the
    hyphen-split registry token) counted as substrings over the spec
    surface. Integer hit counts, deterministic, no invention — the
    `llm-self-assessment` source replaces exactly this dict."""
    text = _spec_text(spec if isinstance(spec, dict) else {})
    scores: dict[str, int] = {}
    for fam in sorted(set(families)):
        hits = 0
        for word in str(fam).split("-"):
            if word:
                hits += text.count(word)
        scores[str(fam)] = int(hits)
    return scores


def seed_intake_prior(ws, *, families=None,
                      source: str = "heuristic-fallback") -> dict:
    """Write runs/llm-prior.json: weak Beta pseudo-counts per family with
    TOTAL mass exactly BETA_SEED_CAP, means strictly in (0, 0.5)
    (skepticism-first: cap-0.5 seeding never commits hard), ordered by
    the mechanical scores. Fail-open: missing task_spec or an empty
    family set writes NOTHING and returns {} (the current behavior);
    an unknown source raises ValueError (a made-up provenance is not a
    fail-open case)."""
    if source not in SEED_SOURCES:
        raise ValueError(f"unknown seed source {source!r}")
    from kunglao_log import warn

    ws = Path(ws)
    spec: dict | None
    try:
        import yaml

        loaded = yaml.safe_load(
            (ws / "task_spec.yaml").read_text(encoding="utf-8"))
        spec = loaded if isinstance(loaded, dict) else None
    except (OSError, ValueError):
        spec = None
    if spec is None:
        return {}
    fams = sorted(set(families)) if families is not None else None
    if fams is None:
        import method_families

        fams = sorted(method_families.registered_tokens())
    if not fams:
        return {}
    scores = heuristic_family_scores(spec, fams)
    smax = max(scores.values())
    weights = {f: scores[f] + 1 for f in fams}
    total_w = _seq_sum([weights[f] for f in fams])
    digest = hashlib.sha256(
        json.dumps(spec, sort_keys=True,
                                 ensure_ascii=False, default=str)
        .encode("utf-8")).hexdigest()
    fam_doc: dict[str, dict] = {}
    for fam in fams:
        mass = BETA_SEED_CAP * weights[fam] / total_w
        mean = 0.5 * (scores[fam] + 1) / (smax + 2)
        alpha = mass * mean
        fam_doc[fam] = {"alpha": alpha, "beta": mass - alpha}
    doc = {
        "schema": SEED_SCHEMA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "task_features_digest": digest,
        "families": fam_doc,
        "calibration": dict(_SEED_CALIBRATION),
        "provenance": dict(_SEED_PROVENANCE),
    }
    try:
        path = ws / SEED_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(doc, ensure_ascii=False,
                                     sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
    except OSError as exc:  # telemetry, never the producer — but loud (#275)
        warn("priors.seed_intake_prior", f"{type(exc).__name__}: {exc}")
        return {}
    return doc


def read_intake_prior(ws) -> dict | None:
    """Tolerant read: missing / corrupt / wrong-schema / any malformed
    family row ⇒ None — never an exception, never a fabricated prior
    (the whole doc is rejected; there is no partial credit for a seed)."""
    try:
        raw = (Path(ws) / SEED_REL).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(doc, dict) or doc.get("schema") != SEED_SCHEMA:
        return None
    fams = doc.get("families")
    if not isinstance(fams, dict) or not fams:
        return None
    for row in fams.values():
        if not isinstance(row, dict):
            return None
        try:
            alpha = float(row["alpha"])
            beta = float(row["beta"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (alpha > 0.0 and beta > 0.0):
            return None
    return doc


def intake_prior_lead(doc: dict | None) -> str | None:
    """The doc's top family by mean alpha/(alpha+beta); ties break
    alphabetically (deterministic); None-safe on doc/empty."""
    if not isinstance(doc, dict):
        return None
    fams = doc.get("families")
    if not isinstance(fams, dict) or not fams:
        return None
    return min(fams, key=lambda f: (
        -(float(fams[f]["alpha"]) / (float(fams[f]["alpha"])
                                     + float(fams[f]["beta"]))), f))


def intake_prior_weights(ws, allowed=None) -> dict:
    """{family: mean} over the doc — the envelope's cold-start proposal
    face. ``allowed`` requires EXACT coverage (the doc must rank the
    whole allowed vocabulary or nothing): a doc that predates a registry
    change cannot rank coherently next to 1.0 fill-ins, so partial
    coverage fails open to {} (uniform)."""
    doc = read_intake_prior(ws)
    if doc is None:
        return {}
    fams = doc["families"]
    if allowed is not None and set(fams) != set(allowed):
        return {}
    return {f: float(r["alpha"]) / (float(r["alpha"]) + float(r["beta"]))
            for f, r in fams.items()}
