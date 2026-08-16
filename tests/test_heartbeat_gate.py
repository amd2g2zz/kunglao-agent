# -*- coding: utf-8 -*-
"""tests/test_heartbeat_gate.py — heartbeat liveness gate F1 (#14, PRD M3).

RED: gate reads max(last_tick_ts, activity_ts) — an active tool (activity_ts) should be alive even if cron never ticked.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import worker_budget as wb


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _mins_ago(m: int) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(minutes=m))


def _make_hb(ws: Path, last_tick_ts: str, activity_ts: str | None = None) -> Path:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    data = {"last_tick_ts": last_tick_ts, "started_ts": last_tick_ts}
    if activity_ts is not None:
        data["activity_ts"] = activity_ts
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps(data), encoding="utf-8")
    state = ws / "loop-state.json"
    state.write_text("{}", encoding="utf-8")
    return state


def test_activity_ts_keeps_gate_alive(tmp_path):
    """F1 core: cron not ticking (last_tick 120min ago) but tool active (activity 1min ago) → alive."""
    state = _make_hb(tmp_path, last_tick_ts=_mins_ago(120), activity_ts=_mins_ago(1))
    alive, msg = wb.check_heartbeat_alive(state)
    assert alive, f"should be alive (activity_ts fresh): {msg}"


def test_both_stale_rejected(tmp_path):
    """both fields stale (120min) → STALE (correctly refuses to keep)."""
    state = _make_hb(tmp_path, last_tick_ts=_mins_ago(120), activity_ts=_mins_ago(120))
    alive, msg = wb.check_heartbeat_alive(state)
    assert not alive, "both fields stale must reject"


def test_cron_only_still_alive(tmp_path):
    """Regression: fresh cron tick (both fields 1min ago) → still alive."""
    state = _make_hb(tmp_path, last_tick_ts=_mins_ago(1), activity_ts=_mins_ago(1))
    alive, _ = wb.check_heartbeat_alive(state)
    assert alive


def test_no_activity_field_legacy_still_works(tmp_path):
    """legacy .heartbeat.json without activity_ts field → judged by last_tick_ts (backward compatible)."""
    state = _make_hb(tmp_path, last_tick_ts=_mins_ago(1), activity_ts=None)
    alive, _ = wb.check_heartbeat_alive(state)
    assert alive
