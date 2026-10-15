#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/step_credit.py — step-level ladder credit (#712): dense reward
at step boundaries (TIPS 2603.22293 / TRACE 2607.13988 turn-level credit).

The measured defect: ladder credit (scalar.round_credit) settles only at
claim-terminal, so a 10-step rollout produced ONE learning signal, the
step-level Φ increment was degenerate (S9: 83/85 = 0), and during a
multi-hour claim neither the Beta nor the sampling distribution moved.

This module owns the step-boundary score — ``step_credit =
f(evidence_quality, verification_status)`` — evaluated over the evidence
the step itself touched (the fact files whose mtime falls inside the
step window):

  cross-validated  terminal claim strength (PROVEN / VERIFIED /
                   NEGATIVE) with a green verifier gate
                   (``verify_status: passes``)              -> 1.0
  unverified       everything else — OPEN / INFERRED /
                   DEFERRED, pending / partial / stale /
                   absent gate; and a window with NO evidence
                   (provisional: the step happened, nothing is
                   verified yet)                            -> 0.3
  refuted          ``status: REFUTED``, or a red gate
                   (``verify_status: fails``)               -> 0.0

Cross-validation here is the two-channel agreement available AT STEP
TIME — worker claim strength × verifier gate — never the #651
certification (register-backing), which by construction only exists at
claim-terminal. The claim-terminal calibration (scalar
``_bank_q_cell_credit``) is the reconciliation for anything the
step-time view over- or under-prices.

``evidence_quality`` is source_reliability: when a fact's provenance
carries an ICD-203 Admiralty credibility letter (A completely reliable
-> F unreliable) the anchor is multiplied by its declared weight — the
WORST letter governs (a claim resting on one weak source is weak);
no provenance letter -> weight 1.0 ("weighted ... if available").

The LEARNED source-reliability discount (``rlvr.source_reliability``)
rides ON TOP: when an evidence item carries source labels (``source`` +
``reference_class``) its credit is multiplied by a Thompson draw from
the Beta folded over invalidation events — evidence REFUTED by later
evidence lowers its source class's reliability, CONFIRMED raises it,
and no event about a source means the uniform prior (the absence of a
rule; the learned face reads neither the Admiralty table nor any other
rule table). Unlabeled evidence rides weight 1.0 — "weighted ... if
available" — so an unlabeled window scores byte-identical to the
pre-discount value. ``weighted_step_credit`` is the composition face;
``step_credit`` routes through it.

Window rule: the step's evidence is ``facts/F*.md`` with mtime in
``(since_ts, until]`` AND a claim channel naming THIS claim
(claim_id / claim_ids / claims / creator). Facts outside the window or
belonging to another claim never enter — otherwise every step would
re-score the claim's cumulative evidence and bank the same credit again.
Re-touching a fact inside a later window rescores it (verification IS
step work); the cumulative sum it produces is exactly what the
claim-terminal residual claws back or tops up, so farming nets zero by
construction.

Posture: fail-open — a malformed fact, an unreadable window, or an
unknown claim is skipped or scores the provisional floor; no face here
may raise into the SubagentStop path (rlvr.step_grain owns the cage).
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation

from rlvr import source_reliability as _sr  # the learned weight

#: the three verification classes the step score prices (#712 A)
CROSS_VALIDATED = "cross_validated"
UNVERIFIED = "unverified"
REFUTED = "refuted"

#: the anchor credit per verification class (#712 A's declared scale)
CREDIT_BY_CLASS = {
    CROSS_VALIDATED: 1.0,
    UNVERIFIED: 0.3,
    REFUTED: 0.0,
}

#: terminal claim strengths whose green gate cross-validates the item.
#: NEGATIVE is a reproduced proven-negative finding (terminal strength:
#: high confidence + mechanical sources per the fact schema) — a rule-out
#: step is real verified work; the claim ladder prices claim-contribution
#: separately and the claim-terminal residual reconciles the difference.
CROSS_VALIDATED_STATUSES = frozenset({"PROVEN", "VERIFIED", "NEGATIVE"})

#: a refuted proposition — even a green reproduce gate then only means
#: the refutation itself reproduced; the issue prices it 0.0
REFUTED_STATUSES = frozenset({"REFUTED"})

#: the red verifier gate — the evidence did not reproduce
RED_GATE = "fails"
GREEN_GATE = "passes"

#: ICD-203 Admiralty source-reliability letter -> credit weight.
#: Declared policy (A = completely reliable ... F = unreliable), a
#: multiplicative modulation in [0.5, 1.0] — reliability refines the
#: status anchor, it never invents one. Letter absent/unknown -> 1.0.
RELIABILITY_WEIGHT = {
    "A": 1.0,
    "B": 0.9,
    "C": 0.8,
    "D": 0.7,
    "E": 0.6,
    "F": 0.5,
}

#: the launch/step ledger timestamp shape (second precision, UTC Z)
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

#: the fact-file glob the window scans (the F<NNN> naming convention,
#: same glob scalar.fact_artifacts reads)
_FACT_GLOB = "F*.md"

#: the frontmatter claim-ref channels (the lint_facts CLAIM_REF_FIELDS
#: face + the #379 creator provenance channel)
_CLAIM_REF_FIELDS = ("claim_id", "claim_ids", "claims")


def classify_verification(status, verify_status) -> str:
    """One evidence item's verification class: a red gate or a refuted
    status refutes FIRST (a green gate on a REFUTED fact only means the
    refutation reproduced), then a green gate over terminal claim
    strength cross-validates, else the item stays unverified."""
    st = str(status or "").strip().upper()
    vs = str(verify_status or "").strip().lower()
    if vs == RED_GATE or st in REFUTED_STATUSES:
        return REFUTED
    if vs == GREEN_GATE and st in CROSS_VALIDATED_STATUSES:
        return CROSS_VALIDATED
    return UNVERIFIED


