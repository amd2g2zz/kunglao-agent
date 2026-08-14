# -*- coding: utf-8 -*-
"""Tests for init-completeness gate (#304): env_check + env_check_gate.

TDD RED phase: tests for:
- env_check.py new init_complete HARD check
- env_check_gate.py reject dispatch when workspace lacks init completion
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"


@pytest.fixture
def untwisted_ws(tmp_path: Path) -> Path:
    """Workspace WITHOUT init completion (no project_type)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n",
        encoding="utf-8",
    )
    # analysis_state.txt exists but NO project_type
    (ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\n", encoding="utf-8",
    )
    return ws


@pytest.fixture
def typed_ws(tmp_path: Path) -> Path:
    """Workspace WITH init completion (marker + project_type)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n",
        encoding="utf-8",
    )
    (ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=windows\n", encoding="utf-8",
    )
    return ws


# ---------- env_check.py init_complete check ----------

def test_env_check_init_complete_fail_on_untyped(untwisted_ws: Path, monkeypatch):
    """env_check FAILs init_complete check when project_type missing."""
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    # Suppress other checks to isolate init_complete
    monkeypatch.setattr(env_check, "VM_HOST", "")
    monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
    rc = env_check.run(untwisted_ws)
    assert rc != 0, "un-typed workspace should FAIL env_check"
    snap = json.loads((untwisted_ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["init_complete"]["status"] == "FAIL", snap


def test_env_check_init_complete_pass_on_typed(typed_ws: Path, monkeypatch):
    """env_check PASSes init_complete when project_type present."""
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    monkeypatch.setattr(env_check, "VM_HOST", "")
    monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
    # Note: other checks may still fail (hooks, etc.) but init_complete should pass
    rc = env_check.run(typed_ws)
    snap = json.loads((typed_ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["init_complete"]["status"] == "PASS", snap


def test_env_check_init_complete_no_register(tmp_path: Path, monkeypatch):
    """No claim-register.yaml at all -> init_complete FAIL."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    monkeypatch.delenv(FLAG_NAME, raising=False)
    import env_check
    monkeypatch.setattr(env_check, "VM_HOST", "")
    monkeypatch.setattr(env_check, "GHIDRA_DEFAULT", None)
    rc = env_check.run(ws)
    snap = json.loads((ws / "runs" / ".env-check.json").read_text(encoding="utf-8"))
    assert snap["checks"]["init_complete"]["status"] == "FAIL"


# ---------- env_check_gate.py init completeness ----------

def test_gate_rejects_untyped_workspace(untwisted_ws: Path):
    """env_check_gate rejects Agent dispatch in un-typed workspace."""
    from env_check_gate import evaluate
    payload = {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(untwisted_ws),
        "tool_input": {"prompt": "claim C-001"},
    }
    # Clean env (no agent teams flag)
    rc, stderr, ctx = evaluate(payload, environ={})
    assert rc == 2, f"un-typed workspace should be REJECTED, got {rc}"
    assert ctx is not None, "rejection should carry guidance"
    assert "init" in ctx.lower() or "project_type" in ctx.lower() or "type" in ctx.lower()


def test_gate_allows_typed_workspace(typed_ws: Path):
    """env_check_gate allows Agent dispatch in typed workspace."""
    from env_check_gate import evaluate
    payload = {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(typed_ws),
        "tool_input": {"prompt": "claim C-001"},
    }
    rc, stderr, ctx = evaluate(payload, environ={})
    assert rc == 0, f"typed workspace should pass, got {rc}; stderr={stderr}"


def test_gate_guidance_mentions_kunglao_init(untwisted_ws: Path):
    """Rejection guidance mentions kunglao-init.py as the fix."""
    from env_check_gate import evaluate
    payload = {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(untwisted_ws),
        "tool_input": {"prompt": "claim C-001"},
    }
    _, stderr, ctx = evaluate(payload, environ={})
    assert ctx is not None
    assert "kunglao-init" in ctx, f"guidance should mention kunglao-init: {ctx}"


