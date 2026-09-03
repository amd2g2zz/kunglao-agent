#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_trajectory_replay.py — #498 验收方法 D: v0.1.1 双轨迹重演 (e2e).

Issue #498 is the v0.1.2 architecture declaration; its acceptance section
requires the two v0.1.1 field trajectories to REPLAY on the converged system
and be intercepted. Plan R2 method D fixes them as this file (four scenarios,
selectors: -k trajectory1 / trajectory2 / heartbeat / capability_card).

The organs each have unit-level negative tests already (#495 transducer /
#497 decision grammar v2 / #496 decision teeth / #461 heartbeat bootstrap).
This file adds the RELAY: the event sequences are the field ones, and every
gate's OUTPUT becomes the next gate's INPUT — v0.1.1 died precisely in the
composition ("each gate individually compliant, chained = dead task").

e2e discipline (design D1): every organ runs through its REAL CLI / hook
process (subprocess.run) — no mocking of organ internals; assertions face
observable output (exit codes, stderr keywords, on-disk artifact shapes).
Fixtures are fully synthetic (register / analyses / .hook_state / task_spec);
no real sample, no VM. Texts are behaviour-EQUIVALENCE representatives of
the death-grammar and stall-semantics classes, not verbatim narrative
(plan risk row: 双轨迹重演测试过度拟合叙事细节).

  trajectory1  death-verdict chain: transient failures x2 (analysis recorded,
               three artifacts MISSING — the v0.1.1 evidence-evaporation
               shape) + death declaration -> ask gate rc=1 (Type E) AND
               failure_analysis scan rc=1 (BLOCKED); recording the three
               artifacts promotes the obstacle to a claim and the next step
               points at DISPATCH (open claim -> work, not a dead end).
  trajectory2  plan-stall: action history -> milestone summary + "下一步:"
               -> zero subsequent actions -> rc=1 (Type B equivalent); the
               summary's capability achievement (frida✓) landed as
               validated_capability -> tool-switch dispatch REJECTs.
  heartbeat    self-armed e2e: one hermetic init run leaves runs/.heartbeat.json
               fresh with ZERO manual hook_activation calls (#461 pinned the
               source level; this is the composition re-check); cron not
               registered -> --verify rc=1 + stderr guidance (HARD).
  capability_card  看牌 variant: disproof shown -> passes AND leaves the
               capability_switch trace (stderr marker + unified log event).

Windows note: child processes get PYTHONIOENCODING=utf-8 so the zh verdict
texts round-trip (conftest golden_master uses the same posture).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from _factories import seed_bins, write_hook_state

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
HOOKS = REPO_ROOT / "hooks"

# liveness line shared with heartbeat.py / worker_budget.check_heartbeat_alive
# (#461 reuse) — the replay asserts the init-bootstrapped heartbeat is FRESH
# by this line, not by a softer local constant.
HEARTBEAT_STALE_MINUTES = 35

# every CLI the test invokes (the "zero manual hook_activation" guard reads
# this — a runtime record, not a source-text grep)
_INVOKED: list[list[str]] = []


def _child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_cli(argv: list[str], *, timeout: int = 120, stdin: str | None = None
             ) -> subprocess.CompletedProcess:
    _INVOKED.append(argv)
    return subprocess.run(
        [sys.executable, *argv], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
        env=_child_env(), input=stdin, cwd=str(REPO_ROOT))


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _ask(ws: Path, text: str) -> subprocess.CompletedProcess:
    return _run_cli([str(SCRIPTS / "ask_for_direction_gate.py"), str(ws), text])


def _fag(ws: Path, *extra: str) -> subprocess.CompletedProcess:
    return _run_cli([str(SCRIPTS / "failure_analysis_gate.py"), str(ws), *extra])


# ===========================================================================
# trajectory 1 — death-verdict chain: intercept -> transduce -> not a dead end
# ===========================================================================

def _trajectory1_ws(root: Path) -> Path:
    """The v0.1.1 trajectory-1 shape: C-1 attempted twice (spawn-timeout
    class transient failures), a failure analysis that answers the three
    questions in prose but records NONE of the #495 artifacts."""
    ws = root / "ws"
    _write(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": "OPEN",
         "boundary_type": "positive_observation",
         "evidence_tier_attempted": 1, "promotion_attempts": 2,
         "depends_on": [], "statement":
         "app calls badger.a under real Context (frida spawn path)"}]})
    _write(ws / "task_spec.yaml", {"primary_questions": []})
    _write(ws / "analyses" / "failure-C-1.yaml", {
        "claim": "C-1", "covers_attempt": 2,
        "method_assumption": "spawn mode keeps the app alive long enough",
        "assumption_validity": "justified-adequate",
        "next_method": "method was adequate",
        "analyzed_at": "2026-08-19T00:00:00+00:00"})
    return ws


