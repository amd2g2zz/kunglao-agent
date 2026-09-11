# -*- coding: utf-8 -*-
"""Tests for scripts/env_check.py — environment-init mechanical gate (#233).

Three scenarios (mirroring the incident-driven acceptance criteria):
  1. AGENT_TEAMS flag set (process scope) -> check ① FAIL, overall FAIL, exit 1
     (the 2026-08-12 polluted-session shape)
  2. VM unreachable (socket refused/timed out) -> vm check FAIL, exit 1
     (dynamic analysis blocked; static may proceed — recoverable FAIL)
  3. all five checks PASS -> exit 0 + runs/.env-check.json snapshot says PASS

The check functions take explicit paths / module state so tests can monkeypatch
deterministically: flag via os.environ, VM via socket.create_connection,
Ghidra via GHIDRA_DEFAULT, hooks via BOTH project-level targets
(<ws>/.claude/settings.json — the wire_up_settings --wire-up target, #258/#269;
<ws-parent>/.claude/settings.json — the external_kicker D2 read/write target,
#410. The user-global file is NOT a deployment target), venv probe via the
uv dispatch (`uv run --project <skill_root>`, issue 207) with shutil.which /
subprocess.run pinned — never the real machine's uv.

#410 (2026-08-17): the hooks check is TRI-STATE — PASS (all registry hooks in
either target), WARN (no target wired — per-workspace optional, static analysis
proceeds), FAIL (partial deployment — some registry hooks dropped, the
#258/#372 silent-drop class).
"""
import json
import subprocess
from pathlib import Path

import pytest

import platform_paths  # pytest.ini pythonpath = . hooks scripts tools
import wire_up_settings  # pytest.ini pythonpath = . hooks scripts tools

from env_check import (  # pytest.ini pythonpath = . hooks scripts tools
    FLAG_NAME,
    run,
)


def _kunglao_ws(tmp_path: Path) -> Path:
    """Minimal workspace: runs/ + FULLY initialized state (#304: [initialized]
    marker in claim-register.yaml + project_type in analysis_state.txt) so the
    snapshot write succeeds and init_complete passes. #536: carries the
    template version stamp (a fully-initialized workspace has one).
    #757: pins a vmr channel record so checklist shaping never hits the
    runtime derivation probe path (tests control sockets explicitly)."""
    import template_version
    stamp = template_version.stamp_line(template_version.read_skill_version())
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / ".init-report.json").write_text(
        json.dumps({"channel": {"selected": "vmr"}}), encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(stamp + "\n# _INDEX\n", encoding="utf-8")
    (ws / "CLAUDE.md").write_text(stamp + "\n# workspace\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        stamp + "\n"
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=windows\n", encoding="utf-8")
    return ws


def _write_settings(target_root: Path) -> Path:
    """Deploy a settings.json carrying all wire-up hooks under target_root —
    makes check ④ PASS. target_root=ws -> PROJECT level (the #258/#269
    deployment target); target_root=isolated_home -> user-global (used by the
    negative regression test); target_root=parent (ws.parent) -> the
    workspace-parent target the external_kicker reads/writes (#410). #372:
    derives from the registry (all files, recall_inject under Pre/Agent,
    completion_gate under Stop). #532: write_guard rides the
    Edit|Write|MultiEdit matcher — a Pre/Agent-only fixture can never satisfy
    the full-registry scan."""
    settings = target_root / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    pre_agent = ["worker_budget.py", "dispatch_gate.py", "env_check_gate.py",
                 "recall_inject.py"]
    pre = [{"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python hooks/{h}"}]}
        for h in pre_agent]
    post = [{"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python hooks/{h}"}]}
        for h in ("worker_budget.py", "worker_pulse.py", "state_anchor.py")]
    post.append({"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python hooks/violation_capture.py"},
        {"type": "command", "command": "python hooks/bash_fact_guard.py"}]})
    pre.append({"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python hooks/heartbeat_touch.py"},
        {"type": "command", "command": "python hooks/orchestrator_tool_guard.py"}]})
    pre.append({"matcher": "Edit|Write|MultiEdit", "hooks": [
        {"type": "command", "command": "python hooks/write_guard.py"}]})
    stop = [{"hooks": [
        {"type": "command", "command": "python hooks/completion_gate.py"}]}]
    settings.write_text(json.dumps({"hooks": {"PreToolUse": pre,
                                              "PostToolUse": post,
                                              "Stop": stop}}),
                        encoding="utf-8")
    # #675: the per-matcher grouping above mirrors register_hooks — the
    # grouping lives only in its imperative _ensure sequence, so this
    # guard (not derivation) is the loud-fail: registry growth without a
    # fixture update fails HERE at construction with the symmetric
    # difference, never as a downstream env-check mystery (#608 class).
    covered = {
        h["command"][len("python hooks/"):]
        for group in (pre, post, stop)
        for entry in group
        for h in entry["hooks"]
    }
    registry = set(wire_up_settings.WIRE_UP_HOOK_FILES)
    if covered != registry:
        raise AssertionError(
            "_write_settings drifted from wire_up_settings.WIRE_UP_HOOK_FILES"
            f" (symmetric difference: {sorted(covered ^ registry)}) —"
            " update the per-matcher groups to cover the registry (#675)")
    return settings