def reliability_weight(credibility) -> float:
    """One Admiralty credibility code (``A1`` .. ``F6``) -> its declared
    weight; absent/unknown -> 1.0 (reliability weights "if available")."""
    letter = str(credibility or "").strip()[:1].upper()
    return RELIABILITY_WEIGHT.get(letter, 1.0)


def _provenance_weight(meta: dict) -> float:
    """The item's source_reliability: the WORST (max letter) credibility
    among its provenance entries' KNOWN letters (an unknown code never
    masks a known-weak source — C4 review finding); no known letters ->
    1.0."""
    prov = meta.get("provenance")
    if not isinstance(prov, list):
        return 1.0
    letters = [str(e.get("credibility") or "").strip()[:1].upper()
               for e in prov
               if isinstance(e, dict) and str(e.get("credibility") or "")]
    known = [letter for letter in letters if letter in RELIABILITY_WEIGHT]
    if not known:
        return 1.0
    return RELIABILITY_WEIGHT[max(known)]


def item_credit(meta: dict) -> float:
    """One evidence item's credit: status anchor × source reliability."""
    meta = meta or {}
    anchor = CREDIT_BY_CLASS[classify_verification(
        meta.get("status"), meta.get("verify_status"))]
    return round(anchor * _provenance_weight(meta), 6)


def step_credit(items) -> float:
    """The step-boundary score: the mean credit of the evidence items
    the step touched, each discounted by its item's LEARNED source
    reliability (``weighted_step_credit`` — unlabeled items ride the
    neutral weight, so the pre-discount score is preserved). Empty
    window -> the unverified provisional floor (the step happened;
    claim-terminal calibration corrects it — a step with no evidence is
    never banked as 0, which would keep the signal degenerate)."""
    return weighted_step_credit(items)


def weighted_step_credit(items, *, context_class=None,
                         rng: random.Random | None = None,
                         source_view=None) -> float:
    """The step score with the LEARNED source-reliability discount: the
    mean over items of ``item_credit(meta) × theta``, where theta is a
    Thompson draw from the learned source-reliability Beta
    (``rlvr.source_reliability``) for the item's source class. The
    discount is learned from invalidation events — never a
    source-to-trust table. An item carrying no source labels rides
    theta = 1.0 ("weighted ... if available"), so an unlabeled window
    scores byte-identical to the pre-discount value. ``source_view``
    lets a caller reuse one fold across items; the store is read only
    when a labeled item is present (no I/O for unlabeled windows)."""
    rows = [i for i in (items or []) if isinstance(i, dict)]
    if not rows:
        return CREDIT_BY_CLASS[UNVERIFIED]
    view = source_view
    total = 0.0
    for meta in rows:
        weight = 1.0
        if _sr.has_source_labels(meta):
            if view is None:
                view = _sr.fold()
            weight = _sr.reliability_weight(meta,
                                            context_class=context_class,
                                            rng=rng, view=view)
        total += item_credit(meta) * weight
    return round(total / len(rows), 6)


# --------------------------------------------------------- the evidence window

def _epoch(ts) -> float | None:
    """A ledger Z-timestamp -> epoch seconds; unknown shape -> None
    (staleness/window undecidable — never a guess)."""
    try:
        dt = datetime.strptime(str(ts), _TS_FMT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return dt.timestamp()


def _frontmatter(path: Path) -> dict | None:
    """One fact file's frontmatter dict; malformed / non-mapping ->
    None (not evidence — lint_facts owns the loudness)."""
    import yaml
    try:
        parts = path.read_text(
            encoding="utf-8", errors="replace").split("---", 2)
        meta = yaml.safe_load(parts[1]) if len(parts) >= 3 else None
    except OSError:
        return None
    except yaml.YAMLError:
        return None
    return meta if isinstance(meta, dict) else None


def _claim_refs(meta: dict) -> set[str]:
    """The claim channels a fact names (exact ids — never a substring):
    the claim-ref fields plus the creator provenance channel."""
    refs: set[str] = set()
    for key in _CLAIM_REF_FIELDS:
        value = meta.get(key)
        if isinstance(value, str):
            refs.add(value.strip())
        elif isinstance(value, list):
            refs.update(str(v).strip() for v in value)
    creator = str(meta.get("creator") or "").strip()
    if creator:
        refs.add(creator)
    refs.discard("")
    return refs


def evidence_in_window(ws, *, claim: str, since_ts,
                       until: datetime | None) -> list[dict]:
    """The step's own evidence: fact frontmatter for facts touched in
    the half-open window ``(since_ts, until]`` that name THIS claim.

    since_ts unparseable / until not a datetime / claim empty -> [] (the
    window is undecidable; the caller scores the provisional floor —
    fail-open, never a raise into the settle). Read errors skip the file,
    malformed frontmatter skips the file."""
    claim = str(claim or "").strip()
    try:
        if not claim:
            return []
        since = _epoch(since_ts)
        if since is None:
            return []
        if not isinstance(until, datetime):
            return []
        until_epoch = until.timestamp()
        facts_dir = Path(ws) / "facts"
        if not facts_dir.is_dir():
            return []
        out: list[dict] = []
        for path in sorted(facts_dir.glob(_FACT_GLOB)):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if not since < mtime <= until_epoch:
                continue
            meta = _frontmatter(path)
            if meta is None:
                continue
            if claim not in _claim_refs(meta):
                continue
            out.append(dict(meta, id=str(meta.get("id") or path.stem)))
        return out
    except Exception as exc:  # noqa: BLE001 — fail-open telemetry
        warn("rlvr.step_credit.evidence_in_window",
             f"{type(exc).__name__}: {exc}")
        return []
