#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feature_prior.py — #460 Part B: the feature-conditioned prior.

predict-before-try (the SATzilla move): a new signature's cells
inherit evidence from structurally similar instances mined into the
feature table (feature-table/1, scripts/feature_mining.py — Part A's
substrate). NO prior math lives in the miner; ALL of it lives here.

## Activation (default OFF)

Everything in this module feeds the kernel only when
KUNGLAO_PREDICT_BEFORE_TRY == "1" (``enabled()``). Flag off, or flag
on without a table/features, is byte-identical to the pre-change
kernel — the determinism wall. The A/B replay (EX-5) is the activation
gate; a losing or underpowered replay ships flag-off.

## Similarity — Jaccard over canonical feature tokens

Every mined field is categorical, boolean, or set-valued, so the
features object is projected to a TOKEN SET (``feature_tokens``) and
similarity is Jaccard (``similarity``): shared tokens over all tokens.
NULL/absent fields emit no tokens — missing evidence degrades to lower
similarity, never to fabricated distance (absence never scored); the
empty union scores 0.0 (no borrowing on no evidence). Token identity
is string equality: deterministic, order-independent, float-free.

## The pool — a second anchor source under the one SHRINK_CAP

``pool_for(table, features, family, exclude_run=None)`` accumulates,
per table row whose outcome is attributed to ``family``: mass
(similarity × (success, failure)) where the outcome's value is its
settled credit (non-null), else 1.0/0.0 for landed/timeout|blocked
act_results; unknown never scores. Rows iterate in table order and the
masses reduce input-order (``q_cells._seq_sum``) — same input bytes ⇒
same pool bits. The live face pools EVERY row (an identical-feature
previous run is prior history, not leakage — the outcome already
happened); ``exclude_run`` is the REPLAY's leave-one-run-out split,
honored by explicit run id only (no fuzzy run-identity join exists).

``q_cells.cell_posterior(..., feature_pool=...)`` adds the pool masses
to the anchor masses BEFORE the single SHRINK_CAP: the family/global
pool stays the base borrow (weight 1 per observation), the feature
pool rides on top similarity-discounted, and total borrowed
pseudo-observations never exceed SHRINK_CAP (q_cells' policy constant
— ADR-001: no new fitted knob here).

## Probe arms (#669 retirement)

die-probe and apkid-prescan are ordinary cost_tier=probe ARMS ranked
by expected information gain: each probe carries static revealable
token CATEGORIES (key prefixes); a category is known when the current
features carry any token with that prefix; gain = unknown/total
categories. Cold start (no probe facts): every category unknown, gain
1.0, probes rank above uninformative method arms. Joint ordering
(``rank_arms``): positive-gain probes above zero-mass method arms,
informative method arms (nonzero evidence mass) above zero-gain
probes; ties by score, category count, name — deterministic.

## Zero-decision posture

Pure functions + flag reads only; nothing here gates, settles, or
moves a dispatch decision on its own. Extraction from a live
workspace (``features_from_workspace``) reuses Part A's extraction by
import (feature_mining._features) — the live face has no corpus
task_dir, so target_kind degrades to nulls (the absence idiom); total
extraction failure degrades to {} (inert — empty tokens borrow
nothing).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

# the single activation flag (owner-ruling axis: the A/B is exactly
# flag-on vs flag-off; default OFF — the inert-landing discipline)
FLAG_ENV = "KUNGLAO_PREDICT_BEFORE_TRY"

# where Part A's miner writes (and the A/B replay reads) the table
FEATURE_TABLE_REL = Path("runs") / "feature-table.jsonl"


def enabled() -> bool:
    """KUNGLAO_PREDICT_BEFORE_TRY == "1" (exact; anything else is off)."""
    return os.environ.get(FLAG_ENV, "") == "1"


def default_table_path(ws) -> Path:
    """The workspace's mined-table location (presence = Part A output)."""
    return Path(ws) / FEATURE_TABLE_REL


def load_table(path) -> list[dict]:
    """Tolerant read of feature-table/1 rows: every row must pass
    feature_mining.validate_row (the substrate contract — reuse, never
    a second validator); invalid rows are skipped, never fatal."""
    import feature_mining  # noqa: PLC0415 — lazy (import-chain cost)

    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    import json  # noqa: PLC0415

    out: list[dict] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and not feature_mining.validate_row(row):
            out.append(row)
    return out


def table_rows(feature_table) -> list[dict]:
    """Accept a table Path (load) or a ready row list (pass-through) —
    the tests/replay pass pre-validated rows."""
    if isinstance(feature_table, (str, Path)):
        return load_table(feature_table)
    return [r for r in feature_table if isinstance(r, dict)]


# ---------------------------------------------------------------------------
# token projection + Jaccard
# ---------------------------------------------------------------------------

