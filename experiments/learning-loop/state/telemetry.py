# -*- coding: utf-8 -*-
"""state/telemetry.py — the unified loop observability face (#915).

The owner directive (2026-10-30): exception-swallowing / log-coverage /
debuggability / observability are ONE problem, and the core rule is
**screen logging is NOT recording; only FILE logging counts.** Every
notable path in the rl-v2 loop lands a ``loop-telemetry/1`` ROW in the
consolidated ledger's TELEMETRY family (``runs/telemetry.jsonl`` via
``consolidated_ledger.append`` — the single-substrate rule: never a
parallel file, never stdout-only). The row shape::

    {schema, ts, lap, rollout_id, seam, event, detail}

``event`` is a dotted machine-sortable CODE from the CLOSED registry
(``CODES`` — "seam.event", e.g. ``terminator.TERM_LOSSCUT``); human
text rides ``detail``. Cross-run failure statistics are a group-by over
codes, not a grep.

The two-sided posture (the hooks/observer mirror):

- fail-CLOSED on the vocabulary: an unknown seam/event is a caller bug
  and raises BEFORE any write (a typo'd code must never read as
  recorded);
- fail-OPEN on the environment: a ledger-write failure is ONE warn +
  a named refusal receipt, never a raise into the caller — but the row
  is ALWAYS attempted (a telemetry layer that silently skips recording
  is the bug class this card kills).

The read faces are deterministic from the ledger alone: ``loop_summary``
(``loop-metrics/1`` — per-lap aggregates, ΔP/P series from the state
face's own transition rows, credit flow, the events group-by; an empty
ledger reads honest zeros), ``trace`` (one rollout's full row chain in
append order), ``trend`` (the P variance-profile statistic delegated to
#904's ``channel_pins.variance_profile``).

Registry codes with no runtime call site yet stay enumerated (the
closed vocab is the contract a future caller cannot typo):
``stagnation.STAG_ADVICE`` (the receipt face is pure/no-ws — its loop
caller lands the row), ``settlement.SETTLE_CLAMPED`` (the rail clamp
lives behind the scripts/ boundary), and
``selector.SELECT_POSTERIOR_CORRUPTED`` (the #909 carried gap: a
schema-valid garbage value in a posterior read is telemetry-visible).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent.parent          # learning-loop/
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from kunglao_log import warn  # noqa: E402 — the ONE canonical warn
from rlvr import consolidated_ledger as _cl  # noqa: E402
from state import channel_pins  # noqa: E402

#: the row stamps — every face names its schema (the receipt discipline)
SCHEMA = "loop-telemetry/1"
METRICS_SCHEMA = "loop-metrics/1"
TREND_SCHEMA = "loop-trend/1"

#: the CLOSED per-seam code registry — dotted "seam.event", aggregated
#: across runs by group-by. Fail-closed: an unknown code never writes.
CODES: frozenset[str] = frozenset({
    # terminator — the β rules and the one-shot watchdog's life cycle
    "terminator.TERM_WATCHDOG_ARMED",
    "terminator.TERM_WATCHDOG_FIRED",
    "terminator.TERM_WATCHDOG_CANCELLED",
    "terminator.TERM_LOSSCUT",
    "terminator.TERM_QUESTION_COVERED",
    # settlement — the two-phase landing's notable paths
    "settlement.SETTLE_DRAFTED",
    "settlement.SETTLE_COMMITTED",
    "settlement.SETTLE_DISCARDED",
    "settlement.SETTLE_CLAMPED",
    "settlement.SETTLE_REFUSED",
    # selector — batch-boundary prior moves, candidate-set widening,
    # and the #909 carried gap (schema-valid garbage in a read)
    "selector.SELECT_PRIOR_MOVED",
    "selector.SELECT_CANDIDATES_WIDENED",
    "selector.SELECT_EMPTY_CANDIDATES",
    "selector.SELECT_POSTERIOR_CORRUPTED",
    # assigner — the step assignment and its candidate widening
    "assigner.ASSIGN_ASSIGNED",
    "assigner.ASSIGN_WIDENED",
    # stagnation — the advisory receipt (re-plan advice, pre-death)
    "stagnation.STAG_ADVICE",
    # belief — the P(s) precursor snapshot landed / honest-empty
    "belief.BELIEF_SNAPSHOT",
    "belief.BELIEF_EMPTY_SPEC",
    # credit — the rail clamp on a banked value (injected != banked)
    "credit.CREDIT_V_CLAMPED",
})

_SEAMS: frozenset[str] = frozenset(
    dotted.split(".", 1)[0] for dotted in CODES)

#: the state face's transition-row encoding (progress.record_transition):
#: rows carry source="state" and fingerprint="delta_p=<float>" — the
#: ΔP series is read from the ledger's own rows, never recomputed.
progress_SOURCE = "state"
_DELTA_PREFIX = "delta_p="


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"state.telemetry.{field}: {why}")


def _now() -> str:
    from harness_common import utc_now_z  # noqa: PLC0415 — lazy
    return utc_now_z()


def _checked_lap(lap: Any) -> int | None:
    if lap is None:
        return None
    if isinstance(lap, bool) or not isinstance(lap, int) or lap < 0:
        raise _fail("lap", "must be None or a non-negative integer")
    return lap


def _checked_rollout(rollout_id: Any) -> str | None:
    if rollout_id is None:
        return None
    if not isinstance(rollout_id, str) or not rollout_id.strip():
        raise _fail("rollout_id", "must be None or a non-empty string")
    return rollout_id


def _checked_detail(detail: Any) -> Any:
    if detail is None or isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        return dict(detail)
    raise _fail("detail", "must be None, a string, or a mapping")


def emit(ws, seam: str, event: str, *, lap: int | None = None,
         rollout_id: str | None = None, detail: Any = None) -> dict:
    """Land ONE telemetry row — the file-logging rule. Fail-closed on
    the vocabulary (unknown seam/event raises BEFORE any write);
    fail-open on the environment (a ledger-write failure returns the
    named refusal receipt, never raises into the caller). The receipt:
    ``{emitted, reason, seam, event, lap, rollout_id}``."""
    if not isinstance(seam, str) or seam not in _SEAMS:
        raise _fail("seam", f"unknown seam {seam!r} — the registry is "
                            f"closed over {sorted(_SEAMS)}")
    if not isinstance(event, str) or f"{seam}.{event}" not in CODES:
        raise _fail("event", f"unknown code {seam + '.' + event!r} — the "
                             f"{seam!r} vocabulary is closed")
    lap_v = _checked_lap(lap)
    rid_v = _checked_rollout(rollout_id)
    doc = _checked_detail(detail)
    row = {"schema": SCHEMA, "ts": _now(), "seam": seam, "event":
           f"{seam}.{event}", "lap": lap_v, "rollout_id": rid_v,
           "detail": doc}
    try:
        appended = _cl.append(ws, "telemetry", row)
    except Exception as exc:  # noqa: BLE001 — telemetry never blocks
        warn("state.telemetry.emit",
             f"{seam}.{event}: {type(exc).__name__}: {exc} — telemetry "
             f"degraded, the row did not land, caller unaffected")
        return {"emitted": False, "reason": f"error:{type(exc).__name__}",
                "seam": seam, "event": f"{seam}.{event}", "lap": lap_v,
                "rollout_id": rid_v}
    return {"emitted": bool(appended),
            "reason": None if appended else "write-failed",
            "seam": seam, "event": f"{seam}.{event}", "lap": lap_v,
            "rollout_id": rid_v}


def events(ws) -> list[dict]:
    """Every landed loop-telemetry row, oldest first (the tolerant
    consolidated read)."""
    return _cl.read(ws, "telemetry", schema_prefix="loop-telemetry")


# ------------------------------------------------------ the read faces

def _trajectory(ws) -> list[dict]:
    from rlvr import q_cells  # noqa: PLC0415 — lazy (import weight)
    return q_cells.trajectory_rows(ws)


def _settlement_rows(ws) -> list[dict]:
    return _cl.read(ws, "settlement",
                    schema_prefix=("settlement-draft", "settlement-commit",
                                   "settlement-discard"))


def _delta_series(traj: list[dict]) -> list[float]:
    """The ΔP series from the state face's OWN transition rows
    (progress.record_transition encodes each delta in the row's
    ``fingerprint`` — ``delta_p=<float>``; append order)."""
    out: list[float] = []
    for row in traj:
        if str(row.get("source") or "") != progress_SOURCE:
            continue
        fp = str(row.get("fingerprint") or "")
        if not fp.startswith(_DELTA_PREFIX):
            continue
        try:
            out.append(float(fp[len(_DELTA_PREFIX):]))
        except ValueError:
            continue  # a torn fingerprint is an honest gap, not a zero
    return out


def _p_series(deltas: list[float]) -> list[float]:
    """The P trajectory: the cumulative sum of the ΔP series (P starts
    at the empty-tree 0.0 and walks the transitions in append order)."""
    out: list[float] = []
    total = 0.0
    for d in deltas:
        total = round(total + d, 6)
        out.append(total)
    return out


def _credit_flow(rows: list[dict]) -> dict:
    drafted = committed = 0.0
    discarded = 0
    for row in rows:
        stamp = str(row.get("schema") or "")
        if stamp == "settlement-draft/1":
            drafted += float(row.get("credit") or 0.0)
        elif stamp == "settlement-commit/1":
            committed += float(row.get("total_credit") or 0.0)
        elif stamp == "settlement-discard/1":
            discarded += 1
    return {"drafted": round(drafted, 6), "committed": round(committed, 6),
            "discarded": discarded}


def loop_summary(ws) -> dict:
    """The ``loop-metrics/1`` aggregates — deterministic from the
    ledger alone (no clock, no sampling): rollout/dispatch/verified
    counts, the ΔP and P series, credit flow, cost total, stagnation
    count, and the telemetry events grouped by code. An empty ledger
    reads honest zeros."""
    traj = _trajectory(ws)
    tel = events(ws)
    rollouts: set[str] = set()
    dispatches = verified = rollbacks = cost_n = 0
    cost = 0.0
    for row in traj:
        stamp = str(row.get("schema") or "")
        rid = str(row.get("rollout_id") or "")
        if rid:
            rollouts.add(rid)
        if stamp == "q-cell-action/1":
            kind = str(row.get("kind") or "")
            if kind == "assign_step":
                dispatches += 1
            elif kind == "rollback":
                rollbacks += 1
        elif stamp == "q-cell-result/1":
            if row.get("verified") is True:
                verified += 1
            c = row.get("cost")
            if isinstance(c, (int, float)) and not isinstance(c, bool):
                cost += float(c)
                cost_n += 1
    deltas = _delta_series(traj)
    group: dict[str, int] = {}
    laps: set[int] = set()
    for row in tel:
        code = str(row.get("event") or "")
        group[code] = group.get(code, 0) + 1
        lap = row.get("lap")
        if isinstance(lap, int) and not isinstance(lap, bool):
            laps.add(lap)
    return {
        "schema": METRICS_SCHEMA,
        "laps": sorted(laps),
        "rollouts": len(rollouts),
        "dispatches": dispatches,
        "verified_steps": verified,
        "rollback_count": rollbacks,
        "delta_series": deltas,
        "p_series": _p_series(deltas),
        "credit": _credit_flow(_settlement_rows(ws)),
        "cost_total": round(cost, 6) if cost_n else 0.0,
        "stagnation_count": group.get("stagnation.STAG_ADVICE", 0),
        "events": dict(sorted(group.items())),
    }


def trace(ws, rollout_id: str) -> list[dict]:
    """One rollout's full row chain in append order: the trajectory
    rows (action/result/obs) and the telemetry rows carrying its
    rollout_id, stable-sorted by the rows' own ``ts`` (ties keep the
    per-family append order — experience first). Deterministic from
    the ledger alone."""
    if not isinstance(rollout_id, str) or not rollout_id.strip():
        raise _fail("rollout_id", "must be a non-empty string")
    rid = rollout_id
    chain = [row for row in _trajectory(ws)
             if str(row.get("rollout_id") or "") == rid]
    chain += [row for row in events(ws)
              if str(row.get("rollout_id") or "") == rid]
    return sorted(chain, key=lambda r: str(r.get("ts") or ""))


def trend(ws) -> dict:
    """The P variance-profile series — #904's ``variance_profile``
    statistic over the P history the ledger carries. Fewer than two P
    points is the honest empty (``profile: None``), never a fabricated
    profile."""
    p = _p_series(_delta_series(_trajectory(ws)))
    if len(p) < 2:
        return {"schema": TREND_SCHEMA, "points": len(p), "profile": None,
                "dark_room_flag": False}
    profile = channel_pins.variance_profile(p)
    return {"schema": TREND_SCHEMA, "points": len(p), "profile": profile,
            "dark_room_flag": bool(profile["dark_room_flag"])}
