# -*- coding: utf-8 -*-
"""tests/test_gate_pass_mechanisms_1086.py — #1086 S20: cheap mechanisms in
the zero-LLM gate pass.

S18 closed the bypass: the OS cron runs the wake-gate wrapper, a QUIET
verdict injects nothing, and the quiet day stops burning model turns. But
run_due's only production host is the tick's UNPARKED machinery pass — a
quiet day is a parked day, and the #740 parked posture skipped the
machinery entirely, so the tick-channel clocks (env freshness, premise
expiry, rotation induction) lost their only run window exactly when
nothing else was moving.

This module pins the S20 posture:

  1. the zero-LLM host marker rides the WRAPPER's own gate invocation
     (--zero-llm): the in-session tick the loop prompt teaches (gate mode,
     no marker) keeps the FULL machinery — expensive mechanisms and the
     think seat keep their WAKE-turn host;
  2. a zero-LLM pass dispatches ONLY cost_class: cheap tick mechanisms —
     medium/expensive are ceiling SKIPS carrying the S20 reason, not
     budget drops (the drops counter stays a time-cap casualty count);
  3. the 'parked' gate is exempt inside a zero-LLM pass (the pass IS the
     parked mechanisms' time host): the cheap clocks run while parked;
  4. the verdict contract is untouched — a parked, healthy zero-LLM pass
     still exits QUIET (rc 0) with the park face named, and the think
     seat never runs hostless (no THINK artifact without a reader);
  5. the default run_due pass and the parked in-session tick keep their
     #740 behavior verbatim (execution timing moved, not jurisdiction);
  6. the production path: the real wrapper CLI on a real parked workspace
     — QUIET, zero staged bytes, and the cheap mechanisms' state rows
     show they RAN.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
for _p in (SCRIPTS, HOOKS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import kunglao_log  # noqa: E402
import mechanism_scheduler as ms  # noqa: E402
import heartbeat_tick as ht  # noqa: E402

from _factories import write_hook_state  # noqa: E402

NOOP_STATE = Path("runs") / ".heartbeat-noop.json"
MECH_STATE = Path("runs") / ".mechanisms-state.json"

# The shipped registry's tick channel — 13 entries (the two extra
# "channel: tick" grep hits in the yaml are section-banner comments, not
# entries). Together these three tuples ARE the S20 per-mechanism
# reconciliation for a parked, quiet zero-LLM pass:
RUN_IN_GATE_PASS = ("env_probe", "stale_feedback", "cadence_advisor",
                    "slot_monitor", "credit_settle", "verify_watch",
                    "premise_expiry", "rotation_induction")
# cheap, but gated events_seen — a quiet day has no wake-class rows, so
# the gate (not the ceiling) skips them; they run on the event pass that
# wakes the session anyway
GATE_SKIPPED_QUIET = ("workspace_monitor", "notes_rollup")
# medium/expensive — above the zero-LLM ceiling, WAKE-turn only
CEILING_SKIPPED = ("think_seat", "policy_retro", "oracle_probe_t1")

SCRIPT_BY_NAME = {
    "env_probe": "env_state_probe.py",
    "stale_feedback": "feedback.py",
    "cadence_advisor": "cadence_advisor.py",
    "slot_monitor": "slot_monitor.py",
    "credit_settle": "settle_round_credit.py",
    "verify_watch": "verify_status_watch.py",
    "premise_expiry": "premise_gate.py",
    "rotation_induction": "rotation_induction.py",
    "workspace_monitor": "kunglao-monitor.py",
    "notes_rollup": "rollup.py",
    "think_seat": "think_seat.py",
    "policy_retro": "backtrack_loop.py",
    "oracle_probe_t1": "verification_ladder.py",
}


# ---------------------------------------------------------------- helpers --

def _ws(tmp_path: Path) -> Path:
    """Minimal workspace the chain scripts accept (claims: [] = zero
    dispatchable work through the real ranking machinery)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _seed_noop(ws: Path) -> str:
    fp = ht.state_fingerprint(ws)
    (ws / NOOP_STATE).write_text(json.dumps({"hash": fp, "count": 1}),
                                 encoding="utf-8")
    return fp


