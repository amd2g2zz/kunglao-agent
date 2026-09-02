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
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from _factories import write_hook_state

ROOT = Path(__file__).resolve().parents[1]
TICK = ROOT / "scripts" / "heartbeat_tick.py"
SCRIPTS = TICK.parent

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
    write_hook_state(ws, active_hooks=["cost_gate"], ts=_iso(datetime.now(timezone.utc)),
                     tier="none", phase="IDLE", user_override={},
                     expires_at=expires_at)


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


def _drifted_scratch_skill(tmp_path: Path) -> Path:
    """Scratch copy of the tick chain scripts with a registry rename (#381).

    scratch/scripts/wire_up_settings.py says heartbeat_touch_v2.py while
    hooks_selfcheck's chain table still names heartbeat_touch.py — the exact
    import-time ValueError a conscious-mirror gap produces. The tick resolves
    SCRIPTS from its own __file__, so running the scratch copy drives the REAL
    subprocess drift (no monkeypatch can reach a child process).
    """
    skill = tmp_path / "scratch_skill"
    (skill / "scripts").mkdir(parents=True)
    # template_version.py rides the copy set (#536: hooks_selfcheck imports
    # it for the stamp verify — a scratch copy without it dies on
    # ModuleNotFoundError instead of the intended registry-drift ValueError).
    # kunglao_log.py rides the copy set (#534: heartbeat_tick module-level
    # emits on load — without it the tick ModuleNotFoundErrors before even
    # reaching the registry drift).
    # liveness_policy.py rides the copy set (#597: heartbeat_tick/
    # hook_activation/heartbeat import their minutes constants from it —
    # a scratch copy without it dies on ModuleNotFoundError at import).
    # utf8_boot.py rides the copy set (#811: heartbeat_tick entry imports
    # force_utf8 — a scratch copy without it dies on ModuleNotFoundError
    # instead of the intended registry-drift ValueError).
    # ws_layout.py + env_manifest.py ride the copy set (#863 Family C:
    # heartbeat_tick delegates _resolve_ws to ws_layout, which resolves
    # layout names from env_manifest — a scratch copy without either dies
    # on ModuleNotFoundError instead of the intended registry-drift
    # ValueError).
    for f in ("heartbeat_tick.py", "hook_activation.py", "hooks_selfcheck.py",
              "wire_up_settings.py", "reconcile_workers.py", "heartbeat.py",
              "template_version.py", "kunglao_log.py", "liveness_policy.py",
              "utf8_boot.py", "ws_layout.py", "env_manifest.py"):
        shutil.copy2(SCRIPTS / f, skill / "scripts" / f)
    wu = skill / "scripts" / "wire_up_settings.py"
    wu.write_text(
        wu.read_text(encoding="utf-8").replace(
            "heartbeat_touch.py", "heartbeat_touch_v2.py"),
        encoding="utf-8")
    return skill


class TestTickSelfcheckFailure:
    def test_tick_report_carries_selfcheck_failure(self, tmp_path):
        """#381 F1: a drifted registry makes hooks_selfcheck crash at import —
        the tick must surface that failure, not report success.

        Pre-fix behavior: run() stores only the subprocess stdout tail, so the
        ValueError traceback (stderr) is dropped from the report, and main()
        weighs only renew/heartbeat rc — the crashed selfcheck leaves the tick
        exiting 0. Silent drift through the tick path while the direct CLI is
        loud. The ws is seeded healthy (fresh heartbeat + empty analysis
        state) so selfcheck is the ONLY failing step: exit 1 must come from
        the selfcheck, not from an unrelated stale heartbeat.
        """
        skill = _drifted_scratch_skill(tmp_path)
        ws = _make_ws(tmp_path)
        (ws / "analysis_state.txt").write_text("", encoding="utf-8")
        (ws / "runs" / ".heartbeat.json").write_text(json.dumps({
            "started_ts": _iso(datetime.now(timezone.utc)),
            "last_tick_ts": _iso(datetime.now(timezone.utc))}),
            encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(skill / "scripts" / "heartbeat_tick.py"), str(ws)],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        report = json.loads(
            (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
        assert report["selfcheck"]["rc"] != 0, (
            "a registry drift that crashes hooks_selfcheck must be visible "
            f"in the report: {report['selfcheck']}")
        assert "heartbeat_touch.py" in report["selfcheck"].get("stderr", ""), (
            "the selfcheck failure text (stderr tail) must ride the report — "
            "stdout-only storage drops the ValueError traceback: "
            f"{report['selfcheck']}")
        assert r.returncode == 1, (
            "a failed selfcheck must fail the tick (exit 1 = LLM must act), "
            f"not report success: rc={r.returncode}")