class TestTrajectory1DeathChain:
    def test_trajectory1_death_verdict_intercepted_by_both_gates(
            self, tmp_path: Path) -> None:
        """方法 D 行 1 前半: the death declaration is rejected (rc=1, ladder
        guidance) AND the failed claim is BLOCKED (scan rc=1, artifacts
        named) — no quiet terminal, no re-dispatch either."""
        ws = _trajectory1_ws(tmp_path)

        r = _ask(ws, "frida spawn 第二次超时。这条路走不通，换方向吧。")
        assert r.returncode == 1, (
            f"Type E death verdict must be intercepted; rc={r.returncode}, "
            f"stdout={r.stdout!r}, stderr={r.stderr!r}")
        assert ("ladder" in r.stdout.lower() or "梯" in r.stdout), (
            f"guidance must point at the ladder; stdout={r.stdout!r}")

        r2 = _fag(ws)
        assert r2.returncode == 1, (
            f"two transient failures without artifacts must BLOCK the scan; "
            f"rc={r2.returncode}, stdout={r2.stdout!r}")
        assert "BLOCKED" in r2.stdout, f"stdout={r2.stdout!r}"
        assert "validated_capability" in r2.stdout, r2.stdout
        assert "identified_obstacle" in r2.stdout, r2.stdout

    def test_trajectory1_artifacts_promote_obstacle_and_point_to_dispatch(
            self, tmp_path: Path) -> None:
        """方法 D 行 1 后半: recording the three artifacts (capability ✓ /
        obstacle / provenance) promotes the obstacle to a NEW claim (real
        claim_deps edge) and the next step is DISPATCH via decide() +
        resume — an open claim means work pending, never a dead end."""
        ws = _trajectory1_ws(tmp_path)
        empty_lib = tmp_path / "empty-lessons"   # ladder rung runs, no hits
        empty_lib.mkdir()

        r = _fag(ws, "C-1", "--record",
                 "--assumption", "spawn keeps the app alive to trigger badger.a",
                 "--validity", "not-justified",
                 "--next-method", "listen mode instead of spawn",
                 "--validated-capability", "frida 桥 works (NewByteArray called)",
                 "--identified-obstacle", "spawn 超时 kills only the spawn path",
                 "--source", "lesson-hit",
                 "--library", str(empty_lib))
        assert r.returncode == 0, f"record rejected: {r.stdout!r} {r.stderr!r}"
        assert "RECORDED" in r.stdout, r.stdout

        # the obstacle became a claim (DAG grew a node, real edge)
        reg = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8"))
        obstacle = [c for c in reg["claims"]
                    if c.get("origin") == "failure-obstacle"]
        assert obstacle, f"obstacle was not promoted: {reg['claims']}"
        assert obstacle[0]["obstacle_for"] == "C-1"
        assert obstacle[0]["depends_on"] == ["C-1"]
        deps = yaml.safe_load(
            (ws / "claim_deps.yaml").read_text(encoding="utf-8"))
        assert deps["depends_on"].get(obstacle[0]["id"]) == ["C-1"], deps

        # the recorded analysis carries the untested branch as next_method
        entry = yaml.safe_load(
            (ws / "analyses" / "failure-C-1.yaml").read_text(encoding="utf-8"))
        assert "listen" in entry["next_method"], entry

        # next step = DISPATCH (open claims + free slots), not a dead end
        rc = _run_cli([str(SCRIPTS / "convergence_check.py"), str(ws),
                       "--json"])
        assert rc.returncode == 1, rc.stdout  # exit 1 == DISPATCH verdict
        decision = json.loads(rc.stdout)
        assert decision["decision"] == "DISPATCH", decision
        assert decision["open_count"] >= 2, (
            f"parent + obstacle must both be open work; got {decision}")

        rr = _run_cli([str(SCRIPTS / "kunglao_resume.py"), str(ws), "--json"],
                      timeout=180)
        brief = json.loads(rr.stdout)
        assert "dispatch the priority_ratio top claim" in brief["next_step"], (
            f"resume must point at dispatch; got {brief['next_step']!r}")