def _write_partial_settings(target_root: Path) -> Path:
    """Deploy a settings.json carrying SOME registry hooks (all except
    completion_gate.py under Stop) — the #372 blind-spot shape. A partial
    deployment must FAIL the #410 tri-state check (a dropped hook is a
    silent-drop class defect, not 'unwired')."""
    settings = target_root / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    pre_agent = ["worker_budget.py", "dispatch_gate.py", "env_check_gate.py",
                 "recall_inject.py"]
    pre = [{"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python hooks/{h}"}]}
        for h in pre_agent]
    pre.append({"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python hooks/heartbeat_touch.py"}]})
    post = [{"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python hooks/{h}"}]}
        for h in ("worker_budget.py", "worker_pulse.py", "state_anchor.py")]
    settings.write_text(json.dumps({"hooks": {"PreToolUse": pre,
                                              "PostToolUse": post}}),
                        encoding="utf-8")
    return settings


def _stub_non_hook_checks(monkeypatch):
    """Isolate the hooks check: every non-hook check is forced to PASS so the
    #410 tri-state tests observe ONLY the hooks decision (VM/Ghidra/venv would
    otherwise FAIL on a bare tmp workspace and mask the hooks status)."""
    import env_check
    monkeypatch.setattr(env_check, "check_vm", lambda: ("PASS", "stubbed VM"))
    monkeypatch.setattr(env_check, "check_ghidra", lambda: ("PASS", "stubbed Ghidra"))
    monkeypatch.setattr(env_check, "check_venv_sample",
                        lambda ws, sha: ("PASS", "stubbed venv"))
    return env_check


@pytest.fixture(autouse=True)
def _isolated_claude_json(tmp_path, monkeypatch):
    """#757: env_check now reads MCP registration surfaces — point the user
    ~/.claude.json at an isolated file carrying a ghidra registration so the
    desktop mcp_registered row lands on its deterministic WARN-unverified
    branch and real-machine configs can never leak into these verdicts."""
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({"mcpServers": {"ghidra": {"command": "b"}}}),
                 encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(p))


def test_flag_set_fails_exit_1(monkeypatch, tmp_path):
    """Scenario 1: the 2026-08-12 polluted-session shape — flag set -> FAIL + exit 1."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.setenv(FLAG_NAME, "1")
    rc = run(ws)
    assert rc == 1
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["overall"] == "FAIL"
    assert snap["checks"]["agent_teams_flag"]["status"] == "FAIL"
    assert FLAG_NAME in snap["checks"]["agent_teams_flag"]["detail"]


def test_vm_unreachable_fails(monkeypatch, tmp_path):
    """Scenario 2: VM sockets refused/timed out -> the vm_reachability ROW
    FAILs. Per the #757 T3 grading that row is DEGRADED (static analysis may
    proceed), so the overall stays PASS / exit 0 — the FAIL lives in the row.
    Blocking rows are pinned (the issue 207 uv probe included) so the
    assertion reads the VM decision, never this machine's environment."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)

    def _boom(*args, **kwargs):
        raise OSError("mock: connection timed out")

    import env_check
    # #228: no default VM host — set one so this test exercises the socket path
    monkeypatch.setattr(env_check, "VM_HOST", "127.0.0.1")
    monkeypatch.setattr(env_check.socket, "create_connection", _boom)
    monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
    _uv_ok(monkeypatch, env_check, tmp_path / "skill-root")

    rc = run(ws)
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    vm = snap["checks"]["vm_reachability"]
    assert vm["status"] == "FAIL"
    assert vm["blocking"] is False and vm["detail"].startswith("T3-restricted:")
    assert "VM 127.0.0.1 unreachable" in vm["detail"]
    assert rc == 0, "a degraded vm FAIL must not exit nonzero (#757)"


