# -*- coding: utf-8 -*-
"""policy/redteam.py — the redteam self-learning machinery (card 933).

The adversarial faces the loop consumes, ALL deterministic: the
debate arbitration (worker-evidence vs redteam-challenge, ruled by
structure — NO LLM referee), the dual-pool canaries (the GAP between
known-family recall and held-out new-family recall is THE collapse
signal), the detection-strategy arms (Beta posteriors that gain mass
on verified catches and lose it on misses), and the cheat class — the
absolute disqualifier ABOVE the evidence ladder, whose punishment
beyond zero is a RECORDED PARAMETER, default OFF.

Debate (the battery M6 machinery, productionized): a redteam challenge
    that carries no anchored evidence never disqualifies (the citation
    wall); an anchored challenge the worker REBUTS with anchored
    evidence stands down; an anchored challenge the worker leaves
    UNANSWERED upholds — the confrontation itself is the evidence (the
    worker, who knows the ground truth, could not answer it), which is
    why the ruling is pool-invariant by construction: it reads the
    confrontation structure only, never the case's pool tag.

Unilateral (the comparator): the report-only ruling verifies every
    challenge anchor against the KNOWN signature registry — a
    new-family anchor does not resolve, against-registry-unknown means
    the report cannot stand alone, so detection collapses on the
    held-out pool (the battery's 0.25 held-out recall).

Cheat (the absolute class): a cheat-ruled dispatch's credit is 0.0 no
    matter what the measured climb priced (cheat_zero, the disqualifier
    above the ladder); the caught worker's next-dispatch context
    carries a cheat-warning receipt through the loop's receipt channel
    (a ledger row + an immutable context composition); and punishment
    below zero is a RECORDED PARAMETER, default OFF — cheat prices at
    exactly 0.0 until explicitly enabled.

All ledger rows land credit=None (the telemetry posture — the redteam
face is not a credit authority; the disqualifier prices through
cheat_zero at the composition).
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import consolidated_ledger as _cl  # noqa: E402 — the read face
from rlvr import q_cells  # noqa: E402 — the single-writer path

#: the dual-pool canary vocabulary (closed).
POOLS: tuple[str, ...] = ("known", "heldout")

#: the collapse floor: recall_known - recall_heldout beyond this IS the
#: collapse signal (the battery's unilateral gap 0.75 fires it; the
#: debate arm's -0.125 stays healthy). Documented policy, NOT fitted.
GAP_FLOOR = 0.5

#: the cheat row's ledger identity (the telemetry posture).
CHEAT_SOURCE = "redteam"
CHEAT_FAMILY = "cheat-verdict"
CHEAT_FINGERPRINT = "cheat=1"
CHEAT_REASON = "cheat-disqualified"

#: the recorded punishment parameter, DEFAULT OFF: a cheat prices at
#: exactly 0.0 until this flag is explicitly enabled by policy.
PUNISHMENT_BEYOND_ZERO = False

#: the dormant magnitude (rides only an explicitly-enabled punishment).
PUNISHMENT_MAGNITUDE = 0.25


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"policy.redteam.{field}: {why}")


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _checked_refs(refs: Any, field: str) -> tuple[str, ...]:
    """Anchored evidence: a sequence (never a bare string — it would
    iterate its characters) of non-empty strings."""
    if isinstance(refs, (str, bytes)) or not isinstance(refs, Sequence):
        raise _fail(field,
                    "must be a sequence of non-empty strings")
    out: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            raise _fail(field,
                        f"each ref must be a non-empty string, "
                        f"got {ref!r}")
        out.append(ref)
    return tuple(out)


@dataclass(frozen=True)
class DebateCase:
    """One structured confrontation: the worker's claim + anchored
    evidence vs the redteam's challenge + anchored evidence. The pool
    tag rides the receipt only (the rulings never read it — the
    pool-invariance pin). ``planted_cheat`` is the HARNESS'S ground
    truth for the canary arithmetic, data like any other input."""

    case_id: str
    pool: str
    claim: str
    worker_refs: tuple[str, ...] = ()
    challenge: str | None = None
    challenge_refs: tuple[str, ...] = ()
    planted_cheat: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id",
                           _non_empty(self.case_id, "case_id"))
        object.__setattr__(self, "pool", _checked_pool(self.pool))
        object.__setattr__(self, "claim", _non_empty(self.claim, "claim"))
        object.__setattr__(self, "worker_refs",
                           _checked_refs(self.worker_refs,
                                         "worker_refs"))
        if self.challenge is not None \
                and (not isinstance(self.challenge, str)
                     or not self.challenge.strip()):
            raise _fail("challenge",
                        "must be None or a non-empty string")
        object.__setattr__(self, "challenge_refs",
                           _checked_refs(self.challenge_refs,
                                         "challenge_refs"))
        if not isinstance(self.planted_cheat, bool):
            raise _fail("planted_cheat", "must be a bool")


def _checked_pool(pool: Any) -> str:
    if not isinstance(pool, str) or pool not in POOLS:
        raise _fail("pool", f"must be one of {POOLS}, got {pool!r}")
    return pool


def _receipt(case: DebateCase, verdict: str, reason: str) -> dict:
    return {"case_id": case.case_id, "pool": case.pool,
            "verdict": verdict, "reason": reason}


def arbitrate_debate(case: Any) -> dict:
    """The DETERMINISTIC confrontation ruling (no LLM referee): reads
    the case's structure only — no registry, no pool, no content
    judgment. Same structure, same receipt, byte-identical."""
    if not isinstance(case, DebateCase):
        raise _fail("case", "must be a DebateCase")
    if case.challenge is None:
        return _receipt(case, "claim_stands", "no-challenge")
    if not case.challenge_refs:
        return _receipt(case, "claim_stands", "challenge-unanchored")
    if case.worker_refs:
        return _receipt(case, "claim_stands", "rebutted")
    return _receipt(case, "challenge_upheld",
                    "unanswered-anchored-challenge")


def unilateral_rule(case: Any, *, known_anchors: Any) -> dict:
    """The report-only comparator: every challenge anchor must resolve
    into the KNOWN signature registry for the challenge to uphold — a
    new-family anchor cannot stand alone, so the ruling stands (the
    battery's unilateral held-out collapse mechanism). No rebuttal
    round, no confrontation."""
    if not isinstance(case, DebateCase):
        raise _fail("case", "must be a DebateCase")
    if not isinstance(known_anchors, (set, frozenset)):
        raise _fail("known_anchors",
                    "must be a set of known signature anchors")
    if case.challenge is None or not case.challenge_refs:
        return _receipt(case, "claim_stands", "no-challenge")
    if all(ref in known_anchors for ref in case.challenge_refs):
        return _receipt(case, "challenge_upheld", "known-anchor")
    return _receipt(case, "claim_stands", "anchor-does-not-resolve")


def ruling_catches(ruling: Mapping, case: DebateCase) -> bool:
    """A VERIFIED CATCH: the ruling upholds a challenge on a case that
    is (per the harness's ground truth) a planted cheat. The only
    event that feeds the strategy arms and the canary recalls."""
    if ruling.get("case_id") != case.case_id:
        return False
    return ruling.get("verdict") == "challenge_upheld" \
        and case.planted_cheat


def canary_cycle(cases: Any, rulings: Any) -> dict:
    """The dual-pool canary over ONE cycle: per-pool verified-catch
    recalls over the planted cheats (a pool with nothing planted reads
    the honest 0.0), the GAP = recall_known - recall_heldout (the
    battery's sign convention: unilateral 0.75, debate -0.125), and
    the collapse rule ``gap > GAP_FLOOR``. A ruling naming a foreign
    case id never counts (the receipt must name its case)."""
    if not isinstance(cases, (list, tuple)) \
            or not isinstance(rulings, (list, tuple)):
        raise _fail("cases/rulings", "must be sequences")
    by_id = {}
    for c in cases:
        if not isinstance(c, DebateCase):
            raise _fail("cases", "every case must be a DebateCase")
        by_id[c.case_id] = c
    caught = {"known": 0, "heldout": 0}
    planted = {"known": 0, "heldout": 0}
    for r in rulings:
        if not isinstance(r, Mapping):
            raise _fail("rulings", "every ruling must be a mapping")
        c = by_id.get(str(r.get("case_id")))
        if c is None:
            continue
        if c.planted_cheat:
            planted[c.pool] += 1
            if ruling_catches(r, c):
                caught[c.pool] += 1
    recall_known = (caught["known"] / planted["known"]
                    if planted["known"] else 0.0)
    recall_heldout = (caught["heldout"] / planted["heldout"]
                      if planted["heldout"] else 0.0)
    gap = round(recall_known - recall_heldout, 6)
    # collapse needs HELD-OUT EVIDENCE: an empty held-out pool reads
    # recall 0.0 and would fire a spurious collapse with nothing
    # measured — no planted held-out cheats, no collapse verdict.
    measurable = planted["heldout"] > 0
    return {"recall_known": round(recall_known, 6),
            "recall_heldout": round(recall_heldout, 6),
            "gap": gap,
            "measurable": measurable,
            "collapse": measurable and gap > GAP_FLOOR}


@dataclass(frozen=True)
class StrategyArm:
    """One detection strategy's Beta posterior (the arm machinery): a
    verified catch gains mass (alpha + 1), a miss loses it (beta + 1).
    The uniform prior at cold start; updates are IMMUTABLE."""

    strategy: str
    alpha: float = 1.0
    beta: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy",
                           _non_empty(self.strategy, "strategy"))
        for name in ("alpha", "beta"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(float(v)) or v < 0.0:
                raise _fail(name,
                            "must be a finite number >= 0")
        object.__setattr__(self, "alpha", float(self.alpha))
        object.__setattr__(self, "beta", float(self.beta))


def strategy_mean(arm: Any) -> float:
    """The posterior mean ``alpha / (alpha + beta)`` — 0.5 at the
    cold-start prior."""
    if not isinstance(arm, StrategyArm):
        raise _fail("arm", "must be a StrategyArm")
    if arm.alpha + arm.beta <= 0.0:
        raise _fail("arm", "degenerate posterior (alpha + beta <= 0)")
    return round(arm.alpha / (arm.alpha + arm.beta), 6)


def strategy_update(arm: Any, *, caught: bool) -> StrategyArm:
    """The immutable update: +alpha on a verified catch, +beta on a
    miss."""
    if not isinstance(arm, StrategyArm):
        raise _fail("arm", "must be a StrategyArm")
    if not isinstance(caught, bool):
        raise _fail("caught", "must be a bool")
    if caught:
        return StrategyArm(arm.strategy, alpha=arm.alpha + 1.0,
                           beta=arm.beta)
    return StrategyArm(arm.strategy, alpha=arm.alpha,
                       beta=arm.beta + 1.0)


def cheat_zero(credit: Any, *, cheat: bool) -> float:
    """The ABSOLUTE disqualifier: a cheat-ruled dispatch banks 0.0 no
    matter what the evidence ladder priced — the class sits ABOVE the
    ladder, so the composition is total (the ladder never rescues
    it)."""
    if isinstance(credit, bool) or not isinstance(credit, (int, float)) \
            or not math.isfinite(float(credit)):
        raise _fail("credit", "must be a finite number")
    if not isinstance(cheat, bool):
        raise _fail("cheat", "must be a bool")
    return 0.0 if cheat else round(float(credit), 6)


def cheat_adjustment(*, cheat: bool,
                     enabled: bool = PUNISHMENT_BEYOND_ZERO,
                     magnitude: Any = PUNISHMENT_MAGNITUDE) -> float:
    """The recorded punishment parameter: default OFF — a cheat prices
    at exactly 0.0 (cheat_zero's floor), never negative. Only an
    explicitly-enabled punishment prices the magnitude below zero."""
    if not isinstance(cheat, bool) or not isinstance(enabled, bool):
        raise _fail("cheat/enabled", "must be bools")
    mag = _finite_check(magnitude)
    if cheat and enabled:
        return round(-mag, 6)
    return 0.0


def _finite_check(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)) or float(value) < 0.0:
        raise _fail("magnitude", "must be a finite number >= 0")
    return float(value)


def _cheat_digest(worker: str, rollout_id: str, dispatch_id: str,
                  reason: str) -> str:
    payload = json.dumps(
        {"worker": worker, "rollout_id": rollout_id,
         "dispatch_id": dispatch_id, "reason": reason},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_cheat(ws, *, rollout_id: str, dispatch_id: str,
                 worker: str, reason: str = "", ts: str | None = None) \
        -> dict:
    """Land ONE cheat ruling as a credit=None telemetry row (the
    redteam face is not a credit authority). The digest is
    content-derived, never clock-derived; the worker rides the row's
    ``agent`` column — the receipt channel's key."""
    rid = _non_empty(rollout_id, "rollout_id")
    did = _non_empty(dispatch_id, "dispatch_id")
    w = _non_empty(worker, "worker")
    # the caller's case reason rides the row's audit reason column
    # (blank falls back to the face's own stamp)
    return q_cells.append_observation(
        ws, _cheat_digest(w, rid, did, str(reason)), CHEAT_FAMILY,
        credit=None, source=CHEAT_SOURCE, agent=w, claim=rid,
        dispatch_id=did, fingerprint=CHEAT_FINGERPRINT,
        reason=str(reason) if str(reason).strip() else CHEAT_REASON,
        ts=ts)


def cheat_warning_receipt(ws, worker: str) -> dict | None:
    """The receipt channel's read face: the worker's MOST RECENT cheat
    row as the warning receipt for the NEXT dispatch context, else
    None (append order, last wins)."""
    w = _non_empty(worker, "worker")
    found: dict | None = None
    for row in _cl.read(ws, "experience", schema_prefix="q-cell-obs"):
        if str(row.get("source") or "") != CHEAT_SOURCE \
                or str(row.get("method_family") or "") != CHEAT_FAMILY:
            continue
        if str(row.get("agent") or "") != w:
            continue
        found = row
    if found is None:
        return None
    return {"worker": w,
            "rollout_id": str(found.get("claim") or ""),
            "dispatch_id": str(found.get("dispatch_id") or ""),
            "reason": str(found.get("reason") or ""),
            "ts": str(found.get("ts") or "")}


def with_cheat_warning(context: Mapping, receipt: dict | None) -> dict:
    """The immutable next-dispatch composition: a NEW mapping with the
    warning under ``cheat_warning`` — the base context is never
    mutated; a None receipt composes nothing."""
    if not isinstance(context, Mapping):
        raise _fail("context", "must be a mapping")
    out = dict(context)
    if receipt is not None:
        out["cheat_warning"] = dict(receipt)
    return out