def _token(prefix: str, value) -> str | None:
    """One trait literal over a PRESENT string value (null/absent emit
    nothing — absence never scores)."""
    return f"{prefix}{value}" if isinstance(value, str) and value \
        else None


def _scalar_tokens(features: Mapping) -> set[str]:
    out = set()
    for prefix, key in (("lane=", "lane"), ("ptype=", "project_type")):
        tok = _token(prefix, features.get(key))
        if tok:
            out.add(tok)
    return out


def _target_kind_tokens(features: Mapping) -> set[str]:
    tk = features.get("target_kind")
    if not isinstance(tk, Mapping):
        return set()
    out = set()
    for prefix, key in (("lang=", "language"), ("entry=", "entry_suffix")):
        tok = _token(prefix, tk.get(key))
        if tok:
            out.add(tok)
    return out


def _packer_tokens(features: Mapping) -> set[str]:
    pf = features.get("packer_flags")
    if not isinstance(pf, Mapping):
        return set()
    from feature_mining import FAMILY_KEYS  # noqa: PLC0415

    out = {f"pf:{flag}" for flag in FAMILY_KEYS if pf.get(flag) is True}
    for packer in pf.get("detected_packers") or []:
        if isinstance(packer, str) and packer:
            out.add(f"pk:{packer}")
    for obf in pf.get("detected_obfuscators") or []:
        if isinstance(obf, str) and obf:
            out.add(f"ob:{obf}")
    return out


def _difficulty_tokens(features: Mapping) -> set[str]:
    df = features.get("difficulty_factors")
    if not isinstance(df, Mapping):
        return set()
    out = set()
    for prefix, key in (("tier=", "tier"), ("dom=", "dominant_factor")):
        tok = _token(prefix, df.get(key))
        if tok:
            out.add(tok)
    return out


def _probe_tokens(features: Mapping) -> set[str]:
    po = features.get("probe_outputs")
    if not isinstance(po, Mapping):
        return set()
    out = set()
    die = po.get("die")
    if isinstance(die, Mapping):
        if die.get("usable") is True:
            out.add("die:usable")
        tok = _token("die:packer=", die.get("detected_packer"))
        if tok:
            out.add(tok)
    apkid = po.get("apkid")
    if isinstance(apkid, Mapping) and apkid.get("usable") is True:
        out.add("apkid:usable")
    return out


def feature_tokens(features: Mapping) -> frozenset[str]:
    """The canonical token set of one feature-table/1 features object.

    Every token is a string literal over PRESENT values only — nulls
    and absent keys emit nothing (absence never scores). The token
    vocabulary is the audit trail: two instances are similar exactly
    by their shared trait literals."""
    if not isinstance(features, Mapping):
        return frozenset()
    return frozenset(_scalar_tokens(features)
                     | _target_kind_tokens(features)
                     | _packer_tokens(features)
                     | _difficulty_tokens(features)
                     | _probe_tokens(features))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """|A∩B| / |A∪B|; 0.0 on the empty union (no evidence of
    similarity — no borrowing)."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def similarity(features_a: Mapping, features_b: Mapping) -> float:
    """Jaccard over the two feature vectors' canonical token sets."""
    return jaccard(feature_tokens(features_a), feature_tokens(features_b))


# ---------------------------------------------------------------------------
# the feature pool
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FeaturePool:
    """Similarity-weighted (success, failure) masses over OTHER mined
    instances' same-family outcomes, plus the contributing row count.
    (0.0, 0.0, 0) is a NO-OP pool — bit-identical to no pool."""
    success: float
    failure: float
    rows: int

    @property
    def mass(self) -> float:
        return self.success + self.failure


def outcome_mass(outcome: Mapping) -> tuple[float, float] | None:
    """One outcome's unit mass: settled credit (non-null, clamped)
    splits (credit, 1−credit); else landed = (1, 0), timeout/blocked =
    (0, 1); unknown/missing = None (never scores)."""
    credit = outcome.get("credit")
    if isinstance(credit, (int, float)) and not isinstance(credit, bool):
        c = max(0.0, min(1.0, float(credit)))
        return (c, 1.0 - c)
    act = outcome.get("act_result")
    if act == "landed":
        return (1.0, 0.0)
    if act in ("timeout", "blocked"):
        return (0.0, 1.0)
    return None


