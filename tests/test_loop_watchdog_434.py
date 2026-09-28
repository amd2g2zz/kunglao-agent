# -*- coding: utf-8 -*-
"""tests/test_loop_watchdog_434.py — cron heartbeat demotes to TRUE
watchdog (issue 434).

Topology: in-turn wakes come from the blocking dispatch return; turn-exit
wakes from the Stop WORKGUARD; between-turns wakes from worker completion.
The cron heartbeat therefore fires ONLY when an expected event did NOT
arrive — pinned here:

  - normal-event flow (fresh activity, healthy workers, green steps)
    does NOT fire the loop guidance injection;
  - a missed-event fixture (activity gap / silent worker / failed step)
    DOES fire, with the reason named.

The tick report carries the verdict as report["watchdog"]; the loop
prompt's body reads it (quiet -> NO-OP wake).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _factories import write_claims_register, write_hook_state, \
    write_worker_status

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TICK = SCRIPTS / "heartbeat_tick.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _mk_ws(tmp_path: Path, claims: list[dict] | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, claims or [])
    write_hook_state(ws, active_hooks=["cost_gate"])
    return ws


def _register_heartbeat(ws: Path) -> None:
    """A registered, fresh heartbeat so the tick's heartbeat-check step
    passes (an unregistered heartbeat IS a missed maintenance event and
    correctly fires the watchdog)."""
    now = datetime.now(timezone.utc)
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps({
        "started_ts": _iso(now - timedelta(minutes=10)),
        "last_tick_ts": _iso(now - timedelta(minutes=1)),
        "interval_min": 5, "loop_registered": True}), encoding="utf-8")


def _activity_row(ws: Path, minutes_ago: float, actor: str = "tick") -> None:
    log = ws / "runs" / ".heartbeat.log"
    ts = _iso(datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": ts, "actor": actor}) + "\n")


class TestWatchdogPredicate:
    def test_normal_event_flow_does_not_fire(self, tmp_path):
        """Fresh activity (a tick 2 min ago), no workers, no failed steps —
        every expected event arrived; the watchdog stays silent."""
        import loop_watchdog
        ws = _mk_ws(tmp_path)
        _activity_row(ws, minutes_ago=2)
        res = loop_watchdog.evaluate(ws)
        assert res["fired"] is False, res
        assert res["reasons"] == []

    def test_activity_gap_fires(self, tmp_path):
        """The durable sidecar's newest row is older than the gap budget —
        the expected cadence event did not arrive."""
        import loop_watchdog
        ws = _mk_ws(tmp_path)
        (ws / "runs" / ".heartbeat.json").write_text(json.dumps(
            {"started_ts": _iso(datetime.now(timezone.utc)),
             "interval_min": 5}), encoding="utf-8")
        _activity_row(ws, minutes_ago=25)
        res = loop_watchdog.evaluate(ws)
        assert res["fired"] is True, res
        assert any("heartbeat" in r for r in res["reasons"]), res

    def test_silent_worker_fires(self, tmp_path):
        """An in-progress worker whose pulse went quiet — the expected
        worker event did not arrive."""
        import loop_watchdog
        ws = _mk_ws(tmp_path)
        _activity_row(ws, minutes_ago=2)
        write_worker_status(ws, "w1", "in-progress", age_min=45)
        res = loop_watchdog.evaluate(ws)
        assert res["fired"] is True, res
        assert any("stuck" in r for r in res["reasons"]), res

    def test_failed_step_fires(self, tmp_path):
        """A mechanical step failure (the tick chain is broken) is a missed
        maintenance event."""
        import loop_watchdog
        ws = _mk_ws(tmp_path)
        _activity_row(ws, minutes_ago=2)
        res = loop_watchdog.evaluate(ws, failed_steps=["heartbeat"])
        assert res["fired"] is True, res
        assert any("heartbeat" in r for r in res["reasons"]), res

    def test_returned_worker_is_not_a_missed_event(self, tmp_path):
        """A done worker is an ARRIVED event (the completion wake) — the
        watchdog must not fire on it (that face belongs to the WORKGUARD)."""
        import loop_watchdog
        ws = _mk_ws(tmp_path)
        _activity_row(ws, minutes_ago=2)
        write_worker_status(ws, "w1", "done")
        res = loop_watchdog.evaluate(ws)
        assert res["fired"] is False, res


class TestTickReportCarriesWatchdog:
    def test_report_has_watchdog_quiet_on_healthy_ws(self, tmp_path):
        """The real tick CLI writes report['watchdog'] — quiet when the
        workspace is healthy (normal-event flow -> no guidance injection)."""
        ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
        _register_heartbeat(ws)
        _activity_row(ws, minutes_ago=1)
        r = subprocess.run(
            [sys.executable, str(TICK), str(ws)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180)
        report = json.loads(
            (ws / "runs" / ".heartbeat-tick.json").read_text(
                encoding="utf-8"))
        wd = report.get("watchdog")
        assert isinstance(wd, dict), f"watchdog face missing: {sorted(report)}"
        assert wd["fired"] is False, (wd, r.stdout[-400:])
        assert wd["reasons"] == []

    def test_report_watchdog_fires_on_stale_activity(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _activity_row(ws, minutes_ago=40)
        subprocess.run(
            [sys.executable, str(TICK), str(ws)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180)
        report = json.loads(
            (ws / "runs" / ".heartbeat-tick.json").read_text(
                encoding="utf-8"))
        wd = report.get("watchdog")
        assert isinstance(wd, dict) and wd["fired"] is True, wd
        assert wd["reasons"], wd
