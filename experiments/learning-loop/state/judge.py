# -*- coding: utf-8 -*-
"""state/judge.py — the gated judge face (reward base v2, card 933).

Mechanical signals stay the default; only AMBIGUOUS segments escalate
to the judge, and what comes back is a BOUNDED per-step delta — the
judge modulates, it never prices (the Ask-a-Strong-Judge structure).
Three faces:

GATE      ``is_ambiguous(progress_delta, signals)`` — the escalation
          trigger fires ONLY on measured progress at the ambiguity
          floor (|dP| <= AMBIGUITY_FLOOR, the stagnation face's flat
          semantics) or on a SIGNAL CONFLICT (the verdict layers
          disagree). A missing measurement (``progress_delta=None``,
          the cold-start) is honestly UNKNOWN, never flat — it does
          not escalate by itself. Structural garbage raises.

SEAM      ``judge_step(judge, ...)`` — the judge is a CALLABLE the face
          owns no profile for (the scripted judge lives in tests; the
          real LLM judge plugs in later through the trajectory rubric).
          The callable receives one structured payload
          (``{progress_delta, signals}``) and returns a real number;
          the face hard-clamps it into ``[-bound, +bound]`` (the
          designed DELTA_BOUND, shrinkable by the calibration band) and
          fails closed on a non-finite or non-numeric ruling. A
          gate-closed step returns delta 0.0 WITHOUT calling the judge
          — escalation is the only cost.

BAND      ``effective_band(agreements, ...)`` — the calibration
          posterior: the judge's modulation-vs-outcome agreement
          history (True = the judge's direction matched the eventual
          outcome) drives a Laplace posterior mean, and the effective
          band scales as ``base x max(0, 2p - 1)``: full agreement
          keeps (an ever-larger share of) the designed bound, a
          coin-flip judge is NEUTRAL (band 0), and the shrink is
          monotone in the history. An empty history trusts the designed
          bound — the judge is trusted until evidence accumulates.

LEDGER    ``record_judgment`` lands one credit=None telemetry row per
          ESCALATED judgment (the state/progress discipline: the judge
          face is not a credit authority) with the delta in a strict
          ``delta_j=<float>`` fingerprint; ``trajectory_delta`` reads a
          trajectory's summed injection with the same strict parse — a
          poisoned row raises, never silently prices. The signature
          digest is content-derived, never clock-derived.

The cumulative cap over these deltas lives beside the settlement
commit (settlement/judge_cap.py) — it binds the injection to the
COMMIT-certified mechanical total, so the binding is a settlement-time
invariant, not a judge-side promise.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import consolidated_ledger as _cl  # noqa: E402 — the read face
from rlvr import q_cells  # noqa: E402 — the single-writer path

#: the ambiguity floor: |dP| at or below this is FLAT (the stagnation
#: face's semantics — P is rounded to 6 decimals and every legal
#: nonzero ladder move clears it by orders of magnitude).
AMBIGUITY_FLOOR = 1e-6

#: the designed per-step bound on the judge's modulation. A documented
#: policy constant (NOT fitted) — a tenth of a full step's credit: the
#: judge steers within a step, the ladder still owns the scale.
DELTA_BOUND = 0.1

#: the ledger row identity (the telemetry posture — credit=None).
SOURCE = "judge"
METHOD_FAMILY = "judge-delta"
REASON = "judge-escalation"
DELTA_PREFIX = "delta_j="


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"state.judge.{field}: {why}")


def _checked_signals(signals: Any) -> dict[str, bool]:
    """The signal wall: a non-empty mapping of real bools (``1`` is a
    caller bug, not a pass — the settlement verdict wall's posture)."""
    if not isinstance(signals, Mapping) or not signals:
        raise _fail("signals", "must be a non-empty mapping of bools")
    out: dict[str, bool] = {}
    for key in sorted(signals):
        v = signals[key]
        if not isinstance(v, bool):
            raise _fail(f"signals.{key}", "must be a bool")
        out[str(key)] = v
    return out


def _checked_progress_delta(progress_delta: Any) -> float | None:
    """``None`` is the honest cold-start (unknown, never flat); a
    number must be finite."""
    if progress_delta is None:
        return None
    if isinstance(progress_delta, bool) \
            or not isinstance(progress_delta, (int, float)) \
            or not math.isfinite(float(progress_delta)):
        raise _fail("progress_delta",
                    "must be None or a finite number")
    return float(progress_delta)


def is_ambiguous(progress_delta: Any, signals: Any) -> bool:
    """The escalation gate: True iff the measured progress is flat
    (``|dP| <= AMBIGUITY_FLOOR``) OR the signals conflict (the verdict
    layers disagree). Missing measurement + agreeing signals = the
    mechanical base is trusted."""
    checked = _checked_signals(signals)
    delta = _checked_progress_delta(progress_delta)
    values = set(checked.values())
    if len(values) > 1:
        return True
    return delta is not None and abs(delta) <= AMBIGUITY_FLOOR


def _checked_band(band: Any) -> float:
    """The calibration band can only SHRINK the judge's reach: finite,
    in [0, DELTA_BOUND] — anything else is a caller bug."""
    if isinstance(band, bool) or not isinstance(band, (int, float)) \
            or not math.isfinite(float(band)):
        raise _fail("band", "must be a finite number")
    b = float(band)
    if not 0.0 <= b <= DELTA_BOUND:
        raise _fail("band",
                    f"must lie in [0, {DELTA_BOUND}], got {b}")
    return b


def judge_step(judge: Callable[[Mapping], Any], *, progress_delta: Any,
               signals: Any, band: Any = None) -> dict:
    """One gated judgment. Gate closed: the judge callable is NEVER
    invoked and the step's delta is exactly 0.0 (escalation is the
    only cost). Gate open: the callable receives the structured
    payload and its ruling is hard-clamped into ``[-bound, +bound]``
    — a non-finite or non-numeric ruling raises (a fabricated score
    never prices)."""
    if not callable(judge):
        raise _fail("judge", "must be a callable")
    bound = DELTA_BOUND if band is None else _checked_band(band)
    payload = {"progress_delta": _checked_progress_delta(progress_delta),
               "signals": _checked_signals(signals)}
    if not is_ambiguous(payload["progress_delta"], payload["signals"]):
        return {"escalated": False, "delta": 0.0, "raw": None,
                "bound": bound}
    raw = judge(payload)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) \
            or not math.isfinite(float(raw)):
        raise _fail("judge", "ruling must be a finite number")
    raw = float(raw)
    delta = round(max(-bound, min(bound, raw)), 6)
    return {"escalated": True, "delta": delta, "raw": raw,
            "bound": bound}