def _parked_ws(tmp_path: Path) -> Path:
    ws = _ws(tmp_path)
    _seed_noop(ws)
    return ws


def _read_report(ws: Path) -> dict:
    return json.loads(
        (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))


def _ok(script, ws_arg, *extra):
    return {"rc": 0, "stdout": "", "stderr": ""}


def _spy_runner(sink: list):
    def runner(script, ws_arg, *extra):
        sink.append(script)
        return {"rc": 0, "stdout": "", "stderr": ""}
    return runner


def _active_worker(ws: Path, wid: str = "C001") -> None:
    (ws / "runs" / f"worker-status-{wid}.md").write_text(
        "[2026-10-10T00:00Z] step: x | status: in-progress\n", encoding="utf-8")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ==========================================================================
# the reconciliation itself (the registry is the single declaration source)
# ==========================================================================

class TestReconciliation:
    def test_shipped_registry_has_exactly_the_thirteen_tick_entries(self):
        entries, errors = ms.load_registry()
        assert not errors, errors
        tick = sorted(e["name"] for e in entries if e.get("channel") == "tick")
        assert tick == sorted(RUN_IN_GATE_PASS + GATE_SKIPPED_QUIET
                              + CEILING_SKIPPED), tick

    def test_every_gate_pass_runner_is_cheap(self):
        entries, _ = ms.load_registry()
        by = {e["name"]: e for e in entries}
        for name in RUN_IN_GATE_PASS:
            assert by[name]["cost_class"] == "cheap", name
        for name in CEILING_SKIPPED:
            assert by[name]["cost_class"] in ("medium", "expensive"), name


# ==========================================================================
# the run_due zero-LLM face
# ==========================================================================

class TestZeroLlmSchedulingPass:
    def test_parked_quiet_pass_runs_the_reconciled_eight(self, tmp_path):
        ws = _parked_ws(tmp_path)
        calls: list = []
        out = ms.run_due(ws, budget_s=30, runner=_spy_runner(calls),
                         zero_llm=True)
        assert sorted(out["ran"]) == sorted(RUN_IN_GATE_PASS), out["ran"]
        for name in GATE_SKIPPED_QUIET + CEILING_SKIPPED:
            assert name in out["skipped"], name
        for name in RUN_IN_GATE_PASS:
            assert SCRIPT_BY_NAME[name] in calls, name
        # the ceiling entries carry the S20 skip reason — a skip, not a drop
        for name in CEILING_SKIPPED:
            assert "zero-LLM" in out["results"][name]["stdout"], name
        assert out["dropped"] == []

    def test_ceiling_skip_preserves_the_persisted_row(self, tmp_path):
        """A ceiling skip must not erase last_run/last_rc: the zero-LLM pass
        fires every interval all quiet day and the cockpit health face reads
        the persisted rows — dropping history would make a failed expensive
        mechanism look clean between wake turns."""
        ws = _parked_ws(tmp_path)
        (ws / MECH_STATE).write_text(json.dumps({
            "schema": 1,
            "mechanisms": {"policy_retro": {
                "last_run": "2026-11-26T00:00:00Z",
                "last_rc": 3, "runs": 7, "drops": 1}}}), encoding="utf-8")
        out = ms.run_due(ws, budget_s=30, runner=_ok, zero_llm=True)
        assert "policy_retro" in out["skipped"]
        state = json.loads((ws / MECH_STATE).read_text(encoding="utf-8"))
        row = state["mechanisms"]["policy_retro"]
        assert row["last_rc"] == 3 and row["runs"] == 7, row

    def test_budget_cap_still_drops_in_a_zero_llm_pass(self, tmp_path):
        """The single-pass time cap survives the ceiling: candidates that do
        not fit are budget drops, never silent passes."""
        ws = _parked_ws(tmp_path)
        out = ms.run_due(ws, budget_s=0, runner=_ok, zero_llm=True)
        assert out["ran"] == []
        assert out["dropped"], "the time cap must survive the ceiling"
        assert all(d["reason"] == "budget" for d in out["dropped"])

    def test_default_pass_keeps_the_parked_skip_verbatim(self, tmp_path):
        """Without the marker the #740 posture is untouched: parked-gated
        mechanisms stay skipped on any host that walks the registry."""
        ws = _parked_ws(tmp_path)
        out = ms.run_due(ws, budget_s=30, runner=_ok)
        for name in ("env_probe", "premise_expiry", "rotation_induction",
                     "think_seat"):
            assert name in out["skipped"], name
            assert name not in out["ran"], name

    def test_expensive_keeps_its_wake_turn_host(self, tmp_path):
        """An expensive mechanism whose gate IS due (a stall event landed)
        runs in the default pass and is ceiling-skipped in the zero-LLM
        pass — the ceiling cuts before gate evaluation."""
        ws = _ws(tmp_path)
        kunglao_log.emit(ws, "test", "mission_stall", detail="one")
        default_out = ms.run_due(ws, budget_s=30, runner=_ok)
        assert "policy_retro" in default_out["ran"], default_out["ran"]
        kunglao_log.emit(ws, "test", "mission_stall", detail="two")
        gate_out = ms.run_due(ws, budget_s=30, runner=_ok, zero_llm=True)
        assert "policy_retro" in gate_out["skipped"]
        assert "zero-LLM" in gate_out["results"]["policy_retro"]["stdout"]