def test_all_pass_exit_0(monkeypatch, tmp_path):
    """Scenario 3: flag unset + VM up + Ghidra present + hooks deployed at the
    PROJECT level + venv deps importable -> overall PASS, exit 0, snapshot
    written."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)

    import env_check
    # VM: pretend both ports accept connections (socket() is a context manager;
    # __enter__ does not connect — pure local, no network). #228: no default
    # VM host — set one so the check reaches the socket probe.
    monkeypatch.setattr(env_check, "VM_HOST", "127.0.0.1")
    monkeypatch.setattr(env_check.socket, "create_connection",
                        lambda *a, **k: env_check.socket.socket())
    # Ghidra: pretend analyzeHeadless exists at the module-resolved path
    fake_ghidra = tmp_path / platform_paths.analyze_headless_name()
    fake_ghidra.write_text("", encoding="utf-8")
    monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", fake_ghidra)
    # hooks: PROJECT-level <ws>/.claude/settings.json (#258/#269)
    _write_settings(ws)
    # venv: the probe dispatches through uv (issue 207 —
    # `uv run --project <skill_root> python -c "import yaml"`); a fake uv on
    # PATH + a rc=0 run is the whole fixture. No venv binary path is read.
    monkeypatch.setattr(env_check, "SKILL_DIR", tmp_path / "skill-root")
    monkeypatch.setattr(env_check.shutil, "which",
                        lambda name: "/fake/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        env_check.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""),
    )

    rc = run(ws)
    assert rc == 0
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["overall"] == "PASS"
    # #757: the mcp_registered row is intentionally WARN-unverified here
    # (fixture registers ghidra; a registry read can never claim capability).
    assert snap["checks"]["mcp_registered"]["status"] == "WARN"
    others = {k: v for k, v in snap["checks"].items() if k != "mcp_registered"}
    assert all(c["status"] == "PASS" for c in others.values())


def test_snapshot_written_on_fail(monkeypatch, tmp_path):
    """The snapshot must exist even when checks FAIL (gates read it)."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.setenv(FLAG_NAME, "1")
    assert run(ws) == 1
    snap_path = ws / "runs" / ".env-check.json"
    assert snap_path.exists()
    assert "ts" in json.loads(snap_path.read_text(encoding="utf-8"))


def test_user_level_settings_alone_does_not_satisfy_hooks(monkeypatch, tmp_path, isolated_home):
    """#269 regression: the hooks check must read the PROJECT-level targets
    (<ws>/.claude/settings.json — #258 deployment target — AND the
    workspace-parent <ws-parent>/.claude/settings.json, #410) — NOT the
    user-global ~/.claude/settings.json. A user-global-only deployment (the
    pre-#258 shape, 0 hooks in any project target) must be reported WARN, not
    misreported as deployed."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    _write_settings(isolated_home)  # user-global only — must NOT satisfy check ④
    assert not (ws / ".claude" / "settings.json").exists(), \
        "test setup: project-level settings must be absent"
    assert not (ws.parent / ".claude" / "settings.json").exists(), \
        "test setup: workspace-parent settings must be absent"

    _stub_non_hook_checks(monkeypatch)

    assert run(ws) == 0
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["hooks_deployed"]["status"] == "WARN", \
        "user-global-only deployment must NOT be reported PASS (deployed) — #269"
    assert snap["checks"]["hooks_deployed"]["status"] != "PASS"


# ---------- #410: workspace-parent settings.json is a valid deployment target ----------

def test_hooks_pass_from_workspace_parent_settings(monkeypatch, tmp_path):
    """#410: hooks deployed ONLY in the workspace-parent <ws-parent>/.claude/
    settings.json (the external_kicker D2 read/write target) must PASS — the
    deployment target and the check location must agree."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    _write_settings(ws.parent)  # workspace-parent target (#410)
    assert not (ws / ".claude" / "settings.json").exists(), \
        "test setup: ws-level settings must be absent"

    _stub_non_hook_checks(monkeypatch)

    rc = run(ws)
    assert rc == 0
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    hooks = snap["checks"]["hooks_deployed"]
    assert hooks["status"] == "PASS", (
        f"parent-target deployment must be reported PASS (#410): {hooks['detail']}")


