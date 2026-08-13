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
Ghidra via GHIDRA_DEFAULT, hooks via isolated_home USERPROFILE, venv probe via
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
    """Minimal workspace: runs/ exists so the snapshot write succeeds."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _write_settings(home: Path) -> Path:
    """settings.json carrying all wire-up hooks — makes check ④ pass."""
    settings = home / ".claude" / "settings.json"
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


def test_all_pass_exit_0(monkeypatch, tmp_path, isolated_home):
    """Scenario 3: flag unset + VM up + Ghidra present + hooks deployed +
    venv deps importable -> overall PASS, exit 0, snapshot written."""
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
    # hooks: isolated_home points USERPROFILE/HOME at tmp — deploy the hooks
    _write_settings(isolated_home)
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
