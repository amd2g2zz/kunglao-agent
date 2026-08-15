# -*- coding: utf-8 -*-
"""tests/test_heartbeat_tick.py — renewal-margin early warning in step 6 (issue #365).

The hook-activation TTL (30 min) makes gates sleep SILENTLY when the tick
chain is ALIVE but its cadence is mismatched with the TTL: a renewal landing
close to expiry leaves no visible anomaly anywhere else. Step 6 (renew) must
measure the PRE-renewal margin (expires_at - now) and warn when it is low —
diagnostic only: the renewal always proceeds, and the margin computation must
never fail the tick (fail-open on missing/corrupt state).

These tests drive the real tick CLI via subprocess (same convention as
tests/test_router_runtime.py, issue #370) against a scratch workspace.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICK = ROOT / "scripts" / "heartbeat_tick.py"

# Exact stdout line pinned by the issue body (#365).
WARN_LINE = "[hooks] renewal margin low (<10 min) — check tick cadence vs 30-min TTL"


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_ws(tmp_path: Path) -> Path:
    """Minimal workspace (claim-register.yaml so the chain scripts accept it)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _set_hook_state(ws: Path, expires_at: str) -> None:
    """Fabricate .hook_state.json with a controlled expires_at."""
    (ws / ".hook_state.json").write_text(json.dumps({
        "ts": _iso(datetime.now(timezone.utc)),
        "tier": "none",
        "phase": "IDLE",
        "active_hooks": ["cost_gate"],
        "paused_hooks": [],
        "user_override": {},
        "expires_at": expires_at,
    }), encoding="utf-8")


def _tick(ws: Path) -> tuple[dict, str]:
    """Run the real tick CLI; return (report dict, stdout)."""
    r = subprocess.run(
        [sys.executable, str(TICK), str(ws)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    report = json.loads(
        (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
    return report, r.stdout


class TestRenewMarginLow:
    def test_low_margin_reported_and_printed(self, tmp_path):
        """#365 core: expires_at 5 min out → report gains renew_margin_low: true
        + the exact stdout one-liner. Margin is measured BEFORE --renew runs."""
        ws = _make_ws(tmp_path)
        _set_hook_state(ws, _iso(datetime.now(timezone.utc) + timedelta(minutes=5)))
        report, stdout = _tick(ws)
        assert report.get("renew_margin_low") is True
        assert WARN_LINE in stdout

    def test_healthy_margin_no_field_no_line(self, tmp_path):
        """Healthy margin (25 min left) → no field, no line — warning must stay
        silent when cadence is fine, or it becomes noise."""
        ws = _make_ws(tmp_path)
        _set_hook_state(ws, _iso(datetime.now(timezone.utc) + timedelta(minutes=25)))
        report, stdout = _tick(ws)
        assert "renew_margin_low" not in report
        assert "[hooks] renewal margin low" not in stdout

    def test_expired_state_still_warns(self, tmp_path):
        """Negative margin (already expired 2 min ago) is also < 10 min → warn:
        this is the worst case — the gate window has already silently opened."""
        ws = _make_ws(tmp_path)
        _set_hook_state(ws, _iso(datetime.now(timezone.utc) - timedelta(minutes=2)))
        report, stdout = _tick(ws)
        assert report.get("renew_margin_low") is True
        assert WARN_LINE in stdout

    def test_corrupt_state_fail_open_tick_continues(self, tmp_path):
        """Fail-open: garbage .hook_state.json → no warning, no crash; the
        renew step still runs (rc 0) — the check must never break the tick."""
        ws = _make_ws(tmp_path)
        (ws / ".hook_state.json").write_text("{not json", encoding="utf-8")
        report, stdout = _tick(ws)
        assert "renew_margin_low" not in report
        assert "[hooks] renewal margin low" not in stdout
        assert report["renew"]["rc"] == 0

    def test_missing_state_file_fail_open(self, tmp_path):
        """No .hook_state.json at all (fresh workspace) → no warning; renew
        still performs the first activation (rc 0)."""
        ws = _make_ws(tmp_path)
        report, stdout = _tick(ws)
        assert "renew_margin_low" not in report
        assert "[hooks] renewal margin low" not in stdout
        assert report["renew"]["rc"] == 0
