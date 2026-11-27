# -*- coding: utf-8 -*-
"""tests/test_wake_gate_wiring_1086.py — #1086 S18: the wake gate's consumer.

The pre-LLM gate (`heartbeat_tick.py --wake-gate`) was built, implemented and
tested, but nothing consumed it: the operator contract registered the LOOP
PROMPT as the cron body (SKILL.md → heartbeat_loop_prompt.py stdout →
CronCreate */5), so a model turn happened every five minutes whether or not
there was work, and the verdict only ever ran inside a turn whose tokens it
existed to save. The wrapper the gate declaration names ("a wake verdict
exits 3 and the wrapper injects the loop prompt") did not exist.

This module pins the wiring, not the gate (the gate's own pins live in
tests/test_economics_801.py):

  1. the emitted OS-scheduler registration runs the GATE wrapper and carries
     `--wake-gate` — never the loop-prompt emitter;
  2. a QUIET verdict injects NOTHING (zero prompt bytes staged, zero
     deliveries, wrapper rc 0);
  3. a WAKE verdict injects the loop prompt EXACTLY ONCE (the payload is the
     emitter's own body — never a re-embedded copy), wrapper rc 3;
  4. a wrapper/gate fault is LOUD and never reported as QUIET (rc 1 + stderr;
     fail-toward-wake so a broken gate cannot make the system sleep forever);
  5. rc 2 (the #634 idle circuit breaker) stays a MANDATORY stop — no
     injection, never treated as quiet;
  6. the contract surfaces teach the wrapper (SKILL.md 1.1/1.4, the loop
     prompt body's tick line, kunglao_resume's re-arm advice), and the QUIET
     verdict is legal inaction in the tick contract (the WAKE discipline
     itself is unchanged);
  7. the production path end to end: the real wrapper CLI against the real
     gate on a real workspace fixture — quiet injects nothing, a broken
     heartbeat wakes (the #1086 gotcha: that WAKE is correct, not a bug).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
SKILL_MD = ROOT / "skills" / "kunglao-agent" / "SKILL.md"
for _p in (SCRIPTS, HOOKS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from _factories import write_hook_state  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeCompleted:
    """The run_gate seam's return shape (subprocess.CompletedProcess face)."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_runner(rc: int, stdout: str, stderr: str = ""):
    def _run(cmd, *, timeout=None):
        return _FakeCompleted(rc, stdout, stderr)
    return _run


class _Recorder:
    """The delivery seam: records every call (the exactly-once pin)."""

    def __init__(self, *, result=None):
        self.calls: list[tuple] = []
        self._result = result or {"delivered": "kicked", "pid": 4242}

    def __call__(self, prompt: str, ws, *, claude_bin="claude"):
        self.calls.append((prompt, Path(ws)))
        return dict(self._result)


QUIET_GATE = _fake_runner(0, "QUIET: no LLM action needed — idle ≈ 0 tokens\n")
WAKE_GATE = _fake_runner(3, "WAKE: events:settlement — inject the loop prompt (exit 3)\n")
STOP_GATE = _fake_runner(2, "*** IDLE CIRCUIT BREAKER: 6 consecutive no-op ticks\n")


