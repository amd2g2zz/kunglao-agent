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
Ghidra via GHIDRA_DEFAULT, hooks via the PROJECT-level <ws>/.claude/settings.json
(#258/#269 — the user-global file is NOT a deployment target), venv probe via
subprocess.run.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

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
    makes check ④ pass. target_root=ws -> PROJECT level (the #258/#269
    deployment target); target_root=isolated_home -> user-global (used by the
    negative regression test)."""
    settings = target_root / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    pre = [{"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python C:/skills/hooks/{h}"}]}
        for h in HOOK_FILES if h in ("worker_budget.py", "dispatch_gate.py", "env_check_gate.py")]
    post = [{"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python C:/skills/hooks/{h}"}]}
        for h in HOOK_FILES if h in ("worker_pulse.py", "state_anchor.py")]
    pre.append({"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python C:/skills/hooks/heartbeat_touch.py"}]})
    settings.write_text(json.dumps({"hooks": {"PreToolUse": pre, "PostToolUse": post}}),
                        encoding="utf-8")
    return settings


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
    fake_ghidra = tmp_path / "analyzeHeadless.bat"
    fake_ghidra.write_text("", encoding="utf-8")
    monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", fake_ghidra)
    # hooks: PROJECT-level <ws>/.claude/settings.json (#258/#269)
    _write_settings(ws)
    # venv: fake python.exe exists; probe subprocess returns rc=0
    venv_py = ws / ".venv" / "Scripts" / "python.exe"
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
    """#269 regression: the hooks check must read the PROJECT-level
    <ws>/.claude/settings.json — the #258 deployment target — NOT the
    user-global ~/.claude/settings.json. A user-global-only deployment (the
    pre-#258 shape, 0 hooks in the project file) must be reported FAIL, not
    misreported as deployed."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    _write_settings(isolated_home)  # user-global only — must NOT satisfy check ④
    assert not (ws / ".claude" / "settings.json").exists(), \
        "test setup: project-level settings must be absent"
    assert run(ws) == 1
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["hooks_deployed"]["status"] == "FAIL", \
        "user-global-only deployment must fail the project-level check (#269)"
    assert "settings.json" in snap["checks"]["hooks_deployed"]["detail"]


def test_hooks_fail_when_no_project_settings(monkeypatch, tmp_path):
    """No project-level settings.json at all -> hooks_deployed FAIL with
    --wire-up guidance (a correctly deployed workspace must never be
    misreported as PASS on the strength of the user-global file)."""
    ws = _kunglao_ws(tmp_path)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    assert run(ws) == 1
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["hooks_deployed"]["status"] == "FAIL"
    assert "--wire-up" in snap["checks"]["hooks_deployed"]["detail"]


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
