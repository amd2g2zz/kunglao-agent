# -*- coding: utf-8 -*-
"""tests/test_renew_audit_619.py — #619: renew gets an audit trail.

RED: renew() overwrote expires_at/ts with zero record of WHO renewed, whether
the prior state was expired, or how long the gap was — postmortems of "why did
the heartbeat die" had nothing. Adjudicated fix (方案 B): audit into the
existing kunglao_log event stream (action=renew + was_expired + expiry_gap_s),
NOT into .hook_state.json (state stays minimal).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hook_activation as ha  # noqa: E402
import kunglao_log  # noqa: E402


def _expired_state() -> dict:
    exp = (datetime.now(tz=timezone.utc) - timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"expires_at": exp, "tier": "advisory", "phase": "DISPATCH",
            "active_hooks": ["dispatch_gate"], "paused_hooks": []}


def _read_events(ws: Path) -> list[dict]:
    log = ws / "runs" / "logs"
    rows = []
    if log.exists():
        for f in sorted(log.glob("kunglao-*.jsonl")):
            rows += [json.loads(ln) for ln in
                     f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return rows


def test_renew_on_expired_state_logs_gap(tmp_path):
    ws = tmp_path / "ws"; (ws / "runs").mkdir(parents=True)
    ha.write_state(ws, _expired_state())
    ha.renew(ws)
    events = _read_events(ws)
    ev = [e for e in events if e["action"] == "renew"]
    assert ev, "renew must emit action=renew"
    assert "was_expired" in ev[-1]["detail"]
    assert "expiry_gap_s" in ev[-1]["detail"]


def test_renew_on_fresh_state_still_logs(tmp_path):
    ws = tmp_path / "ws"; (ws / "runs").mkdir(parents=True)
    exp = (datetime.now(tz=timezone.utc) + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ha.write_state(ws, {"expires_at": exp, "tier": "advisory",
                        "phase": "DISPATCH", "active_hooks": [], "paused_hooks": []})
    ha.renew(ws)
    ev = [e for e in _read_events(ws) if e["action"] == "renew"]
    assert ev and "was_expired=false" in ev[-1]["detail"]


def test_log_failure_never_breaks_renew(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; (ws / "runs").mkdir(parents=True)
    ha.write_state(ws, _expired_state())

    def boom(*a, **k):
        raise OSError("read-only")
    monkeypatch.setattr("kunglao_log.emit", boom)
    state = ha.renew(ws)  # must not raise
    assert "expires_at" in state
