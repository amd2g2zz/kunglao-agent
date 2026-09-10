# -*- coding: utf-8 -*-
"""tests/test_state_layer_diagnosis_213.py — issue 213 contract (TDD).

Field evidence: three same-shape failures in one session — "MCP tools
unreachable" read as "the MCP is dead" (truth: registered, venv broken —
connection layer, agent-repairable); "idat64 not found" read as "IDA not
installed" (installed as a .app bundle, binary name differed); an x86_64
libidalib + python 3.14 environment pip-installed the binding anyway. One
pattern: a single-layer symptom generalized to total failure; remediation
skipped layers.

Contract pinned here:
(a) guidance — SKILL.md carries the five ladder layers IN ORDER plus the
    four state-layer rules;
(b) toolchain — a registered-but-connection-broken MCP item renders the
    connection layer and an agent-do repair (never a "dead" verdict,
    never a fallback-tool recommendation), while a not-registered item
    renders the register layer with a fix that stays a RUNNABLE register
    command (the fix string is an execution seam);
(c) the distilled convergence rules name the no-tool-jumping rule.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = ROOT / "skills" / "kunglao-agent" / "SKILL.md"
RULES_MD = (ROOT / "skills" / "kunglao-agent" / "rules"
            / "kunglao-convergence-loop.md")

LADDER_LAYERS = ("installed?", "registered?", "connects?",
                 "capable?", "input ready?")


# ---------- (a) guidance contract ----------

def test_skill_md_names_five_ladder_layers_in_order():
    text = SKILL_MD.read_text(encoding="utf-8")
    positions = [text.find(layer) for layer in LADDER_LAYERS]
    missing = [l for l, p in zip(LADDER_LAYERS, positions) if p < 0]
    assert not missing, f"ladder layers absent from SKILL.md: {missing}"
    assert positions == sorted(positions), (
        f"ladder layers out of order in SKILL.md: "
        f"{list(zip(LADDER_LAYERS, positions))}")


def test_skill_md_carries_the_state_layer_rules():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "failed layer" in text, "repair-at-the-failed-layer rule missing"
    assert "issue 210" in text, "decompiler XOR family (issue 210) not named"
    assert "decision invalidity" in text, (
        "fallback-while-primary-repairable rule missing")
    assert 'never a "dead" verdict' in text, (
        "layer-naming report rule missing")


# ---------- (b) toolchain contract ----------

def _registered_mcp_item():
    import toolchain as tc
    return tc.CheckResult(
        name="mcp:ida-pro-vm", status=tc.Status.PASS, tier=tc.Tier.HARD,
        detail="registered (user-global)")


def test_registered_but_unreachable_names_connection_layer(monkeypatch,
                                                           tmp_path):
    import toolchain as tc
    monkeypatch.setattr(
        tc, "_tcp_connect",
        lambda host, port: (False, "connection refused"))
    claude_json = tmp_path / "claude.json"
    claude_json.write_text(json.dumps(
        {"mcpServers": {"ida-pro-vm": {"url": "http://127.0.0.1:1"}}}),
        encoding="utf-8")
    item = tc._mcp_reachability_face(
        _registered_mcp_item(), "ida-pro-vm", claude_json, tmp_path)
    assert item.status is tc.Status.WARN
    assert item.detail.startswith("connection layer"), item.detail
    assert item.fix and item.fix.startswith("connection layer"), item.fix
    assert "agent-do" in item.fix, "repair must be agent-do"
    assert "uv sync" in item.fix, "broken venv repair = uv sync in the venv"
    rendered = tc.format_human(
        tc.ToolchainReport(project_type="macos", items=[item]))
    assert "dead" not in rendered, "no 'dead' verdict — name the layer"
    assert "choco install ghidra" not in rendered, "no fallback-tool rec"
    assert "local IDA install" not in rendered, "no fallback-tool rec"


def test_unregistered_task_spec_item_names_register_layer(tmp_path):
    import toolchain as tc
    claude_json = tmp_path / "claude.json"  # registry absent
    checks = tc._task_spec_mcp_checks(
        (tc.McpServerSpec(name="ida-pro-vm", transport="http",
                          url="http://127.0.0.1:1"),),
        claude_json, tmp_path)
    assert len(checks) == 1 and checks[0].status == "FAIL"
    assert checks[0].detail.startswith("register layer"), checks[0].detail
    # execution seam: the fix is fed to _concrete_register_argv verbatim —
    # it must stay a runnable register command, prose never rides it
    argv = tc._concrete_register_argv(checks[0].fix, "http://127.0.0.1:1")
    assert argv is not None and argv[:2] == ["claude", "mcp"], argv


# ---------- (c) distilled rules contract ----------

def test_convergence_rules_name_the_no_tool_jumping_rule():
    text = RULES_MD.read_text(encoding="utf-8")
    assert "tool-jumping" in text, "no-tool-jumping rule missing"
    assert "failed layer" in text, "repair-at-layer rule missing"
    assert all(layer in text for layer in LADDER_LAYERS), (
        "ladder layers must be named in the distilled rules")
