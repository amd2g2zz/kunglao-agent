# -*- coding: utf-8 -*-
"""E2E MCP arming pins: a unit's declared MCP supply reaches the
WORKER, not just the gate.

The gate (post toolchain-parity) reads the workspace
.mcp.json surface only. But three links were missing between the gate and the act:

  1. nothing WRITES the declared server into ws/.mcp.json
  2. nothing sets the sudo-free approval flag (a workspace-scope
     registration without enableAllProjectMcpServers hangs
     "pending approval" forever — the approval trap)
  3. the headless act's --allowedTools rack carries no MCP tools,
     so even a registered server is uncalled by the worker

The fix: task.yaml tools.mcp_servers {name: url} arms all three —
ws/.mcp.json entries + the approval flag + the server's tool prefix
on the dispatch rack for that unit's acts.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import yaml  # repo dep via pythonpath

from e2e import checkpoints as cp        # noqa: E402
from e2e import llm_faces, model        # noqa: E402


def _task(tmp_path, servers):
    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({
        "task_id": "u",
        "tools": {"decompiler_lane": "required",
                  "mcp_servers": servers}}), encoding="utf-8")
    return task


class _Ctx:
    pass


def _ctx(tmp_path, task):
    ctx = _Ctx()
    ctx.ws = tmp_path / "ws"
    ctx.ws.mkdir(exist_ok=True)
    ctx.state = model.RunState(
        run_id="r", unit="u", family="f", repo=str(tmp_path),
        task_dir=str(tmp_path), ws=str(ctx.ws),
        evidence_dir=str(tmp_path), budget_seconds=9999,
        llm_mode="auto", started_ts="", started_monotonic=0.0,
        anchors={})
    ctx.attempts = {}
    ctx.acts = []
    return ctx


def test_arming_writes_ws_registration_and_flag(tmp_path):
    task = _task(tmp_path, {"ida-pro-vm": "http://127.0.0.1:8745/mcp"})
    ctx = _ctx(tmp_path, task)
    prefixes = cp._arm_mcp_supply(ctx, task)
    mcp = json.loads((ctx.ws / ".mcp.json").read_text(encoding="utf-8"))
    assert "ida-pro-vm" in (mcp.get("mcpServers") or {}), mcp
    settings = json.loads(
        (ctx.ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings.get("enableAllProjectMcpServers") is True
    assert prefixes == ["mcp__ida-pro-vm"], prefixes


def test_arming_without_declaration_changes_nothing(tmp_path):
    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({"task_id": "u"}), encoding="utf-8")
    ctx = _ctx(tmp_path, task)
    prefixes = cp._arm_mcp_supply(ctx, task)
    assert prefixes == []
    assert not (ctx.ws / ".mcp.json").exists() or \
        "ida-pro-vm" not in (
            json.loads((ctx.ws / ".mcp.json").read_text(encoding="utf-8"))
            .get("mcpServers") or {})


def test_rack_carries_the_mcp_prefix(tmp_path):
    """The headless act's allowedTools gains the server's tool prefix —
    a registered server an act may not call is decoration."""
    req = model.DispatchRequest(
        claim="C-004", workspace=str(tmp_path),
        prompt_file=str(tmp_path / "p.md"), run_id="r",
        mcp_prefixes=("mcp__ida-pro-vm",))
    rack = llm_faces._rack_of(req)
    assert any(r.startswith("mcp__ida-pro-vm") for r in rack), rack


def test_legacy_supply_honors_registered_mcp(tmp_path):
    """The 3-path OR holds on the legacy (linux/windows) branch too: a
    workspace-registered decompiler MCP satisfies the supply — matrix4d
    field finding: native units died at the ARMED gate with the MCP
    registered, because the legacy face only knew GHIDRA_HOME."""
    import env_check
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"ida-pro-vm": {
            "type": "http", "url": "http://127.0.0.1:8745/mcp"}}}),
        encoding="utf-8")
    status, msg = env_check.check_ghidra_typed(ws, "linux")
    assert status == "PASS", (status, msg)
    assert "ida-pro-vm" in msg, msg