def test_hooks_pass_from_workspace_level_settings(monkeypatch, tmp_path):
    """#410: hooks deployed ONLY at <ws>/.claude/settings.json (the #258
    --wire-up target) must still PASS — the original target remains valid."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    _write_settings(ws)

    _stub_non_hook_checks(monkeypatch)

    rc = run(ws)
    assert rc == 0
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["hooks_deployed"]["status"] == "PASS"


def test_hooks_fail_on_partial_deployment(monkeypatch, tmp_path):
    """#410: a PARTIAL deployment (some registry hooks, completion_gate.py
    dropped — the #372 blind-spot shape) must FAIL even though a target file
    exists. Missing-from-a-deployed-set is a silent-drop defect, not 'unwired':
    the tri-state WARN covers only NO-target-wired, not dropped hooks."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    _write_partial_settings(ws)

    _stub_non_hook_checks(monkeypatch)

    rc = run(ws)
    assert rc == 1, "partial deployment must fail the hooks check (#410)"
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    hooks = snap["checks"]["hooks_deployed"]
    assert hooks["status"] == "FAIL"
    assert "completion_gate.py" in hooks["detail"]
    assert "settings.json" in hooks["detail"]


def test_hooks_warn_when_no_settings_anywhere(monkeypatch, tmp_path):
    """#410: no hooks target at all (neither <ws>/.claude/settings.json nor
    <ws-parent>/.claude/settings.json) -> hooks_deployed WARN, NOT FAIL. Hooks
    are per-workspace optional — an unwired workspace must not block static
    analysis, and the guidance names --wire-up. overall stays PASS when every
    other check passes (exit 0)."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)

    _stub_non_hook_checks(monkeypatch)

    rc = run(ws)
    assert rc == 0, "unwired hooks must not block env_check (#410)"
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    hooks = snap["checks"]["hooks_deployed"]
    assert hooks["status"] == "WARN", f"unwired must be WARN, got {hooks['status']}"
    assert "--wire-up" in hooks["detail"]
    assert snap["overall"] == "PASS", (
        "WARN must not fail overall — hooks are optional (#410): "
        f"{snap['checks']}")


# ---------- #276: default-disabled flag semantics (truthy = FAIL, 0/false/off = PASS) ----------

def test_flag_zero_is_pass(tmp_path, monkeypatch):
    """#276: flag=0 -> agent_teams_flag PASS, detail shows 'disabled (0)'."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.setenv(FLAG_NAME, "0")

    import env_check
    monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
    monkeypatch.setattr(env_check, "VM_HOST", "")

    rc = run(ws)
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["agent_teams_flag"]["status"] == "PASS", snap
    assert "disabled (0)" in snap["checks"]["agent_teams_flag"]["detail"]
    assert rc in (0, 1), "flag check itself must not FAIL"


def test_flag_false_and_off_are_pass(tmp_path, monkeypatch):
    """#276: 'false'/'off' (non-truthy) -> PASS."""
    for i, value in enumerate(("false", "off")):
        ws = tmp_path / f"ws-nontruthy-{i}"
        (ws / "runs").mkdir(parents=True)
        monkeypatch.setenv(FLAG_NAME, value)
        import env_check
        monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
        monkeypatch.setattr(env_check, "VM_HOST", "")
        run(ws)
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        assert snap["checks"]["agent_teams_flag"]["status"] == "PASS", \
            f"{value}: {snap['checks']['agent_teams_flag']}"


