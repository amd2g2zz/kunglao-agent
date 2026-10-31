# -*- coding: utf-8 -*-
"""state/progress.py — P(s), the evidence-ladder progress face (#898).

The trajectory reward is ``R(τ) = ΔP − λ·cost`` and THIS face owns P:
``P(s) := Σ_i w(status(g_i))`` over the goal tree's subgoal states
``g_i = (id, status, evidence_refs, confidence)``. Progress is anchored
on the EVIDENCE LADDER, never on action success and never on an
unverified LLM score (expert round 2: separate 终点/进展/证据 — a loop
that rewards high-scoring exploration learns to repeat exploration
without solving anything).

The weights ``w`` are IMPORTED from ``scripts/rlvr/step_credit.py``'s
``CREDIT_BY_CLASS`` / ``CROSS_VERIFIED_STATUSES`` tables — not mirrored.
step_credit is the system's own evidence pricing; importing keeps one
authority, so the #887 w-sensitivity calibration moves both faces
together and a mirror drift is structurally impossible. The status →
class fold reuses step_credit's own classification: a status in
``CROSS_VALIDATED_STATUSES`` ({PROVEN, VERIFIED, NEGATIVE}) prices at
``CREDIT_BY_CLASS["cross_validated"]`` = 1.0; REFUTED prices
``CREDIT_BY_CLASS["refuted"]`` = 0.0; UNVERIFIED rides the provisional
floor 0.3.

The NEGATIVE correction (the 排除 pin): a reproduced proven-negative
finding prices at FULL cross-validated strength (1.0), exactly as
``CROSS_VALIDATED_STATUSES`` already holds. It is NOT REFUTED's 0.0 —
REFUTED means the subgoal's own proposition was WRONG (the claim-terminal
residual claws that mass back separately); NEGATIVE means the subgoal's
proposition ("this direction is dead") was itself PROVEN. Ruling out a
wrong direction is verified knowledge and must bank nonzero progress.

Fail-closed at the boundary (the episode_schema/terminator posture —
step_credit is deliberately fail-open for its SubagentStop cage; this
face has no such cage and garbage would fabricate reward): statuses off
the closed vocabulary, a cross-validated status without evidence refs,
and malformed refs/confidence raise ValueError.

The ledger face appends transition rows with ``credit=None`` (source
"state"): the state face is TELEMETRY — a row without a credit column
banks no posterior mass anywhere in the fold.

#932 read faces: the transition rows are the P(s) ledger state, and the
settlement line prices MEASURED progress from them at settlement time.
``transition_rows`` is the face's own first-class ledger read;
``has_measurements`` answers the cold-start question (no transitions
anywhere = the fixed ladder still seeds); ``dispatch_delta`` returns a
dispatch's ΣΔP with a STRICT fingerprint parse — a row whose
``delta_p=`` fingerprint is malformed is a tampered ledger and raises
(a poisoned read must never silently price).

"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import consolidated_ledger as _cl  # noqa: E402 — the ledger read
from rlvr import q_cells  # noqa: E402 — the path bootstrap lands first
from rlvr.step_credit import (  # noqa: E402
    CREDIT_BY_CLASS,
    CROSS_VALIDATED,
    CROSS_VALIDATED_STATUSES,
    REFUTED,
    REFUTED_STATUSES,
    UNVERIFIED,
)

#: the closed subgoal-status vocabulary: the ladder's status tokens plus
#: the floor token. Exact uppercase membership — "proven" is garbage.
STATUS_UNVERIFIED = "UNVERIFIED"
STATUSES = frozenset(
    CROSS_VALIDATED_STATUSES | REFUTED_STATUSES | {STATUS_UNVERIFIED})

#: the ladder's derived price list (inspection/telemetry face — the
#: weights live in step_credit; this mapping is their P-view).
STATUS_WEIGHTS: Mapping[str, float] = {}

#: the ledger row source — the telemetry-ish posture (q_cells accepts a
#: free source string; "state" names this face's rows).
SOURCE = "state"
METHOD_FAMILY_TRANSITION = "state-progress"
REASON_TRANSITION = "subgoal-ladder-transition"


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"state.progress.{field}: {why}")


def _checked_status(status: Any) -> str:
    if not isinstance(status, str) or status not in STATUSES:
        raise _fail("status",
                    f"must be one of {sorted(STATUSES)}, got {status!r}")
    return status


def status_weight(status: str) -> float:
    """One ladder status -> its evidence price, via step_credit's OWN
    classification (no local table to drift)."""
    s = _checked_status(status)
    if s in CROSS_VALIDATED_STATUSES:
        return CREDIT_BY_CLASS[CROSS_VALIDATED]
    if s in REFUTED_STATUSES:
        return CREDIT_BY_CLASS[REFUTED]
    return CREDIT_BY_CLASS[UNVERIFIED]


for _s in sorted(STATUSES):
    STATUS_WEIGHTS[_s] = status_weight(_s)


def _checked_id(gid: Any) -> str:
    if not isinstance(gid, str) or not gid.strip():
        raise _fail("id", "must be a non-empty string")
    return gid


def _checked_refs(refs: Any, status: str) -> tuple[str, ...]:
    if isinstance(refs, (str, bytes)) or not isinstance(refs, Sequence):
        raise _fail("evidence_refs",
                    "must be a sequence of non-empty strings "
                    "(a bare string would iterate its characters)")
    out: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            raise _fail("evidence_refs",
                        f"each ref must be a non-empty string, got {ref!r}")
        out.append(ref)
    if status in CROSS_VALIDATED_STATUSES and not out:
        # the #799 wall at the record: cross-validated strength without
        # byte-anchored evidence is structural garbage — it must never
        # exist, hence never price
        raise _fail("evidence_refs",
                    f"a {status} subgoal must carry at least one "
                    "evidence ref (the ladder banks nothing on a bare claim)")
    return tuple(out)


def _checked_confidence(confidence: Any) -> float:
    if isinstance(confidence, bool) \
            or not isinstance(confidence, (int, float)) \
            or not math.isfinite(confidence) \
            or not 0.0 <= confidence <= 1.0:
        raise _fail("confidence", "must be a finite number in [0, 1]")
    return float(confidence)


@dataclass(frozen=True)
class Subgoal:
    """One goal-tree subgoal state ``g_i``. ``confidence`` rides the
    record per the g_i shape but does NOT price P — ``w`` is
    status-anchored only (a confidence-modulated w would be a new fitted
    parameter; the #887 calibration owns any such move)."""

    id: str
    status: str
    evidence_refs: tuple[str, ...] = ()
    confidence: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _checked_id(self.id))
        object.__setattr__(self, "status", _checked_status(self.status))
        object.__setattr__(self, "evidence_refs",
                           _checked_refs(self.evidence_refs, self.status))
        object.__setattr__(self, "confidence",
                           _checked_confidence(self.confidence))