# ---------------------------------------------------------------------------
# 1. the registration is the gate, not the prompt
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_gate_argv_targets_the_tick_in_gate_mode(self, tmp_path):
        import heartbeat_wake_gate as wgw
        argv = wgw.gate_argv(tmp_path)
        joined = " ".join(argv)
        assert "heartbeat_tick.py" in joined
        assert "--origin" in argv and "cron" in argv
        assert "--wake-gate" in argv, "the gate mode flag must ride the argv"
        assert str(tmp_path) in argv

    def test_crontab_line_runs_the_wrapper_and_carries_the_gate_flag(self, tmp_path):
        import heartbeat_wake_gate as wgw
        line = wgw.build_crontab_line(tmp_path, interval_min=5)
        assert "heartbeat_wake_gate.py" in line, (
            "the OS cron must run the wrapper")
        assert "--wake-gate" in line, (
            "#1086 acceptance: the emitted registration contains --wake-gate")
        assert "*/5" in line
        assert str(tmp_path) in line

    def test_registration_is_not_the_loop_prompt(self, tmp_path):
        import heartbeat_wake_gate as wgw
        for line in (wgw.build_crontab_line(tmp_path),
                     " ".join(wgw.build_schtasks_command(ws=tmp_path))):
            assert "heartbeat_loop_prompt" not in line, (
                "registering the prompt emitter is the bypass #1086 closes")
            assert "/loop" not in line

    def test_interval_must_stay_under_the_activation_ttl(self, tmp_path):
        """The kicker's D6 rule applies to the gate metronome too: a cadence
        at or beyond the 30-min activation TTL silently closes gates between
        passes."""
        import pytest
        import heartbeat_wake_gate as wgw
        with pytest.raises(ValueError):
            wgw.build_crontab_line(tmp_path, interval_min=30)

    def test_print_registration_face_emits_both_platforms(self, tmp_path, capsys):
        import heartbeat_wake_gate as wgw
        rc = wgw.main([str(tmp_path), "--print-registration"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--wake-gate" in out
        assert "schtasks" in out and "crontab" in out.lower()

# ---------------------------------------------------------------------------
# 2-5. the verdict -> action map (seam-injected; no subprocess here)
# ---------------------------------------------------------------------------

class TestVerdictActions:
    def test_quiet_injects_nothing(self, tmp_path):
        import heartbeat_wake_gate as wgw
        deliver = _Recorder()
        out = wgw.wake_pass(tmp_path, runner=QUIET_GATE, deliver=deliver)
        assert out["outcome"] == "quiet"
        assert out["injected"] is False
        assert out["rc"] == 0
        assert deliver.calls == [], "a quiet verdict injected something"
        staged = tmp_path / "runs" / ".wake-gate-prompt.txt"
        assert not staged.exists(), "a quiet verdict staged a prompt"

    def test_wake_injects_the_loop_prompt_exactly_once(self, tmp_path):
        import random
        import heartbeat_wake_gate as wgw
        import heartbeat_loop_prompt as hlp
        deliver = _Recorder()
        # seed 0 draws close_loop under the flat priors — a fixed rng so
        # the exactly-once pin never flakes on a `none` draw (S21)
        out = wgw.wake_pass(tmp_path, runner=WAKE_GATE, deliver=deliver,
                            decision_rng=random.Random(0))
        assert out["outcome"] == "wake"
        assert out["injected"] is True
        assert out["rc"] == 3, "the wrapper propagates the gate's wake rc"
        assert len(deliver.calls) == 1, "injection must happen exactly once"
        prompt, ws_arg = deliver.calls[0]
        assert ws_arg == tmp_path
        assert prompt == hlp.build_prompt(str(tmp_path)), (
            "the injected payload must be the emitter's body, never a "
            "re-embedded copy (#598)")
        staged = tmp_path / "runs" / ".wake-gate-prompt.txt"
        assert staged.read_text(encoding="utf-8") == prompt

    def test_fault_is_loud_and_never_quiet(self, tmp_path, capsys):
        import heartbeat_wake_gate as wgw
        deliver = _Recorder()
        for gate in (_fake_runner(1, "Traceback (most recent call last)...\n"),
                     _fake_runner(9, "REFUSE: version mismatch\n"),
                     _fake_runner(0, "heartbeat_tick: ok | selfcheck_rc=0\n")):
            out = wgw.wake_pass(tmp_path, runner=gate, deliver=deliver)
            assert out["outcome"] == "fault", gate.stdout
            assert out["rc"] == 1, "a fault must never exit as the quiet rc"
            err = capsys.readouterr().err
            assert "WAKE-GATE" in err, "the fault must be loud on stderr"
        # fail-toward-wake: a broken gate still injects (never-waking is the
        # worse failure), so the recorder saw exactly one call per fault
        assert len(deliver.calls) == 3

    def test_fault_without_a_deliverable_prompt_still_refuses_quiet(
            self, tmp_path, capsys, monkeypatch):
        import heartbeat_wake_gate as wgw
        def _broken(ws, *, interval_min=5):
            raise RuntimeError("emitter unavailable")
        monkeypatch.setattr(wgw, "loop_prompt", _broken)
        out = wgw.wake_pass(
            tmp_path, runner=_fake_runner(-1, "", ""), deliver=_Recorder())
        assert out["outcome"] == "fault"
        assert out["rc"] == 1
        assert "WAKE-GATE" in capsys.readouterr().err

    def test_gate_spawn_failure_is_loud_never_quiet(self, tmp_path, capsys):
        import random
        import heartbeat_wake_gate as wgw
        def _boom(prompt, ws, *, claude_bin="claude"):
            raise OSError("claude: command not found")
        out = wgw.wake_pass(tmp_path, runner=WAKE_GATE, deliver=_boom,
                            decision_rng=random.Random(0))
        assert out["outcome"] == "fault"
        assert out["rc"] == 1
        assert "WAKE-GATE" in capsys.readouterr().err

    def test_breaker_stop_is_a_mandatory_stop(self, tmp_path, capsys):
        import heartbeat_wake_gate as wgw
        deliver = _Recorder()
        out = wgw.wake_pass(tmp_path, runner=STOP_GATE, deliver=deliver)
        assert out["outcome"] == "stop"
        assert out["rc"] == 2
        assert out["injected"] is False
        assert deliver.calls == [], "a breaker stop must not inject"
        assert "WAKE-GATE" in capsys.readouterr().err

    def test_alive_session_is_not_duplicate_spawned(self, tmp_path):
        """A live session owns the wake: the wrapper stages the prompt but
        never starts a SECOND orchestrator on the same workspace."""
        import random
        import heartbeat_wake_gate as wgw
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        now = _now()
        (ws / "runs" / ".heartbeat.json").write_text(json.dumps({
            "last_tick_ts": _iso(now - timedelta(minutes=1)),
            "activity_ts": _iso(now - timedelta(minutes=1))}), encoding="utf-8")
        deliver = _Recorder()
        out = wgw.wake_pass(ws, runner=WAKE_GATE, deliver=deliver,
                            decision_rng=random.Random(0))
        assert out["outcome"] == "wake"
        assert deliver.calls == [], "a live session was duplicate-spawned"
        assert (ws / "runs" / ".wake-gate-prompt.txt").exists(), (
            "the staged prompt IS the alive-session delivery")
        assert out["delivery"]["delivered"] == "staged"


# ---------------------------------------------------------------------------
# 6. the contract surfaces
# ---------------------------------------------------------------------------

class TestContract:
    def test_skill_registers_the_gate_wrapper(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "heartbeat_wake_gate.py" in text, (
            "SKILL.md must teach registering the wrapper")
        assert "--wake-gate" in text, (
            "the registration guidance must carry the gate flag")
        assert "stdout = /loop prompt → CronCreate" not in text, (
            "the old registration line (the bypass) must be gone")

    def test_skill_tick_binding_scopes_idle_fault_to_a_wake(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        tick_binding = text.split("### 1.4 Tick binding", 1)[1].split("## ", 2)[0]
        assert "no action in a tick = idle fault" in tick_binding, (
            "the WAKE-branch discipline must survive verbatim")
        assert "QUIET" in tick_binding, (
            "the QUIET carve-out must be stated where the rule lives")
        assert "WAKEN" in text, "the THINK EMPTY rule must be scoped to woken ticks"

    def test_loop_prompt_body_runs_the_tick_in_gate_mode(self, tmp_path):
        import heartbeat_loop_prompt as hlp
        body = hlp.build_prompt(str(tmp_path), "5m")
        assert "--origin cron" in body
        tick_lines = [ln for ln in body.splitlines()
                      if "heartbeat_tick.py" in ln and "python" in ln]
        assert tick_lines, "the body lost its tick command"
        assert all("--wake-gate" in ln for ln in tick_lines), (
            "the in-session tick must run in gate mode too")
        assert "idle fault" not in body, "test_heartbeat_off pin must hold"

    def test_resume_rearm_advice_registers_the_gate(self):
        import kunglao_resume as kr
        assert "--wake-gate" in kr.REARM_ADVICE
        assert "heartbeat_wake_gate.py" in kr.REARM_ADVICE
        assert "CronCreate" in kr.REARM_ADVICE, (
            "the durable watchdog cron stays registered (#685 D5)")

    def test_dispatch_reject_guidance_is_gate_first(self):
        """The hook-injected repair paths teach the GATE before the watchdog
        (end appeal #1: these envelopes re-taught the bypass on every
        dispatch rejection). The gate line must come BEFORE the CronCreate
        line, and the pinned words survive."""
        import worker_budget_sinks as sinks
        fix = sinks.REJECT_FIXES["heartbeat"]["additionalContext"]
        assert "heartbeat_wake_gate.py" in fix and "--wake-gate" in fix
        assert "CronCreate" in fix and "--heartbeat-on" in fix, (
            "the framework-rigidity pins must keep biting")
        assert fix.index("heartbeat_wake_gate.py") < fix.index("CronCreate"), (
            "the gate registration must lead, the watchdog follows")

    def test_heartbeat_alive_reject_message_is_gate_first(self, tmp_path):
        import worker_budget_sinks as sinks
        # an existing loop-state with no heartbeat anywhere -> the NOT
        # REGISTERED repair message (a nonexistent state path SKIPS the gate)
        state = tmp_path / "loop-state.json"
        state.write_text("{}", encoding="utf-8")
        ok, msg = sinks.check_heartbeat_alive(state)
        assert ok is False
        assert "heartbeat_wake_gate.py" in msg and "--wake-gate" in msg
        assert "CronCreate" in msg and "#754" in msg, (
            "the durable-watchdog wording must survive")
        assert msg.index("heartbeat_wake_gate.py") < msg.index("CronCreate")

    def test_references_and_eval_remedy_are_gate_first(self):
        root = ROOT
        guardrails = (root / "references" / "governance" / "guardrails.md"
                      ).read_text(encoding="utf-8")
        cold_start = (root / "references" / "contracts"
                      / "cold-start-contract.md").read_text(encoding="utf-8")
        for text in (guardrails, cold_start):
            assert "heartbeat_wake_gate.py" in text, (
                "the reference contract must teach the gate registration")
        src = (root / "scripts" / "eval_loop_runner.py").read_text(
            encoding="utf-8")
        assert "heartbeat_wake_gate.py" in src and "--print-registration" in src
        assert "CronCreate" in src, "the watchdog wording must survive"


# ---------------------------------------------------------------------------
# 7. the production path (real CLI -> real gate; --dry-run never spawns)
# ---------------------------------------------------------------------------

def _quiet_ws(tmp_path: Path) -> Path:
    """A minimal parked workspace the real gate accepts as QUIET (the same
    fixture shape tests/test_economics_801.py uses for its quiet-hour pin)."""
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
    import heartbeat_tick
    (ws / "runs" / ".heartbeat-noop.json").write_text(json.dumps({
        "hash": heartbeat_tick.state_fingerprint(ws), "count": 1}),
        encoding="utf-8")
    return ws


def _run_cli(ws: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "heartbeat_wake_gate.py"), str(ws), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": os.pathsep.join(
            [str(ROOT), str(SCRIPTS), str(HOOKS)])})


class TestProductionPath:
    def test_real_quiet_workspace_injects_nothing(self, tmp_path):
        ws = _quiet_ws(tmp_path)
        r = _run_cli(ws, "--wake-gate", "--dry-run")
        assert r.returncode == 0, r.stderr[-400:]
        staged = ws / "runs" / ".wake-gate-prompt.txt"
        assert not staged.exists(), (
            "the real quiet gate pass staged a prompt — the bypass is back")
        receipt = ws / "runs" / ".wake-gate-receipt.json"
        if receipt.exists():  # quiet writes no receipt by design
            assert json.loads(receipt.read_text(encoding="utf-8"))["injected"] is False

    def test_real_broken_heartbeat_wakes_and_stages_once(self, tmp_path):
        """The #1086 gotcha pinned as CORRECT: on an empty/broken workspace
        the gate judges WAKE (heartbeat_rc=1 -> watchdog step-failure) — the
        wrapper injects; it must never be 'fixed' into QUIET."""
        ws = _quiet_ws(tmp_path)
        stale = _iso(_now() - timedelta(hours=2))
        (ws / "runs" / ".heartbeat.json").write_text(
            json.dumps({"last_tick_ts": stale}), encoding="utf-8")
        r = _run_cli(ws, "--wake-gate", "--dry-run", "--decision-seed", "0")
        assert r.returncode == 3, (
            f"a wake must propagate rc 3: {r.stdout[-300:]} {r.stderr[-300:]}")
        staged = ws / "runs" / ".wake-gate-prompt.txt"
        assert staged.exists(), "the wake did not stage the loop prompt"
        import heartbeat_loop_prompt as hlp
        assert staged.read_text(encoding="utf-8") == hlp.build_prompt(str(ws))
