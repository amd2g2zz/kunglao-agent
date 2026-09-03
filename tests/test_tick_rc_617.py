# -*- coding: utf-8 -*-
"""tests/test_tick_rc_617.py — #617: tick failures must be operator-visible.

RED: the tick summary printed selfcheck_rc/renew_rc but never heartbeat_rc
(the rc that decides the exit); no ALERT banner; the persisted report had no
alarm field. Adjudicated fix: summary gains heartbeat_rc=, a loud banner on
any sub-rc != 0, and the report gains alert/first_failure (truncation-immune).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _load_tick(monkeypatch, sub_rcs):
    """Import heartbeat_tick with run() stubbed to return the given rcs."""
    spec = importlib.util.spec_from_file_location(
        "heartbeat_tick_uut", Path(__file__).resolve().parent.parent / "scripts" / "heartbeat_tick.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def fake_run(script, ws, *extra):
        key = script + "".join(extra)
        rc = sub_rcs.get(key, sub_rcs.get(script, 0))
        return {"script": script, "rc": rc, "stdout": f"{script} out", "stderr": ""}

    monkeypatch.setattr(mod, "run", fake_run)
    monkeypatch.setattr(mod, "_oracle_registered", lambda ws: True)
    return mod


def _tick(monkeypatch, tmp_path, sub_rcs, capsys):
    mod = _load_tick(monkeypatch, sub_rcs)
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)  # prod: earlier steps create it
    rc = mod.main([str(ws)])
    out = capsys.readouterr().out
    report = json.loads((ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
    return rc, out, report


def test_summary_prints_heartbeat_rc_on_failure(monkeypatch, tmp_path, capsys):
    """#617: heartbeat-check rc reaches the summary line (it decides the exit)."""
    rc, out, report = _tick(monkeypatch, tmp_path,
                            {"hook_activation.py--heartbeat-check": 1}, capsys)
    assert rc == 1
    assert "heartbeat_rc=1" in out
    assert "*** HEARTBEAT ALERT" in out


def test_failure_report_carries_alert_fields(monkeypatch, tmp_path, capsys):
    """Persisted report gains alert:true + first_failure (truncation-immune)."""
    rc, out, report = _tick(monkeypatch, tmp_path,
                            {"hook_activation.py--renew": 1}, capsys)
    assert rc == 1
    assert report["alert"] is True
    assert report["first_failure"]["rc"] == 1


def test_healthy_tick_no_alert(monkeypatch, tmp_path, capsys):
    """All rc=0 → exit 0, no banner, alert false, heartbeat_rc=0 still printed."""
    rc, out, report = _tick(monkeypatch, tmp_path, {}, capsys)
    assert rc == 0
    assert "heartbeat_rc=0" in out
    assert "*** HEARTBEAT ALERT" not in out
    assert report["alert"] is False