def _unique(subgoals: Any, field: str) -> list[Subgoal]:
    if not isinstance(subgoals, Sequence):
        raise _fail(field, "must be a sequence of Subgoal records")
    seen: dict[str, Subgoal] = {}
    for s in subgoals:
        if not isinstance(s, Subgoal):
            raise _fail(field, f"not a Subgoal record: {s!r}")
        if s.id in seen:
            raise _fail(field, f"duplicate subgoal id {s.id!r} "
                               "(a duplicate would double-count its mass)")
        seen[s.id] = s
    return list(seen.values())


def P(subgoals: Sequence[Subgoal]) -> float:
    """P(s) := Σ_i w(status(g_i)) — deterministic, monotone: a subgoal
    moving up the ladder weakly raises P, strictly raises it on the
    floor -> cross-validated moves, and strictly DROPS it on a
    floor -> REFUTED downgrade (the within-band pricing is flat by
    the ladder's own table). Empty tree -> 0.0."""
    return round(sum(status_weight(s.status) for s in _unique(subgoals, "P")),
                 6)


def delta_P(before: Sequence[Subgoal], after: Sequence[Subgoal]) -> float:
    """The trajectory progress delta, exact and replay-stable. Two
    documented edges keep ΔP honest against farming:

    - a subgoal BORN into the tree banks ``w(status) − w(UNVERIFIED)`` —
      entering the tree is the floor, only the climb ABOVE it is
      progress (spawning subgoals at the floor must not mint reward);
    - edits are PENALITIVE, never generative: removal claws the full
      w while a rebirth re-banks only above the floor, so any
      delete+recreate cycle nets ≤ 0 (planner restructuring pays a
      per-removal tax — the anti-farm direction);
    - a subgoal REMOVED claws its full weight back."""
    b = {s.id: s for s in _unique(before, "delta_P.before")}
    a = {s.id: s for s in _unique(after, "delta_P.after")}
    d = 0.0
    for gid, s0 in b.items():
        s1 = a.get(gid)
        if s1 is not None:
            d += status_weight(s1.status) - status_weight(s0.status)
        else:
            d -= status_weight(s0.status)
    for gid, s1 in a.items():
        if gid not in b:
            d += status_weight(s1.status) - status_weight(STATUS_UNVERIFIED)
    return round(d, 6)


def _checked_cost(cost: Any) -> float:
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) \
            or not math.isfinite(cost) or cost < 0.0:
        raise _fail("cost", "must be a finite number >= 0")
    return float(cost)


def _checked_lambda(lam: Any) -> float:
    if isinstance(lam, bool) or not isinstance(lam, (int, float)) \
            or not math.isfinite(lam) or lam < 0.0:
        raise _fail("lam", "must be a finite number >= 0")
    return float(lam)


