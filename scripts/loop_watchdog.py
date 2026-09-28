#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loop_watchdog.py — the cron heartbeat's TRUE watchdog predicate
(event-wakeup topology, issue 434).

Topology: in-turn wakes arrive from the blocking dispatch return;
turn-exit is judged by the Stop WORKGUARD; between-turns wakes arrive
from worker completion notifications. The cron heartbeat is therefore
DEMOTE to a watchdog: it fires guidance ONLY when an expected event did
NOT arrive. The missed-event conditions (all mechanical, workspace
state):

  heartbeat-gap   the durable activity sidecar's newest row is older
                  than the gap budget (max(2 x interval, the stale
                  window)) — the expected cadence event never landed;
  stuck-worker    an in-progress worker whose pulse went quiet (mtime
                  past the stuck window) — the expected worker event
                  never landed;
  step-failure    a mechanical tick step failed (selfcheck / renew /
                  heartbeat) — the maintenance event the loop relies on
                  did not arrive green.

Everything else (fresh activity, healthy or delivered workers, green
steps) is the NORMAL-EVENT FLOW: the watchdog stays silent and the loop
wake is a NO-OP for the LLM. A delivered (done/blocked) worker is an
ARRIVED event — it never fires this face (settle faces belong to the
WORKGUARD).

Pure predicate: reads runs/.heartbeat.log (durable sidecar) with a
runs/.heartbeat.json last_tick_ts fallback, plus the worker-liveness
protocol. Fail-open: unreadable inputs read as 'no signal from that
source' (absent sidecar = cold start, not a gap) — never an exception.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation

#: Sources whose failure is a missed maintenance event (heartbeat_tick
#: rc summary weights the same three).
WATCHED_STEPS = ("selfcheck", "renew", "heartbeat")

GAP_FLOOR_MINUTES = 10.0


def _interval_minutes(ws: Path) -> float:
    p = Path(ws) / "runs" / ".heartbeat.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8")).get("interval_min")
        return float(raw) if raw else 0.0
    except (OSError, ValueError, TypeError):
        return 0.0


def last_activity(ws: Path) -> datetime | None:
    """Newest durable activity row ts (runs/.heartbeat.log), falling back
    to .heartbeat.json last_tick_ts. None when neither carries a parseable
    stamp (cold start — absence is not a gap). The tick captures this
    BEFORE appending its own row, so its own bookkeeping can never mask a
    real gap (evaluate's `activity` override)."""
    log = Path(ws) / "runs" / ".heartbeat.log"
    newest: datetime | None = None
    try:
        for line in log.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                ts = datetime.fromisoformat(
                    str(row.get("ts", "")).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if newest is None or ts > newest:
                newest = ts
    except OSError:
        newest = None
    if newest is not None:
        return newest
    p = Path(ws) / "runs" / ".heartbeat.json"
    try:
        ts = datetime.fromisoformat(str(
            json.loads(p.read_text(encoding="utf-8")).get(
                "last_tick_ts", "")).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (OSError, ValueError, TypeError):
        return None


def _stuck_workers(ws: Path) -> list[str]:
    """In-progress workers whose pulse went quiet, via the worker-liveness
    protocol owner. [] on every failure face."""
    try:
        from _hooks_path import load_hooks_lib
        mod = load_hooks_lib()
        states = mod.iter_worker_states(ws)
        _active, stuck = mod.scan_active_workers(ws, states=states)
        return [entry["worker"] for entry in stuck]
    except Exception as exc:  # noqa: BLE001 — the watchdog never crashes
        warn("loop_watchdog_workers", f"{type(exc).__name__}: {exc}")
        return []


def evaluate(ws: Path, *, failed_steps=(), now: datetime | None = None,
             activity: datetime | None = None) -> dict:
    """The missed-event verdict: {"fired": bool, "reasons": [str, ...]}.

    `failed_steps` comes from the tick's own rc summary (step names whose
    subprocess returned non-zero). `now` is injectable for determinism.
    `activity` overrides the durable-activity read (the tick passes the
    stamp captured BEFORE its own row append, so the tick's bookkeeping
    cannot mask a real gap; None means 'read it live'). Reasons are
    stable tokens: heartbeat-gap:<n>min / stuck-worker:<ids> /
    step-failure:<names>."""
    ws = Path(ws)
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    last = activity if activity is not None else last_activity(ws)
    if last is not None:
        gap_budget = max(2.0 * _interval_minutes(ws), GAP_FLOOR_MINUTES)
        gap_min = (now - last).total_seconds() / 60
        if gap_min > gap_budget:
            reasons.append(f"heartbeat-gap:{gap_min:.0f}min")

    stuck = _stuck_workers(ws)
    if stuck:
        reasons.append("stuck-worker:" + ",".join(sorted(stuck)))

    failed = [str(s) for s in failed_steps if str(s)]
    if failed:
        reasons.append("step-failure:" + ",".join(failed))

    return {"fired": bool(reasons), "reasons": reasons}
