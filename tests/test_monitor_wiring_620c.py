# -*- coding: utf-8 -*-
"""tests/test_monitor_wiring_620c.py — #620 Gap C: the orphan monitor gets a
runtime consumer.

RED (adjudicated): kunglao-monitor.py has ZERO runtime callers (grep: only
tests/docs/manifest) — stuck_watch/help_watch/health_check/detect_drift are
built-but-not-wired (#38 precedent). Adjudicated fix (Gap C, 20-line wiring):
heartbeat_tick gains a `monitor` report field by running kunglao-monitor
--json; #88 freeze: monitor is BACKGROUND advisory — it must NEVER change the
tick's rc, never block, and its absence/crash must be fail-open.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location("heartbeat_tick_620", ROOT / "scripts" / "heartbeat_tick.py")
ht = importlib.util.module_from_spec(_spec); sys.modules["heartbeat_tick_620"] = ht; _spec.loader.exec_module(ht)  # noqa: E402


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _tick(monkeypatch, ws, monitor_result):
    calls = {}

    def fake_run(script, ws_arg, *extra):
        calls[script + "".join(extra)] = True
        if script == "kunglao-monitor.py":
            return monitor_result
        return {"script": script, "rc": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(ht, "run", fake_run)
    monkeypatch.setattr(ht, "_oracle_registered", lambda w: True)
    rc = ht.main([str(ws)])
    report = json.loads((ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
    return rc, report, calls


def test_tick_runs_monitor_and_records_report(monkeypatch, tmp_path):
    ws = _mk_ws(tmp_path)
    mon = {"script": "kunglao-monitor.py", "rc": 0, "stdout": '{"next": "ok"}', "stderr": ""}
    rc, report, calls = _tick(monkeypatch, ws, mon)
    assert any("kunglao-monitor" in k for k in calls), \
        "tick must invoke the monitor (Gap C wiring)"
    assert "monitor" in report, "monitor output must land in the tick report"
    assert rc == 0


def test_monitor_crash_is_fail_open(monkeypatch, tmp_path):
    """#88 freeze: a crashed monitor must NEVER fail the tick."""
    ws = _mk_ws(tmp_path)
    mon = {"script": "kunglao-monitor.py", "rc": 1, "stdout": "", "stderr": "boom"}
    rc, report, _ = _tick(monkeypatch, ws, mon)
    assert rc == 0, "monitor rc must not weigh into the tick exit (#88 advisory)"
    assert report.get("monitor", {}).get("rc") == 1, "failure recorded, not swallowed"


def test_monitor_rc_not_in_exit_aggregation(monkeypatch, tmp_path):
    """Explicit pin: tick exit stays 0 with monitor rc=1 even when all else is green."""
    ws = _mk_ws(tmp_path)
    rc, report, _ = _tick(monkeypatch, ws,
                          {"script": "kunglao-monitor.py", "rc": 1, "stdout": "", "stderr": ""})
    assert rc == 0
    assert report["alert"] is False, "monitor failure is not a tick alert (advisory face)"
