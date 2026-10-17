# -*- coding: utf-8 -*-
"""tests/test_liveness_triad_682.py — the #682 scheduler liveness triad.

Three defects, three fixes + one regression pin:

  a) cadence_advisor.active_workers had NO freshness cut — a killed
     worker leaves an in-progress status tail whose stale mtime still
     counted as busy, pinning the advisor at FLOOR_MIN forever (live
     evidence: C006/C019; 94% of fires in [4,6] min over 156 ticks).
  b) heartbeat_touch seeded last_tick_ts from activity_ts (setdefault)
     — tool activity then masquerades as a tick for every last_tick_ts
     reader (monitor M5.2, external_kicker tick_fresh, resume). The tick
     stream is cron-owned; the activity stream is observation-only.
  c) the liveness dispatch gate (worker_budget_sinks.check_heartbeat_alive)
     and WORKGUARD (workguard.actionable_set) each demanded the other's
     precondition: dispatch REJECT (liveness) <-> turn-exit BLOCK
     (workguard). The fix shares the GATE'S OWN verdict as a workguard
     wall: a dead heartbeat walls the actionable set (legal sleep), so
     the retry loop cannot form.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _factories import write_claims_register, write_worker_status

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cadence_advisor as ca  # noqa: E402
import workguard  # noqa: E402

import worker_budget_sinks as wbs  # noqa: E402 (hooks/ on pytest pythonpath)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, [{"id": "C-1", "status": "OPEN",
                                "statement": "probe C-1"}])
    return ws


def _write_hb(ws: Path, state: dict) -> Path:
    p = ws / "runs" / ".heartbeat.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    return p


def _load_touch_hook():
    name = "heartbeat_touch_hook_682"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "heartbeat_touch.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


# ===========================================================================
# a) zombie workers must not pin the cadence at the floor
# ===========================================================================

def test_zombie_worker_does_not_pin_cadence_at_floor(tmp_path):
    """An in-progress status tail whose mtime aged past the freshness
    cut is a zombie: excluded from active_workers, and the advisor steps
    UP (quiet) instead of pinning at FLOOR_MIN."""
    ws = _mk_ws(tmp_path)
    write_worker_status(ws, "C006", "in-progress", age_min=30)  # zombie
    assert ca.active_workers(ws) == [], "stale in-progress tail still counted"
    outs = [ca.advise(ws) for _ in range(3)]
    out = outs[-1]
    assert out["evaluation_due"] is True
    assert out["recommended_interval_min"] == 10  # quiet: 5 -> +5
    assert "busy" not in out["reason"], out["reason"]
    assert out["sources"]["workers"] == []


def test_fresh_worker_still_counts_busy(tmp_path):
    """The freshness cut must not blind the advisor to LIVE workers."""
    ws = _mk_ws(tmp_path)
    write_worker_status(ws, "C006", "in-progress")  # fresh mtime
    assert ca.active_workers(ws) == ["C006"]
    outs = [ca.advise(ws) for _ in range(3)]
    out = outs[-1]
    assert "busy" in out["reason"], out["reason"]
    assert out["recommended_interval_min"] == 5  # floor via busy
    assert out["sources"]["workers"] == ["C006"]


# ===========================================================================
# b) tool activity must never seed / advance the tick signal
# ===========================================================================

def test_tool_touch_does_not_seed_last_tick_ts(tmp_path, monkeypatch):
    """A tool touch lands activity_ts ONLY. The reset-shaped state
    (no last_tick_ts) must stay without it — seeding from activity is
    exactly the #682(b) pollution."""
    ws = _mk_ws(tmp_path)
    now_z = _iso(_now())
    _write_hb(ws, {"started_ts": now_z, "interval_min": 5,
                   "tick_history": [now_z]})  # reset-shaped: no last_tick_ts
    hook = _load_touch_hook()
    monkeypatch.chdir(ws)
    assert hook.main() == 0
    data = json.loads(
        (ws / "runs" / ".heartbeat.json").read_text(encoding="utf-8"))
    assert "activity_ts" in data, "observation stream still lands"
    assert "last_tick_ts" not in data, (
        "tool activity seeded the tick signal (last_tick_ts)")