# ===========================================================================
# trajectory 2 — plan-stall + capability achievement constrains tool switch
# ===========================================================================

class TestTrajectory2PlanStall:
    def test_trajectory2_milestone_next_step_zero_action_rejected(
            self, tmp_path: Path) -> None:
        """方法 D 行 2: action history -> milestone summary + "下一步:" ->
        ZERO subsequent tool actions -> rc=1 (Type B equivalent), execution
        demanded — the F1 shape: a warm action history must not grandfather
        a fresh declaration through (actions BEFORE the declaration did not
        execute the DECLARED step)."""
        ws = tmp_path / "ws"
        ws.mkdir()

        r_act = _ask(ws, "Dispatching W-1 via priority_ratio.py now")
        assert r_act.returncode == 0, (
            f"the action-history round must pass; stdout={r_act.stdout!r}")

        r = _ask(ws, "DPoP milestone 现状总结: 3 产物齐。\n"
                     "下一步: verify C-2 with listen mode")
        assert r.returncode == 1, (
            f"next-step declaration with no subsequent action must be "
            f"rejected; rc={r.returncode}, stdout={r.stdout!r}")
        assert "Type B" in r.stdout, (
            f"guidance must frame it as the Type B equivalent; "
            f"stdout={r.stdout!r}")
        assert ("execute" in r.stdout.lower() or "执行" in r.stdout), (
            f"guidance must demand execution, not waiting; "
            f"stdout={r.stdout!r}")

    def test_trajectory2_capability_achievement_constrains_tool_switch(
            self, tmp_path: Path) -> None:
        """方法 D 行 2 后半: the summary's capability achievement ("frida✓")
        landed as a validated_capability fact — the subsequent tool-switch
        dispatch (xposed) REJECTs until the frida failure is shown."""
        root = tmp_path / "cap"
        ws = root / "malware-analysis-workspace"
        _write(ws / "claim-register.yaml", {"claims": [
            {"id": "C-1", "status": "OPEN", "promotion_attempts": 1,
             "statement": "bypass the anti-debug check via frida"}]})
        _write(ws / "claim_deps.yaml",
               {"depends_on": {}, "competitor_groups": {}})
        _write(ws / "task_spec.yaml", {"primary_questions": []})
        _write(ws / "analyses" / "failure-C-1.yaml", {
            "claim": "C-1", "covers_attempt": 1,
            "method_assumption": "frida spawn would keep the process alive",
            "assumption_validity": "not-justified",
            "next_method": "listen mode instead of spawn",
            "next_method_source": "reference-hit",
            # the milestone summary's capability achievement, transduced
            "validated_capability":
                "frida injection reaches the anti-debug check and bypasses it",
            "identified_obstacle": "spawn timeout kills the spawn path only"})
        write_hook_state(ws, active_hooks=["dispatch_gate"])

        payload = json.dumps({"cwd": str(root), "workspace": str(ws),
                              "tool_input": {"prompt":
                              "[T2 tools=rev-xposed] claim C-1 "
                              "hook the check via xposed"}})
        _INVOKED.append([str(HOOKS / "dispatch_gate.py")])
        r = subprocess.run([sys.executable, str(HOOKS / "dispatch_gate.py")],
                           input=payload, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60,
                           cwd=str(REPO_ROOT))
        assert r.returncode == 2, (
            f"validated frida + dispatch xposed must REJECT; rc="
            f"{r.returncode}, stderr={r.stderr!r}")
        assert "REJECT capability" in r.stderr, f"stderr={r.stderr!r}"
        assert "frida" in r.stderr, (
            f"the rejection must name the validated family; "
            f"stderr={r.stderr!r}")
        assert "capability-disproof" in r.stdout, (
            f"fix guidance must teach the disproof marker; "
            f"stdout={r.stdout!r}")