# ==========================================================================
# the tick wiring (in-process; the runner seam carries stub results)
# ==========================================================================

class TestTickWiring:
    def test_wrapper_marks_its_invocation_as_the_zero_llm_host(self, tmp_path):
        import heartbeat_wake_gate as wgw
        assert "--zero-llm" in wgw.GATE_ARGS
        argv = wgw.gate_argv(tmp_path)
        assert "--wake-gate" in argv and "--zero-llm" in argv

    def test_parked_zero_llm_tick_runs_cheap_and_exits_quiet(
            self, tmp_path, monkeypatch, capsys):
        ws = _parked_ws(tmp_path)
        dispatched: list = []
        monkeypatch.setattr(ht, "run", _spy_runner(dispatched))
        rc = ht.main([str(ws), "--origin", "cron", "--wake-gate",
                      "--zero-llm"])
        assert rc == 0, "a healthy parked zero-LLM pass is QUIET"
        assert "QUIET:" in capsys.readouterr().out
        report = _read_report(ws)
        assert report["mechanisms"]["parked"] is True
        assert sorted(report["mechanisms"]["ran"]) == sorted(RUN_IN_GATE_PASS)
        assert report["parked"]["reason"], "the park posture still names itself"
        assert report["action_taken"].startswith("PARK")
        think = report.get("think")
        assert think is None or think.get("skipped") is True, think
        assert not report["action_taken"].startswith("THINK")
        assert SCRIPT_BY_NAME["think_seat"] not in dispatched
        assert SCRIPT_BY_NAME["policy_retro"] not in dispatched
        assert SCRIPT_BY_NAME["oracle_probe_t1"] not in dispatched

    def test_in_session_gate_tick_keeps_the_parked_skip(
            self, tmp_path, monkeypatch):
        """The loop prompt's in-session tick (gate mode, no marker) is a
        WAKE-turn host: a parked pass keeps the #740 full machinery skip."""
        ws = _parked_ws(tmp_path)
        dispatched: list = []
        monkeypatch.setattr(ht, "run", _spy_runner(dispatched))
        ht.main([str(ws), "--origin", "cron", "--wake-gate"])
        report = _read_report(ws)
        assert report["mechanisms"]["ran"] == []
        assert report["mechanisms"].get("parked") is True
        for name in ("env_probe", "premise_expiry", "think_seat",
                     "policy_retro"):
            assert SCRIPT_BY_NAME[name] not in dispatched, name

    def test_unparked_in_turn_tick_still_dispatches_the_think_seat(
            self, tmp_path, monkeypatch):
        """The seat's reader is the model turn: an unparked in-turn pass
        still dispatches it (medium cost rides the WAKE turn)."""
        ws = _ws(tmp_path)
        _active_worker(ws)
        dispatched: list = []
        monkeypatch.setattr(ht, "run", _spy_runner(dispatched))
        ht.main([str(ws)])
        report = _read_report(ws)
        assert "think_seat" in report["mechanisms"]["ran"]
        assert SCRIPT_BY_NAME["think_seat"] in dispatched

    def test_quiet_unparked_zero_llm_pass_never_seats_the_think_seat(
            self, tmp_path, monkeypatch):
        """Even with the park lifted, a zero-LLM pass never seats the think
        seat: a THINK file no model turn reads is the waste S20 refuses."""
        ws = _ws(tmp_path)
        _active_worker(ws)
        monkeypatch.setattr(ht, "run", _ok)
        ht.main([str(ws), "--origin", "cron", "--wake-gate", "--zero-llm"])
        report = _read_report(ws)
        assert "think_seat" in report["mechanisms"]["skipped"]
        think = report.get("think")
        assert think is None or think.get("skipped") is True, think
        assert not report["action_taken"].startswith("THINK")

    def test_zero_llm_flag_requires_wake_gate(self, tmp_path):
        with pytest.raises(SystemExit) as ei:
            ht.main([str(tmp_path), "--zero-llm"])
        assert ei.value.code == 2