def test_flag_true_fails(tmp_path, monkeypatch):
    """#276: 'true' (truthy) -> agent_teams_flag FAIL, detail names the value."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.setenv(FLAG_NAME, "true")
    rc = run(ws)
    assert rc == 1
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["agent_teams_flag"]["status"] == "FAIL"
    assert "true" in snap["checks"]["agent_teams_flag"]["detail"]


def test_flag_truthy_case_insensitive_fails(tmp_path, monkeypatch):
    """#276: 'TRUE'/'Yes'/'ON' (case-insensitive truthy) -> FAIL."""
    for i, value in enumerate(("TRUE", "Yes", "ON")):
        ws = tmp_path / f"ws-truthy-{i}"
        (ws / "runs").mkdir(parents=True)
        monkeypatch.setenv(FLAG_NAME, value)
        rc = run(ws)
        assert rc == 1
        snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
        assert snap["checks"]["agent_teams_flag"]["status"] == "FAIL", \
            f"{value}: {snap['checks']['agent_teams_flag']}"


def test_flag_empty_string_is_pass(tmp_path, monkeypatch):
    """#276: empty-string flag ('' ) -> PASS (default disabled)."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.setenv(FLAG_NAME, "")
    import env_check
    monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
    monkeypatch.setattr(env_check, "VM_HOST", "")
    run(ws)
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["agent_teams_flag"]["status"] == "PASS", \
        snap["checks"]["agent_teams_flag"]


# ---------- #409: platform de-hardcoding (analyzeHeadless + venv by sys.platform) ----------

def test_ghidra_check_uses_platform_analyze_headless_name(monkeypatch, tmp_path):
    """#409: the Ghidra check resolves support/analyzeHeadless(.bat) by
    sys.platform — .bat on Windows, NO extension on POSIX. GHIDRA_HOME set to
    a real install whose support/ holds ONLY the platform-correct name ->
    the module-computed GHIDRA_DEFAULT points there and check_ghidra() PASSes
    (macOS/Linux no longer search for a .bat that never exists)."""
    import importlib
    import env_check
    ghidra_home = tmp_path / "ghidra"
    support = ghidra_home / "support"
    support.mkdir(parents=True)
    headless = support / platform_paths.analyze_headless_name()
    headless.write_text("", encoding="utf-8")
    monkeypatch.setenv("GHIDRA_HOME", str(ghidra_home))
    importlib.reload(env_check)  # recompute module-level GHIDRA_DEFAULT from env

    assert env_check.GHIDRA_DEFAULT == headless, \
        f"GHIDRA_DEFAULT must use the platform analyzeHeadless name: {env_check.GHIDRA_DEFAULT}"
    ok, detail = env_check.check_ghidra()
    assert ok is True, detail
    assert platform_paths.analyze_headless_name() in detail


def test_venv_probe_dispatches_through_uv_project(monkeypatch, tmp_path):
    """issue 207: the probe runs the REAL runtime invocation — `uv run
    --project <SKILL_DIR> python -c "import yaml"` — never a venv binary with
    a hand-written dep list. The workspace has NO .venv: uv owns the env."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    skill_root = tmp_path / "skill-root"
    monkeypatch.setattr(env_check, "SKILL_DIR", skill_root)
    seen: list[list[str]] = []
    monkeypatch.setattr(env_check.shutil, "which",
                        lambda name: "/fake/bin/uv" if name == "uv" else None)

    def _capture(argv, **kwargs):
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(env_check.subprocess, "run", _capture)

    ok, detail = env_check.check_venv_sample(ws, None)
    assert ok is True, detail
    assert detail == "uv env OK (yaml)"
    assert seen == [["/fake/bin/uv", "run", "--locked", "--project",
                     str(skill_root), "python", "-c", "import yaml"]], seen