def effective_band(agreements: Any, *, base: Any = DELTA_BOUND) -> float:
    """The calibration posterior's effective band. ``agreements`` is
    the judge's modulation-vs-outcome history (True = the judge's
    direction matched the eventual outcome); the Laplace mean
    ``p = (a + 1) / (n + 2)`` scales the band as ``base x max(0,
    2p - 1)`` — monotone in agreement, neutral (0.0) at or below a
    coin flip, the full base on an empty history (trusted until
    evidence accumulates)."""
    b = _checked_band(base)
    if agreements is None or isinstance(agreements, (str, bytes)) \
            or not isinstance(agreements, Sequence):
        raise _fail("agreements", "must be a sequence of bools")
    values = list(agreements)
    for v in values:
        if not isinstance(v, bool):
            raise _fail("agreements", "every entry must be a bool")
    if not values:
        return round(b, 6)
    hits = sum(1 for v in values if v)
    p = (hits + 1.0) / (len(values) + 2.0)
    return round(b * max(0.0, 2.0 * p - 1.0), 6)


def _judgment_digest(rollout_id: str, dispatch_id: str, delta: float,
                     escalated: bool) -> str:
    payload = json.dumps(
        {"rollout_id": rollout_id, "dispatch_id": dispatch_id,
         "delta": round(delta, 6), "escalated": escalated},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def record_judgment(ws, *, rollout_id: str, dispatch_id: str,
                    delta: Any, escalated: bool, ts: str | None = None) \
        -> dict:
    """Land ONE escalated judgment as a credit=None telemetry row.
    The landing face re-enforces the clamp (the seam clamps already —
    a forged record must not resurrect the magnitude) and the digest
    is content-derived (never clock-derived)."""
    rid = _non_empty(rollout_id, "rollout_id")
    did = _non_empty(dispatch_id, "dispatch_id")
    if not isinstance(escalated, bool):
        raise _fail("escalated", "must be a bool")
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) \
            or not math.isfinite(float(delta)):
        raise _fail("delta", "must be a finite number")
    d = round(float(delta), 6)
    if abs(d) > DELTA_BOUND:
        raise _fail("delta",
                    f"|delta| {abs(d)} exceeds the designed bound "
                    f"{DELTA_BOUND}")
    return q_cells.append_observation(
        ws, _judgment_digest(rid, did, d, escalated), METHOD_FAMILY,
        credit=None, source=SOURCE, claim=rid, dispatch_id=did,
        fingerprint=f"{DELTA_PREFIX}{d}", reason=REASON, ts=ts)


def judgment_rows(ws, rollout_id: str) -> list[dict]:
    """This face's own ledger rows for ONE trajectory (claim carries
    the rollout identity), append order."""
    rid = _non_empty(rollout_id, "rollout_id")
    out: list[dict] = []
    for row in _cl.read(ws, "experience", schema_prefix="q-cell-obs"):
        if str(row.get("source") or "") != SOURCE \
                or str(row.get("method_family") or "") != METHOD_FAMILY:
            continue
        if str(row.get("claim") or "") != rid:
            continue
        out.append(row)
    return out


def _parse_delta(fingerprint: Any) -> float:
    """The STRICT fingerprint parse: exactly ``delta_j=<finite float>``
    or a raise (a tampered row must never silently price)."""
    if not isinstance(fingerprint, str) \
            or not fingerprint.startswith(DELTA_PREFIX):
        raise _fail("fingerprint",
                    f"malformed judgment fingerprint {fingerprint!r} "
                    f"(expected {DELTA_PREFIX!r}<delta>)")
    try:
        delta = float(fingerprint[len(DELTA_PREFIX):])
    except ValueError as exc:
        raise _fail("fingerprint",
                    f"malformed judgment fingerprint {fingerprint!r} "
                    "(the delta tail does not parse as a float)") \
            from exc
    if not math.isfinite(delta):
        raise _fail("fingerprint",
                    f"non-finite delta in judgment fingerprint "
                    f"{fingerprint!r}")
    return delta


def trajectory_delta(ws, rollout_id: str) -> float:
    """One trajectory's summed judge injection — the figure the
    cumulative cap binds. Deterministic from the ledger alone; fails
    closed on a poisoned row."""
    total = 0.0
    for row in judgment_rows(ws, rollout_id):
        total += _parse_delta(row.get("fingerprint"))
    return round(total, 6)
