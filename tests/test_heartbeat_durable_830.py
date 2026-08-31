# -*- coding: utf-8 -*-
"""tests/test_heartbeat_durable_830.py - #830 durable tick sidecar (TDD).

Tests:
  D1 delete-cache-still-judged
  D2 tampered-cache-log-wins
  D3 register-cannot-reset-history
  D4 no-log legacy compat
  D5 writers append sidecar
  D6 gate consumer passes log_path
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import heartbeat  # noqa: E402
from liveness_policy import STALE_MINUTES  # noqa: E402

NOW = datetime.now(timezone.utc)


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _append_log(ws, stamps, actor="test"):
    log = ws / "runs" / ".heartbeat.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        for dt in stamps:
            line = json.dumps({"ts": _ts(dt), "actor": actor})
            fh.write(line + "\n")
    return log


def _cache(ws, history):
    hb = ws / "runs" / ".heartbeat.json"
    state = {
        "started_ts": _ts(NOW - timedelta(minutes=40)),
        "interval_min": 5,
        "loop_registered": True,
        "last_tick_ts": _ts(NOW),
        "tick_history": history,
    }
    hb.write_text(json.dumps(state), encoding="utf-8")
    return hb


def test_delete_cache_still_judged_from_durable_log(tmp_path):
    ws = _mk_ws(tmp_path)
    recent = [NOW - timedelta(minutes=5 * i) for i in (3, 2, 1)]
    _append_log(ws, recent)
    _cache(ws, history=[])
    alive, detail = heartbeat.evaluate_tick_continuity(
        json.loads((ws / "runs" / ".heartbeat.json").read_text(encoding="utf-8")),
        log_path=ws / "runs" / ".heartbeat.log")
    assert alive is True
    assert "durable" in detail.lower()


def test_tampered_cache_log_wins(tmp_path):
    ws = _mk_ws(tmp_path)
    stale_ticks = [NOW - timedelta(minutes=m) for m in (50, 45, 40)]
    _append_log(ws, stale_ticks)
    _cache(ws, history=[_ts(NOW - timedelta(minutes=2)),
                        _ts(NOW - timedelta(minutes=1))])
    state = json.loads((ws / "runs" / ".heartbeat.json").read_text(encoding="utf-8"))
    alive, detail = heartbeat.evaluate_tick_continuity(
        state, log_path=ws / "runs" / ".heartbeat.log")
    assert alive is False
    assert "durable" in detail.lower() and "stale" in detail.lower()


def test_register_cannot_reset_history(tmp_path):
    ws = _mk_ws(tmp_path)
    old = [NOW - timedelta(minutes=50, seconds=s) for s in (2, 1, 0)]
    _append_log(ws, old)
    (ws / "runs" / ".heartbeat.json").unlink(missing_ok=True)
    rc = heartbeat.heartbeat_register(ws)
    assert rc == 0
    log = ws / "runs" / ".heartbeat.log"
    lines = [json.loads(x) for x in
             log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 4
    state = json.loads((ws / "runs" / ".heartbeat.json").read_text(encoding="utf-8"))
    alive, detail = heartbeat.evaluate_tick_continuity(state, log_path=log)
    assert alive is False
    assert "gap" in detail.lower()


def test_no_log_legacy_compat(tmp_path):
    ws = _mk_ws(tmp_path)
    hist = [_ts(NOW - timedelta(minutes=5)), _ts(NOW - timedelta(minutes=2))]
    _cache(ws, history=hist)
    state = json.loads((ws / "runs" / ".heartbeat.json").read_text(encoding="utf-8"))
    alive_a, detail_a = heartbeat.evaluate_tick_continuity(state)
    alive_b, detail_b = heartbeat.evaluate_tick_continuity(
        state, log_path=ws / "runs" / ".heartbeat.log.missing")
    assert (alive_a, detail_a) == (alive_b, detail_b)
    assert alive_a is True


def test_writers_append_sidecar(tmp_path):
    ws = _mk_ws(tmp_path)
    rc = heartbeat.heartbeat_register(ws)
    assert rc == 0
    log = ws / "runs" / ".heartbeat.log"
    lines = [json.loads(x) for x in
             log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["actor"] == "register"
    assert lines[0]["ts"].endswith("Z")
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "heartbeat_touch.py"), str(ws)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    lines2 = [json.loads(x) for x in
              log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines2) == 2
    assert lines2[1]["actor"] == "touch"


def test_gate_consumer_passes_log_path(tmp_path):
    ws = _mk_ws(tmp_path)
    recent = [NOW - timedelta(minutes=5 * i) for i in (3, 2, 1)]
    _append_log(ws, recent)
    _cache(ws, history=[])
    import importlib.util
    saved = list(sys.path)
    sys.path.insert(0, str(ROOT / "hooks"))
    try:
        spec = importlib.util.spec_from_file_location(
            "wbs_830", ROOT / "hooks" / "worker_budget_sinks.py")
        wbs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wbs)
    finally:
        sys.path[:] = saved
    state_path = ws / ".hook_state.json"
    state_path.write_text("{}", encoding="utf-8")
    alive, detail = wbs.check_heartbeat_alive(state_path)
    assert alive is True
    assert "durable" in detail.lower()