def reward(before: Sequence[Subgoal], after: Sequence[Subgoal],
           cost: float, *, lam: float) -> float:
    """R(τ) = ΔP − λ·cost for one rollout segment. ``lam`` is the
    caller's declared policy constant (no default — the weight is never
    silently inherited)."""
    return round(delta_P(before, after) - _checked_lambda(lam)
                 * _checked_cost(cost), 6)


def values_from(p_history) -> np.ndarray | None:
    """The V-baseline mapping for ``credit/advantage.py``: a P series
    (one value per step/segment) -> the ``values`` array the advantage
    face consumes. An EMPTY history is None; a FLAT history is None too —
    no g_i transitions means V ≡ 0, which is the advantage face's PINNED
    identity path (A == R exactly, the cold-start contract — a constant
    baseline would shift A away from the pinned early-training shape)."""
    if p_history is None:
        return None
    v = np.asarray(p_history, dtype=float)
    if v.ndim != 1:
        raise _fail("p_history", "must be a 1-d sequence of P values")
    if v.size == 0:
        return None
    if not np.all(np.isfinite(v)):
        raise _fail("p_history", "must be finite (a NaN P would poison V)")
    if not np.any(v != v[0]):
        return None
    return v


def _transition_digest(before: Sequence[Subgoal],
                       after: Sequence[Subgoal]) -> str:
    payload = json.dumps(
        {"before": sorted((s.id, s.status) for s in before),
         "after": sorted((s.id, s.status) for s in after)},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_transition(ws, *, before: Sequence[Subgoal],
                      after: Sequence[Subgoal], claim: str | None = None,
                      dispatch_id: str | None = None) -> dict:
    """Append ONE observation row for a g_i transition via the standard
    single-writer path — ``credit=None`` by construction: the row lands
    with no credit column, so the fold banks NO posterior mass from it
    (the state face is telemetry, the settlement line is the only credit
    authority). The signature digest is content-derived (never
    clock-derived, the #251 contract)."""
    delta = delta_P(before, after)
    return q_cells.append_observation(
        ws, _transition_digest(before, after), METHOD_FAMILY_TRANSITION,
        credit=None, source=SOURCE, claim=claim, dispatch_id=dispatch_id,
        fingerprint=f"delta_p={delta}", reason=REASON_TRANSITION)


#: the transition rows' fingerprint vocabulary — ``delta_p=<ΔP>`` (the
#: only legal shape; anything else on a state-progress row is poison).
DELTA_PREFIX = "delta_p="


def _parse_delta(fingerprint: Any) -> float:
    """The STRICT fingerprint parse: exactly ``delta_p=<finite float>``
    or a raise (fail-closed — a tampered row must never silently
    price)."""
    if not isinstance(fingerprint, str) \
            or not fingerprint.startswith(DELTA_PREFIX):
        raise _fail("fingerprint",
                    f"malformed transition fingerprint {fingerprint!r} "
                    f"(expected {DELTA_PREFIX!r}<ΔP>)")
    try:
        delta = float(fingerprint[len(DELTA_PREFIX):])
    except ValueError as exc:
        raise _fail("fingerprint",
                    f"malformed transition fingerprint {fingerprint!r} "
                    "(the ΔP tail does not parse as a float)") from exc
    if not math.isfinite(delta):
        raise _fail("fingerprint",
                    f"non-finite ΔP in transition fingerprint "
                    f"{fingerprint!r}")
    return delta


def transition_rows(ws, *, dispatch_id: str | None = None) -> list[dict]:
    """This face's OWN ledger rows (source ``state``, method family
    ``state-progress``, schema ``q-cell-obs/1``), append order — the
    P(s) ledger state the settlement line prices from. Optionally
    scoped to one dispatch's rows. The read is the JSONL substrate
    (the JSONLQStore observation face's own query) — the LEDGER, not
    the #428 posterior-bank fold view."""
    did = None if dispatch_id is None else str(dispatch_id).strip()
    out: list[dict] = []
    for row in _cl.read(ws, "experience", schema_prefix="q-cell-obs"):
        if str(row.get("source") or "") != SOURCE \
                or str(row.get("method_family") or "") \
                != METHOD_FAMILY_TRANSITION:
            continue
        if did is not None \
                and str(row.get("dispatch_id") or "") != did:
            continue
        out.append(row)
    return out


def has_measurements(ws) -> bool:
    """The cold-start question (#932): does the ledger carry ANY
    state-progress transition row? False = the fixed CREDIT_BY_CLASS
    ladder still seeds as the prior; True = the measured face prices."""
    return bool(transition_rows(ws))


def dispatch_delta(ws, dispatch_id: str) -> float:
    """One dispatch's MEASURED posterior-mass change across the step —
    the Σ of its transition rows' ΔP fingerprints (a step may advance
    several subgoals). Deterministic from the ledger alone (the
    settlement-time contract); fails closed on a poisoned row."""
    did = _checked_id(dispatch_id)
    total = 0.0
    for row in transition_rows(ws, dispatch_id=did):
        total += _parse_delta(row.get("fingerprint"))
    return round(total, 6)