def test_gate_flag_and_init_both_reject(untwisted_ws: Path):
    """Both flag set AND un-typed -> rejection (flag takes precedence in error text)."""
    from env_check_gate import evaluate
    payload = {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(untwisted_ws),
        "tool_input": {"prompt": "claim C-001"},
    }
    rc, stderr, ctx = evaluate(payload, environ={FLAG_NAME: "1"})
    assert rc == 2, "should reject (flag set + un-typed)"


# ---------- F6 (#304 review): single source of truth — scripts/init_state.py ----------

def test_init_state_module_is_single_source(tmp_path: Path):
    """F6: the completeness predicate lives in ONE module; its results drive
    all three call sites (kunglao-init / env_check / env_check_gate)."""
    import init_state
    ws = tmp_path / "ws"
    ws.mkdir()
    # no register -> incomplete
    assert init_state.is_init_complete(ws) is False
    ok, detail = init_state.init_complete(ws)
    assert not ok and "claim-register" in detail
    # register without marker -> incomplete
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    assert init_state.is_init_complete(ws) is False
    # marker + invalid project_type -> incomplete, detail names the invalid type
    (ws / "claim-register.yaml").write_text(
        "# [initialized] state_hash=abc seeds=3\nclaims: []\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=banana\n", encoding="utf-8")
    ok, detail = init_state.init_complete(ws)
    assert not ok and "invalid project_type" in detail
    # marker + valid type -> complete
    (ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=windows\n", encoding="utf-8")
    ok, detail = init_state.init_complete(ws)
    assert ok and "windows" in detail
    assert init_state.is_init_complete(ws) is True


def test_kunglao_init_uses_shared_predicate():
    """F6: kunglao-init.is_init_complete IS init_state.is_init_complete —
    no local duplicate of the predicate."""
    import importlib.util
    import init_state
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_shared_check", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.is_init_complete is init_state.is_init_complete, \
        "kunglao-init must reference the shared predicate"


def test_env_check_uses_shared_predicate():
    """F6: env_check.check_init_complete delegates to the shared module."""
    import inspect
    import env_check
    import init_state
    src = inspect.getsource(env_check.check_init_complete)
    assert "init_state" in src, "env_check must reference the shared predicate"
    assert env_check.check_init_complete.__doc__ and "init_state" in env_check.check_init_complete.__doc__


def test_env_check_gate_uses_shared_predicate():
    """F6: env_check_gate._check_init_complete delegates to the shared module."""
    import inspect
    import env_check_gate
    src = inspect.getsource(env_check_gate._check_init_complete)
    assert "init_state" in src, "env_check_gate must reference the shared predicate"


def test_shared_predicate_agrees_across_call_sites(tmp_path: Path):
    """F6: all three call sites agree on the same workspace (no drift)."""
    import init_state
    import env_check
    from env_check_gate import evaluate as gate_evaluate

    def _mk_ws(name: str, typed: bool) -> Path:
        ws = tmp_path / name
        ws.mkdir()
        (ws / "claim-register.yaml").write_text(
            "# [initialized] state_hash=abc seeds=3\n"
            "claims:\n- id: C-001\n  status: OPEN\n",
            encoding="utf-8",
        )
        state = "agent_teams_flag=0\n"
        if typed:
            state += "project_type=windows\n"
        (ws / "analysis_state.txt").write_text(state, encoding="utf-8")
        return ws

    untyped = _mk_ws("untyped", typed=False)
    typed = _mk_ws("typed", typed=True)

    # incomplete workspace: env_check FAILs, gate REJECTs, predicate False
    assert init_state.is_init_complete(untyped) is False
    ok_env, _ = env_check.check_init_complete(untyped)
    assert ok_env is False
    rc, _, _ = gate_evaluate(
        {"cwd": str(untyped), "tool_input": {}}, environ={})
    assert rc == 2

    # complete workspace: env_check PASSes, gate allows, predicate True
    assert init_state.is_init_complete(typed) is True
    ok_env, _ = env_check.check_init_complete(typed)
    assert ok_env is True
    rc, _, _ = gate_evaluate(
        {"cwd": str(typed), "tool_input": {}}, environ={})
    assert rc == 0