def test_tool_touch_does_not_advance_existing_last_tick_ts(
        tmp_path, monkeypatch):
    """An existing last_tick_ts is cron-owned: a touch never writes it."""
    ws = _mk_ws(tmp_path)
    then = _iso(_now() - timedelta(hours=2))
    _write_hb(ws, {"started_ts": then, "interval_min": 5,
                   "last_tick_ts": then, "tick_history": [then]})
    hook = _load_touch_hook()
    monkeypatch.chdir(ws)
    assert hook.main() == 0
    data = json.loads(
        (ws / "runs" / ".heartbeat.json").read_text(encoding="utf-8"))
    assert data["last_tick_ts"] == then, (
        "a tool touch advanced the cron-owned last_tick_ts")


def test_check_heartbeat_alive_reads_continuity_verdict(tmp_path):
    """Regression pin: the gate's authority is evaluate_tick_continuity,
    NOT last_tick_ts — a fresh last_tick_ts with no tick history REJECTs
    (the #754 single-tick blind spot stays closed even when a legacy
    writer refreshed last_tick_ts)."""
    ws = _mk_ws(tmp_path)
    state_path = ws / "analysis_state.txt"
    state_path.write_text("{}", encoding="utf-8")
    now_z = _iso(_now())
    _write_hb(ws, {"started_ts": now_z, "interval_min": 5,
                   "last_tick_ts": now_z, "activity_ts": now_z,
                   "loop_registered": True})  # no tick_history
    alive, msg = wbs.check_heartbeat_alive(state_path)
    assert alive is False, f"fresh last_tick_ts blinded the gate: {msg}"
    # two clean ticks flip the verdict — continuity, not the tick field
    old = _iso(_now() - timedelta(minutes=6))
    _write_hb(ws, {"started_ts": old, "interval_min": 5,
                   "last_tick_ts": now_z, "loop_registered": True,
                   "tick_history": [old, now_z]})
    alive, msg = wbs.check_heartbeat_alive(state_path)
    assert alive is True, msg


# ===========================================================================
# c) the liveness gate and WORKGUARD must not demand each other's precondition
# ===========================================================================

def _stale_hb_state() -> dict:
    then = _now() - timedelta(hours=2)
    return {"started_ts": _iso(then), "interval_min": 5,
            "last_tick_ts": _iso(then), "loop_registered": True,
            "tick_history": [_iso(then), _iso(then + timedelta(minutes=5))]}


def test_liveness_and_workguard_do_not_mutually_block(tmp_path):
    """Targeted repro of the #682(c) deadlock: stale heartbeat + OPEN
    claim. The gate rejects every dispatch AND workguard must NOT demand
    one — the liveness wall makes legal sleep, so the loop
    'dispatch REJECT -> stop BLOCK -> retry' cannot form."""
    ws = _mk_ws(tmp_path)
    state_path = ws / "analysis_state.txt"
    state_path.write_text("{}", encoding="utf-8")
    _write_hb(ws, _stale_hb_state())
    alive, _msg = wbs.check_heartbeat_alive(state_path)
    assert alive is False, "the repro premise: the gate rejects dispatches"
    res = workguard.actionable_set(ws)
    assert res["claims"] == [], (
        f"workguard still demands a dispatch the gate would reject: {res}")
    assert res["legal_sleep"] is True, res
    assert any(w["wall"] == "liveness" for w in res["walls"]), res


def test_live_heartbeat_does_not_wall(tmp_path):
    """Symmetric pin: a CONTINUOUS heartbeat never walls the DAG — the
    wall is the dead-heartbeat case only."""
    ws = _mk_ws(tmp_path)
    (ws / "analysis_state.txt").write_text("{}", encoding="utf-8")
    now = _now()
    _write_hb(ws, {"started_ts": _iso(now - timedelta(minutes=12)),
                   "interval_min": 5, "last_tick_ts": _iso(now),
                   "loop_registered": True,
                   "tick_history": [_iso(now - timedelta(minutes=6)),
                                    _iso(now)]})
    res = workguard.actionable_set(ws)
    assert [c["id"] for c in res["claims"]] == ["C-1"], res
    assert not any(w["wall"] == "liveness" for w in res["walls"]), res


def test_no_heartbeat_file_keeps_prior_workguard_behavior(tmp_path):
    """Fail-open posture: a workspace WITHOUT a heartbeat file (never
    opted into the dispatch gate) keeps the pre-#682 predicate — no
    liveness wall appears out of nowhere."""
    ws = _mk_ws(tmp_path)
    res = workguard.actionable_set(ws)
    assert [c["id"] for c in res["claims"]] == ["C-1"], res
    assert not any(w["wall"] == "liveness" for w in res["walls"]), res