def pool_for(table: Iterable[Mapping], features: Mapping, family: str,
             exclude_run: str | None = None) -> FeaturePool:
    """The feature-conditioned pool for one (features, family).

    Rows iterate in table order (the miner's canonical sort); masses
    accumulate per-row and reduce input-order float64 (the settlement
    determinism axiom, via q_cells._seq_sum). ``exclude_run`` drops
    the named run by EXPLICIT run id (the replay's held-out split);
    the live face passes None and pools every row — an
    identical-feature previous run is prior history, not leakage."""
    from .q_cells import _seq_sum  # noqa: PLC0415 — the one reduction

    successes: list[float] = []
    failures: list[float] = []
    rows = 0
    for row in table:
        if not isinstance(row, Mapping):
            continue
        if exclude_run is not None \
                and str(row.get("run_id") or "") == str(exclude_run):
            continue
        sim = similarity(features, row.get("features"))
        if sim <= 0.0:
            continue  # zero similarity never borrows
        for outcome in row.get("outcomes") or []:
            if not isinstance(outcome, Mapping):
                continue
            if str(outcome.get("method_family_or_claim_source")
                   or "") != str(family):
                continue
            mass = outcome_mass(outcome)
            if mass is None:
                continue
            successes.append(sim * mass[0])
            failures.append(sim * mass[1])
            rows += 1
    return FeaturePool(_seq_sum(successes), _seq_sum(failures), rows)


def pools_for_candidates(feature_table, features: Mapping,
                         families: Iterable[str],
                         exclude_run: str | None = None
                         ) -> dict[str, FeaturePool]:
    """Per-candidate-family pools (the sampler face: one pool per
    candidate; only families with rows > 0 ride the receipt)."""
    rows = table_rows(feature_table)
    if not rows:
        return {}
    return {family: pool_for(rows, features, family, exclude_run)
            for family in sorted(set(families))}


# ---------------------------------------------------------------------------
# live workspace adapter (extraction reuse — never a second extractor)
# ---------------------------------------------------------------------------

def features_from_workspace(ws, task_dir=None) -> dict:
    """The live instance's feature vector, extracted with Part A's
    rules (feature_mining._features) over the live task_spec/evidence.
    The live face has no corpus task_dir pointer (that lives in
    run-state), so target_kind degrades to nulls unless supplied.
    Total extraction failure degrades to {} (inert — empty tokens
    borrow nothing)."""
    try:
        import feature_mining  # noqa: PLC0415 — lazy
        import init_state  # noqa: PLC0415 — lazy

        ws = Path(ws)
        try:
            ptype = init_state.read_project_type(ws)
        except Exception:  # noqa: BLE001 — presence probe, fail-open
            ptype = None
        return feature_mining._features(
            {"type": ptype}, ws, Path(task_dir) if task_dir else ws)
    except Exception:  # noqa: BLE001 — the seam is fail-open by design
        return {}


# ---------------------------------------------------------------------------
# probe arms (#669 retirement) — expected information gain ranking
# ---------------------------------------------------------------------------

# static revealable token CATEGORIES per probe arm (key prefixes): a
# category is KNOWN when the current features carry any token with
# that prefix (a probe reveals a VALUE into an open vocabulary, so
# "known" is the presence of any value in that category).
PROBE_ARMS: dict[str, tuple[str, ...]] = {
    "die-probe": ("lang=", "pf:packing", "pk:", "die:usable",
                  "die:packer="),
    "apkid-prescan": ("pk:", "ob:", "pf:obfuscation", "apkid:usable"),
}


def probe_gain(arm: str, tokens: frozenset[str]) -> float:
    """unknown categories / total categories — the probe's expected
    information gain over the CURRENT features (1.0 at cold start,
    0.0 when every category it reveals is already known)."""
    categories = PROBE_ARMS.get(arm, ())
    if not categories:
        return 0.0
    unknown = sum(1 for c in categories
                  if not any(t.startswith(c) for t in tokens))
    return unknown / len(categories)


def rank_arms(features: Mapping,
              method_scores: Mapping[str, float]) -> list[dict]:
    """The joint deterministic arm ordering (the probes-as-arms face):

    tier 0 — probes with positive gain (cold start: above everything);
    tier 1 — method arms with nonzero evidence mass (informative);
    tier 2 — probes with zero gain (already-known categories);
    tier 3 — method arms with zero mass (uninformative Beta(1,1)).

    Ties break by score (desc), revealable-category count (desc), then
    arm name — a pure function of (features, method_scores)."""
    tokens = feature_tokens(features)
    entries: list[dict] = []
    for arm, categories in sorted(PROBE_ARMS.items()):
        gain = probe_gain(arm, tokens)
        entries.append({"arm": arm, "kind": "probe",
                        "gain": round(gain, 9),
                        "categories": len(categories)})
    for family in sorted(method_scores):
        try:
            mass = float(method_scores[family])
        except (TypeError, ValueError):
            mass = 0.0
        entries.append({"arm": family, "kind": "method",
                        "mass": round(max(0.0, mass), 9)})

    def _key(e: dict) -> tuple:
        if e["kind"] == "probe":
            tier = 0 if e["gain"] > 0.0 else 2
            return (tier, -e["gain"], -e["categories"], e["arm"])
        tier = 1 if e["mass"] > 0.0 else 3
        return (tier, -e["mass"], 0, e["arm"])

    entries.sort(key=_key)
    return entries