# ===========================================================================
# heartbeat — self-armed after ONE init run; cron HARD verify (#461 e2e)
# ===========================================================================

def _mk_init_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    seed_bins(ws, payload=b"MZ\x90\x00" + b"\x00" * 64)
    (ws / "runs").mkdir()
    return ws


def _run_init(ws: Path) -> subprocess.CompletedProcess:
    """Hermetic CLI run (mirrors test_heartbeat_bootstrap._run_init): pinned
    fake claude.json, empty PATH dir, profile root under tmp — the init full
    chain without touching the real toolchain (#461 seam)."""
    flag = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
    env = {k: v for k, v in os.environ.items()
           if k not in (flag, "GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    (ws.parent / "empty-bin").mkdir(exist_ok=True)
    env["PATH"] = str(ws.parent / "empty-bin")
    env["PYTHONIOENCODING"] = "utf-8"
    env[flag] = "0"
    env["KUNGLAO_CLAUDE_JSON"] = str(ws.parent / "fake-claude.json")
    fake = ws.parent / "fake-claude.json"
    if not fake.exists():
        fake.write_text("{}", encoding="utf-8")
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
            "--type", "windows", "--skip-toolchain",
            "--profile-root", str(ws.parent / "profile-root")]
    if not any(a.startswith("--host-exec-protection") for a in argv) \
            and "--resolve" not in argv:
        # #919: non-interactive tests answer the host-exec ask explicitly.
        argv += ["--host-exec-protection", "enabled"]
    _INVOKED.append(argv)
    return subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180,
                          env=env, cwd=str(REPO_ROOT))


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestHeartbeatSelfArmed:
    def test_heartbeat_self_armed_e2e_and_cron_hard_verify(
            self, tmp_path: Path) -> None:
        """方法 D 行 3: a clean workspace + ONE init run -> heartbeat exists
        and is fresh, with ZERO manual hook_activation calls in the whole
        scenario (runtime record check on _INVOKED — the v0.1.1 6-step
        manual chain is init-owned now). init never fakes cron registration:
        loop_registered stays false -> --verify HARD-fails (rc=1 + stderr
        guidance), never silent."""
        calls_before = len(_INVOKED)
        ws = _mk_init_ws(tmp_path)
        r = _run_init(ws)
        assert r.returncode == 0, f"init failed: {r.stdout!r} {r.stderr!r}"

        hb = ws / "runs" / ".heartbeat.json"
        assert hb.exists(), (
            f"#461 e2e: init exited 0 without the heartbeat: {r.stdout!r}")
        data = json.loads(hb.read_text(encoding="utf-8"))
        ts = data.get("last_tick_ts") or data.get("started_ts")
        assert ts, f"heartbeat carries no freshness timestamp: {data}"
        age = datetime.now(timezone.utc) - _parse_ts(ts)
        assert age < timedelta(minutes=HEARTBEAT_STALE_MINUTES), (
            f"heartbeat registered STALE ({age}): {data}")
        assert "loop_registered" in data, (
            f"the cron marker must exist (False until CronCreate fires — "
            f"init alone never fakes it): {data}")

        # zero manual hook_activation in this scenario (runtime record)
        assert not any("hook_activation" in " ".join(map(str, a))
                       for a in _INVOKED[calls_before:]), (
            "the heartbeat bootstrap must be init-owned — a manual "
            "hook_activation call appeared in the scenario")

        rv = _run_cli([str(SCRIPTS / "heartbeat_loop_prompt.py"),
                       str(ws), "--verify"])
        assert rv.returncode == 1, (
            f"cron not registered must HARD-fail --verify; rc="
            f"{rv.returncode}, stdout={rv.stdout!r}")
        assert "CronCreate" in rv.stderr or "loop_registered" in rv.stderr, (
            f"stderr must carry the registration guidance: {rv.stderr!r}")