def test_venv_probe_pins_the_lock_so_a_probe_never_relocks(
        monkeypatch, tmp_path):
    """Finding 10 (issue 225): `uv run` WITHOUT --locked re-locks the
    project — it rewrites <skill_root>/uv.lock + .venv and PASSes drift
    that `uv sync --locked` rejects. The probe must run `uv run --locked`
    (the env still syncs from the lock; the lock is never mutated)."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    skill_root = tmp_path / "skill-root"
    monkeypatch.setattr(env_check, "SKILL_DIR", skill_root)
    seen: list[list[str]] = []
    monkeypatch.setattr(env_check.shutil, "which",
                        lambda name: "/fake/bin/uv" if name == "uv" else None)

    def _capture(argv, **kwargs):
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(env_check.subprocess, "run", _capture)

    ok, detail = env_check.check_venv_sample(ws, None)
    assert ok is True, detail
    assert seen, "the probe must run"
    assert "--locked" in seen[0], seen
    assert seen[0][:3] == ["/fake/bin/uv", "run", "--locked"], seen


def test_venv_probe_uv_missing_fails_naming_uv_layer(monkeypatch, tmp_path):
    """issue 207 + the issue 213 state ladder: no uv on PATH is a UV-LAYER
    failure carrying the install command — not a generic 'venv broken', and
    no env probe runs at all."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    monkeypatch.setattr(env_check, "SKILL_DIR", tmp_path / "skill-root")
    monkeypatch.setattr(env_check.shutil, "which", lambda name: None)

    def _must_not_run(*args, **kwargs):
        raise AssertionError("no env probe may run without uv")

    monkeypatch.setattr(env_check.subprocess, "run", _must_not_run)

    ok, detail = env_check.check_venv_sample(ws, None)
    assert ok is False
    assert "uv layer missing" in detail
    assert "uv run --project" in detail
    assert "astral.sh/uv/install.sh" in detail


def test_venv_probe_broken_env_fails_with_sync_repair(monkeypatch, tmp_path):
    """issue 207: a non-zero `uv run` is an ENV-LAYER failure carrying the
    `uv sync --locked --project <skill_root>` repair and the stderr head."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    skill_root = tmp_path / "skill-root"
    monkeypatch.setattr(env_check, "SKILL_DIR", skill_root)
    monkeypatch.setattr(env_check.shutil, "which",
                        lambda name: "/fake/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        env_check.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 1, "", "ModuleNotFoundError: No module named 'yaml'"))

    ok, detail = env_check.check_venv_sample(ws, None)
    assert ok is False
    assert "env layer broken" in detail
    assert f"uv sync --locked --project {skill_root}" in detail
    assert "No module named 'yaml'" in detail


def _uv_ok(monkeypatch, env_check, skill_root):
    """Pin a present uv + a rc=0 `uv run` (the lock-faithful success path)."""
    monkeypatch.setattr(env_check, "SKILL_DIR", skill_root)
    monkeypatch.setattr(env_check.shutil, "which",
                        lambda name: "/fake/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(
        env_check.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))


def test_venv_probe_lock_faithful_env_passes(monkeypatch, tmp_path):
    """issue 207 acceptance: a lock-faithful env (yaml present, cryptography
    absent from uv.lock) PASSes — the probe imports exactly what the lock
    ships, so a cryptography-only failure can no longer refuse Phase 0."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    _uv_ok(monkeypatch, env_check, tmp_path / "skill-root")

    ok, detail = env_check.check_venv_sample(ws, None)
    assert ok is True, detail
    assert detail == "uv env OK (yaml)"


def test_venv_probe_sample_sha_logic_unchanged(monkeypatch, tmp_path):
    """issue 207 keeps the sample-sha256 verdict logic byte-for-byte: match
    -> PASS suffix; mismatch -> FAIL; empty bins/ -> FAIL."""
    import hashlib
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    _uv_ok(monkeypatch, env_check, tmp_path / "skill-root")
    payload = b"MZ" + b"\x00" * 16
    (ws / "bins").mkdir()
    (ws / "bins" / "sample.exe").write_bytes(payload)
    good = hashlib.sha256(payload).hexdigest()

    ok, detail = env_check.check_venv_sample(ws, good)
    assert ok is True and detail == "uv env OK (yaml); sample sha256 OK", detail

    ok, detail = env_check.check_venv_sample(ws, "0" * 64)
    assert ok is False and "sha256 mismatch" in detail, detail

    (ws / "bins" / "sample.exe").unlink()
    ok, detail = env_check.check_venv_sample(ws, good)
    assert ok is False and "no sample under bins/" in detail, detail
