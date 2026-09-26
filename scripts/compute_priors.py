#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compute_priors.py — on-demand cross-workspace prior (issue 137, v0.1.6
promoted slice).

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
    (reward_settlement.prior_observations over rollout_ledger.settled).
  - runs/rollout-ledger.jsonl settled EPISODE TIER SCALARS (#379,
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

CLI:
    python scripts/compute_priors.py <workspace> [<workspace> ...]

Prints the result document as JSON on stdout, exit 0. Any loud failure
prints the named offender to stderr and exits 2. Writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESULT_SCHEMA = "aggregate-prior/1"

BASE_ALPHA = 1.0  # the ONE aggregate uniform base (Beta(1,1))
BASE_BETA = 1.0


def _case_bank_obs(ws: Path) -> tuple[int, int]:
    """(alpha_obs, beta_obs) from the workspace's case bank.

    Tolerant read (kunglao_log.iter_jsonl): malformed lines skipped;
    pre-#137 rows without `schema` are legacy and count normally.
    Missing file -> (0, 0).
    """
    from case_bank import read_entries, ROI_NEGATIVE
    rows = read_entries(ws)
    alpha = sum(1 for r in rows if r.get("roi_class") == "POSITIVE")
    beta = sum(1 for r in rows if r.get("roi_class") == ROI_NEGATIVE)
    return alpha, beta


def _posteriors_obs(ws: Path) -> tuple[float, float]:
    """(alpha_obs, beta_obs) from runs/posteriors.yaml — the observations
    on top of each case's own uniform base. Missing file -> (0.0, 0.0).
    Unknown schema -> PosteriorSchemaError (loud, version wall).
    Degraded/unreadable -> ValueError naming the workspace (loud).
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
    alpha = sum(max(c.alpha - 1.0, 0.0) for c in led.cases.values())
    beta = sum(max(c.beta - 1.0, 0.0) for c in led.cases.values())
    return alpha, beta


def _rollout_ledger_obs(ws: Path) -> tuple[int, int]:
    """(alpha_obs, beta_obs) from the unified rollout ledger (U4 —
    the ONE prior interface: reward_settlement.prior_observations reads
    through rollout_ledger.settled; polarity mapping lives there, the
    prior math here is untouched). Missing ledger -> (0, 0). Settled bands
    only: NEUTRAL/pending rows are not observations."""
    try:
        import reward_settlement
        return reward_settlement.prior_observations(ws)
    except ImportError as exc:  # pragma: no cover — sibling always present
        raise ValueError(
            f"compute_priors: {ws}: reward_settlement unavailable "
            f"({exc})") from exc


def _scalar_ledger_obs(ws: Path) -> dict:
    """Episode tier scalars (#379, reward-rules v2) as a Normal-Gamma
    posterior — the exponential-family conjugate form for a CONTINUOUS
    observation, deliberately NOT Beta-Bernoulli (that family counts
    binary outcomes, and squashing the {0, 0.4, 0.7, 1.0} tier scalars
    into win/lose counts would discard the measured efficiency gap the
    tiers exist to express). Exponential-family Thompson sampling is what
    has the regret grounding (Russo & Van Roy 2014, "Learning to Optimize
    via Posterior Sampling" — the information-ratio bound covers
    exponential-family posteriors). Additive source: read-only through
    scalar_settlement.scalar_observations. Missing ledger -> n=0 prior."""
    try:
        import scalar_settlement
        observations = scalar_settlement.scalar_observations(ws)
    except ImportError as exc:  # pragma: no cover — sibling always present
        raise ValueError(
            f"compute_priors: {ws}: scalar_settlement unavailable "
            f"({exc})") from exc
    posterior = scalar_settlement.normal_gamma_update(observations)
    mean = (sum(observations) / len(observations)) if observations else 0.0
    return {"n": len(observations), "mean": mean, "posterior": posterior}


def compute_priors(ws_paths: list[Path] | list[str]) -> dict:
    """Aggregate Beta prior over the EXPLICITLY-NAMED workspaces.

    Pure: reads the named workspaces, writes nothing, keeps nothing.
    Raises ValueError (loud) on a nonexistent/non-directory path or a
    degraded posterior ledger; PosteriorSchemaError propagates from an
    unknown ledger schema (no silent fold-in of foreign formats).
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
    post_alpha = post_beta = 0.0
    rl_alpha = rl_beta = 0
    sc_n_total = 0
    sc_sum = 0.0
    sc_posts: list[dict] = []
    for p in paths:
        a, b = _case_bank_obs(p)
        cb_alpha += a
        cb_beta += b
        pa, pb = _posteriors_obs(p)
        post_alpha += pa
        post_beta += pb
        ua, ub = _rollout_ledger_obs(p)  # unified-reward prior feed (additive)
        rl_alpha += ua
        rl_beta += ub
        sc = _scalar_ledger_obs(p)  # #379 scalar feed (additive, Normal-Gamma)
        sc_n_total += sc["n"]
        sc_sum += sc["mean"] * sc["n"]
        sc_posts.append(sc["posterior"])

    alpha = BASE_ALPHA + cb_alpha + post_alpha + rl_alpha
    beta = BASE_BETA + cb_beta + post_beta + rl_beta
    agg_mean = (sc_sum / sc_n_total) if sc_n_total else 0.0
    import scalar_settlement
    agg_post = scalar_settlement.merge_normal_gamma_posts(sc_posts)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compute_priors.py",
        description="issue 137: aggregate cross-workspace prior over "
                    "EXPLICITLY-NAMED workspaces (pure — writes nothing)")
    parser.add_argument("workspaces", nargs="*",
                        help="workspace directories to sum (every path must "
                             "exist; none is discovered ambiently)")
    args = parser.parse_args(argv)
    try:
        result = compute_priors(args.workspaces)
    except ValueError as exc:  # loud: bad path / degraded ledger; the
        # unknown-schema version wall (PosteriorSchemaError) is a
        # ValueError subclass and dies here too.
        print(f"compute_priors: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