# ===========================================================================
# capability card — 看牌 variant: disproof shown -> pass + trace
# ===========================================================================

def _capability_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "card"
    ws = root / "malware-analysis-workspace"
    _write(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": "OPEN", "promotion_attempts": 1,
         "statement": "bypass the anti-debug check via frida"}]})
    _write(ws / "claim_deps.yaml",
           {"depends_on": {}, "competitor_groups": {}})
    _write(ws / "task_spec.yaml", {"primary_questions": []})
    _write(ws / "analyses" / "failure-C-1.yaml", {
        "claim": "C-1", "covers_attempt": 1,
        "method_assumption": "frida spawn would keep the process alive",
        "assumption_validity": "not-justified",
        "next_method": "listen mode instead of spawn",
        "next_method_source": "reference-hit",
        "validated_capability":
            "frida injection reaches the anti-debug check and bypasses it",
        "identified_obstacle": "spawn timeout kills the spawn path only"})
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    return root, ws


def _run_dispatch_gate(root: Path, ws: Path, prompt: str
                       ) -> subprocess.CompletedProcess:
    payload = json.dumps({"cwd": str(root), "workspace": str(ws),
                          "tool_input": {"prompt": prompt}})
    argv = [sys.executable, str(HOOKS / "dispatch_gate.py")]
    _INVOKED.append(argv)
    return subprocess.run(argv, input=payload, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=60, cwd=str(REPO_ROOT))


def _event_rows(ws: Path) -> list[dict]:
    logs = ws / "runs" / "logs"
    out: list[dict] = []
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


class TestCapabilityCardDisproofVariant:
    def test_capability_card_disproof_shown_passes_and_records(
            self, tmp_path: Path) -> None:
        """方法 D 行 4 变体: showing the disproof (the frida failure on the
        spawn path) lets the switch pass AND leaves the trace — stderr
        `CAPABILITY (disproof recorded)` + a capability_switch event in the
        unified log. 看牌 is a gate on silent pivots, not a lock."""
        root, ws = _capability_root(tmp_path)
        prompt = ("[T2 tools=rev-xposed] claim C-1 hook the check via xposed\n"
                  "capability-disproof: frida (spawn path timed out twice — "
                  "see analyses/failure-C-1.yaml)")
        r = _run_dispatch_gate(root, ws, prompt)
        assert r.returncode == 0, (
            f"disproof shown must pass; stderr={r.stderr!r}")
        assert "CAPABILITY (disproof recorded)" in r.stderr, (
            f"the pass must be observable on stderr; stderr={r.stderr!r}")
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "capability_switch"]
        assert any(e.get("claim") == "C-1" for e in rows), (
            f"the unified log must carry the switch trace; rows={rows}")

    def test_capability_card_same_family_dispatch_stays_silent(
            self, tmp_path: Path) -> None:
        """Guard (narrow-tooth): dispatching the VALIDATED family itself is
        capability in hand, not a switch — no REJECT, no trace."""
        root, ws = _capability_root(tmp_path)
        r = _run_dispatch_gate(
            root, ws, "[T1 tools=rev-frida] claim C-1 retry via listen mode")
        assert r.returncode == 0, (
            f"staying on the validated family must pass; stderr={r.stderr!r}")
        assert "REJECT capability" not in r.stderr
        assert not [e for e in _event_rows(ws)
                    if e.get("action") == "capability_switch"], (
            "no switch happened — no switch trace expected")
