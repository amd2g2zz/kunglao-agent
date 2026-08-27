# -*- coding: utf-8 -*-
"""tests/test_ttl_warn_613.py — #613: TTL expiry must be observable.

RED: is_active_strict silently returns False on expiry — no marker, no stderr.
Adjudicated fix: first refusal per expired window writes a one-shot
runs/.hook-slept.json (ts / expired_at / gap_seconds / hooks_affected) + one
stderr WARNING line. Write-once per expires_at; fail-open on write errors;
semantics (return False) unchanged; no auto-renew.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hook_activation as ha  # noqa: E402


def _expired_state(hooks=("dispatch_gate", "worker_pulse")) -> dict:
    exp = (datetime.now(tz=timezone.utc) - timedelta(minutes=42)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"expires_at": exp, "active_hooks": list(hooks), "paused_hooks": []}


def _fresh_state(hooks=("dispatch_gate",)) -> dict:
    exp = (datetime.now(tz=timezone.utc) + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"expires_at": exp, "active_hooks": list(hooks), "paused_hooks": []}


def test_expired_state_writes_marker_and_warns(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ha.write_state(ws, _expired_state())
    err = io.StringIO()
    with redirect_stderr(err):
        active = ha.is_active_strict(ws, "dispatch_gate")
    assert active is False
    marker = ws / "runs" / ".hook-slept.json"
    assert marker.exists(), "first refusal must write the one-shot marker"
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["expired_at"] == _expired_state()["expires_at"]
    assert data["gap_seconds"] >= 42 * 60 - 60  # ~42 min gap
    assert data["hooks_affected"] == ["dispatch_gate", "worker_pulse"]
    assert "WARNING" in err.getvalue() and "expired" in err.getvalue()


def test_fresh_state_no_marker_no_warn(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ha.write_state(ws, _fresh_state())
    err = io.StringIO()
    with redirect_stderr(err):
        active = ha.is_active_strict(ws, "dispatch_gate")
    assert active is True
    assert not (ws / "runs" / ".hook-slept.json").exists()
    assert "WARNING" not in err.getvalue()


def test_marker_write_once_per_expired_window(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ha.write_state(ws, _expired_state())
    for _ in range(3):
        with redirect_stderr(io.StringIO()):
            ha.is_active_strict(ws, "dispatch_gate")
    marker = ws / "runs" / ".hook-slept.json"
    first = json.loads(marker.read_text(encoding="utf-8"))
    mtime_first = marker.stat().st_mtime_ns
    with redirect_stderr(io.StringIO()):
        ha.is_active_strict(ws, "worker_pulse")
    assert marker.stat().st_mtime_ns == mtime_first, "same expires_at → marker not rewritten"
    assert json.loads(marker.read_text(encoding="utf-8")) == first


def test_marker_write_failure_fail_open(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    ha.write_state(ws, _expired_state())
    def boom(*a, **k):
        raise OSError("read-only")
    monkeypatch.setattr("pathlib.Path.mkdir", boom)
    with redirect_stderr(io.StringIO()):
        active = ha.is_active_strict(ws, "dispatch_gate")
    assert active is False, "marker failure must never change the gate verdict"


def test_no_state_file_still_silent(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    err = io.StringIO()
    with redirect_stderr(err):
        active = ha.is_active_strict(ws, "dispatch_gate")
    assert active is False  # default-inactive unchanged
    assert not (ws / "runs").exists() or not (ws / "runs" / ".hook-slept.json").exists()
    assert "WARNING" not in err.getvalue()
