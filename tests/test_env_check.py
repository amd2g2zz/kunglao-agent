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
#410. The user-global file is NOT a deployment target), venv probe via
subprocess.run.

#410 (2026-08-17): the hooks check is TRI-STATE — PASS (all registry hooks in
either target), WARN (no target wired — per-workspace optional, static analysis
proceeds), FAIL (partial deployment — some registry hooks dropped, the
#258/#372 silent-drop class).
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

import platform_paths  # pytest.ini pythonpath = . hooks scripts tools

from env_check import (  # pytest.ini pythonpath = . hooks scripts tools
    FLAG_NAME,
    HOOK_FILES,
    run,
)


def _kunglao_ws(tmp_path: Path) -> Path:
    """Minimal workspace: runs/ + FULLY initialized state (#304: [initialized]
    marker in claim-register.yaml + project_type in analysis_state.txt) so the
    snapshot write succeeds and init_complete passes."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
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
    derives from the registry (all 8 files, recall_inject under Pre/Agent,
    completion_gate under Stop)."""
    settings = target_root / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    pre_agent = ["worker_budget.py", "dispatch_gate.py", "env_check_gate.py",
                 "recall_inject.py"]
    pre = [{"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python C:/skills/hooks/{h}"}]}
        for h in pre_agent]
    post = [{"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python C:/skills/hooks/{h}"}]}
        for h in ("worker_budget.py", "worker_pulse.py", "state_anchor.py")]
    pre.append({"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python C:/skills/hooks/heartbeat_touch.py"}]})
    stop = [{"hooks": [
        {"type": "command", "command": "python C:/skills/hooks/completion_gate.py"}]}]
    settings.write_text(json.dumps({"hooks": {"PreToolUse": pre,
                                              "PostToolUse": post,
                                              "Stop": stop}}),
                        encoding="utf-8")
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
        {"type": "command", "command": f"python C:/skills/hooks/{h}"}]}
        for h in pre_agent]
    pre.append({"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python C:/skills/hooks/heartbeat_touch.py"}]})
    post = [{"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python C:/skills/hooks/{h}"}]}
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
    """Scenario 2: VM sockets refused/timed out -> vm check FAIL, exit 1 (recoverable)."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)

    def _boom(*args, **kwargs):
        raise OSError("mock: connection timed out")

    import env_check
    # #228: no default VM host — set one so this test exercises the socket path
    monkeypatch.setattr(env_check, "VM_HOST", "127.0.0.1")
    monkeypatch.setattr(env_check.socket, "create_connection", _boom)
    rc = run(ws)
    assert rc == 1
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["vm_reachability"]["status"] == "FAIL"


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
    # venv: fake SKILL-root venv python (platform layout) exists; probe
    # subprocess returns rc=0 — #409: the authoritative interpreter is the
    # SKILL-root venv (uv run --project <skill_root>), not ws/.venv.
    monkeypatch.setattr(env_check, "SKILL_DIR", tmp_path / "skill-root")
    venv_py = platform_paths.venv_python(env_check.SKILL_DIR / ".venv")
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        env_check.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""),
    )

    rc = run(ws)
    assert rc == 0
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["overall"] == "PASS"
    assert all(c["status"] == "PASS" for c in snap["checks"].values())


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


def test_venv_check_ignores_workspace_venv_when_skill_root_present(monkeypatch, tmp_path):
    """#409: the venv check probes the SKILL-root venv (uv run --project
    <skill_root>) resolved by sys.platform (bin/python | Scripts/python.exe)
    — NOT the workspace .venv. A workspace with NO .venv at all still PASSes
    when the skill-root venv (platform layout) exists."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    monkeypatch.setattr(env_check, "VM_HOST", "")
    monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
    monkeypatch.setattr(env_check, "SKILL_DIR", tmp_path / "skill-root")
    # Only the SKILL-root venv exists (platform layout) — no ws/.venv at all
    skill_py = platform_paths.venv_python(env_check.SKILL_DIR / ".venv")
    skill_py.parent.mkdir(parents=True)
    skill_py.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        env_check.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""),
    )

    run(ws)
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["venv_sample"]["status"] == "PASS", \
        f"workspace .venv must be ignored when skill-root venv is authoritative: {snap['checks']['venv_sample']}"


def test_venv_python_resolves_by_platform():
    """#409: venv_python resolves Scripts/python.exe on Windows, bin/python
    on POSIX — the layout the resolver picks must exist under a real venv
    root shape."""
    root = Path("/tmp/kunglao-test-venv")
    py = platform_paths.venv_python(root)
    assert py.name == platform_paths.venv_python_name()
    if os.name == "nt":
        assert py == root / "Scripts" / "python.exe"
    else:
        assert py == root / "bin" / "python"