# ==========================================================================
# the production path (real wrapper CLI -> real gate -> real mechanisms)
# ==========================================================================

def _quiet_ws(tmp_path: Path) -> Path:
    """A minimal parked workspace the real gate accepts as QUIET (the same
    fixture shape tests/test_wake_gate_wiring_1086.py uses)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    write_hook_state(
        ws, active_hooks=["cost_gate"], ts=_iso(_now()), tier="none",
        phase="IDLE", user_override={},
        expires_at=_iso(_now() + timedelta(minutes=25)))
    now = _now()
    (ws / "runs" / ".heartbeat.json").write_text(
        json.dumps({"last_tick_ts": _iso(now), "loop_registered": True}),
        encoding="utf-8")
    (ws / "runs" / ".heartbeat.log").write_text("\n".join(
        json.dumps({"ts": _iso(now - timedelta(minutes=m)), "actor": "tick"})
        for m in (10, 5)) + "\n", encoding="utf-8")
    (ws / NOOP_STATE).write_text(json.dumps({
        "hash": ht.state_fingerprint(ws), "count": 1}), encoding="utf-8")
    return ws


def _run_wrapper(ws: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "heartbeat_wake_gate.py"), str(ws),
         *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": os.pathsep.join(
            [str(ROOT), str(SCRIPTS), str(HOOKS)])})


class TestProductionPath:
    def test_real_quiet_wrapper_pass_runs_cheap_mechanisms_zero_injection(
            self, tmp_path):
        ws = _quiet_ws(tmp_path)
        r = _run_wrapper(ws, "--wake-gate", "--dry-run")
        assert r.returncode == 0, r.stderr[-400:]
        staged = ws / "runs" / ".wake-gate-prompt.txt"
        assert not staged.exists(), "a quiet pass staged prompt bytes"
        report = _read_report(ws)
        assert report["mechanisms"]["parked"] is True
        ran = report["mechanisms"]["ran"]
        for name in ("env_probe", "premise_expiry", "rotation_induction"):
            assert name in ran, (name, ran)
        for name in CEILING_SKIPPED:
            assert name not in ran, (name, ran)
        think = report.get("think")
        assert think is None or think.get("skipped") is True, think
        assert not report["action_taken"].startswith("THINK")
        state = json.loads((ws / MECH_STATE).read_text(encoding="utf-8"))
        assert state["mechanisms"]["env_probe"]["last_run"], (
            "the cheap clock did not record a run")
