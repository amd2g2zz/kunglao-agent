# -*- coding: utf-8 -*-
"""tests/test_heartbeat_gate.py — heartbeat liveness gate F1 (#14, PRD M3).

RED: gate 读 max(last_tick_ts, activity_ts) — tool 活跃(activity_ts)即使 cron 不 tick 也应 alive。
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
    """F1 核心:cron 不 tick(last_tick 120min 前)但 tool 活跃(activity 1min 前)→ alive。"""
    state = _make_hb(tmp_path, last_tick_ts=_mins_ago(120), activity_ts=_mins_ago(1))
    alive, msg = wb.check_heartbeat_alive(state)
    assert alive, f"应 alive(activity_ts fresh): {msg}"


def test_both_stale_rejected(tmp_path):
    """两字段都 stale(120min)→ STALE(正确拒绝保留)。"""
    state = _make_hb(tmp_path, last_tick_ts=_mins_ago(120), activity_ts=_mins_ago(120))
    alive, msg = wb.check_heartbeat_alive(state)
    assert not alive, "两字段都 stale 应拒绝"


def test_cron_only_still_alive(tmp_path):
    """回归:cron tick 新(两字段都 1min 前)→ 仍 alive。"""
    state = _make_hb(tmp_path, last_tick_ts=_mins_ago(1), activity_ts=_mins_ago(1))
    alive, _ = wb.check_heartbeat_alive(state)
    assert alive


def test_no_activity_field_legacy_still_works(tmp_path):
    """legacy .heartbeat.json 无 activity_ts 字段 → 按 last_tick_ts 判(向后兼容)。"""
    state = _make_hb(tmp_path, last_tick_ts=_mins_ago(1), activity_ts=None)
    alive, _ = wb.check_heartbeat_alive(state)
    assert alive
