#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_ida_pro_unlock_46.py — issue #46: native IDA claims unreachable.

RED (verified on dev): the IDA MCP path is double-locked for the worker rack.

  LOCK 1 — agent allowlists. agents/kunglao-worker.md frontmatter allowedTools
  carries mcp__ghidra__* / mcp__x64dbg__* / mcp__frida__* / mcp__volatility__*
  / mcp__gitnexus__* but NO ida wildcard — a worker dispatched at the IDA MCP
  bridge has no tool grant (and #760's tools-rack gate would REJECT any rack
  citing an ida tool as "not in kunglao-worker allowedTools").

  LOCK 2 — tool-catalog gate. hooks/worker_budget_gates.py _toolfirst_evaluate
  validates the `tool-catalog:` marker against the keyword map derived from
  tools/_INDEX.yaml (_load_tool_index_keywords). _INDEX.yaml has ZERO ida
  entries, so a dispatch text naming IDA keywords can never reach
  mode='matched' by citing an ida tool — the gate rejects with
  detail_mode='self_attestation' and the only compliant citations point at
  other tools (or an opt-out). No compliant path -> native IDA claims
  unreachable for workers.

Naming resolution: the MCP registers as `ida-pro-vm`
(scripts/toolchain.py _DECOMPILER_MCP_NAMES, scripts/mcp_probe.py MANIFEST).
The issue title's `mcp__ida-pro-mcp__*` is a transcription of a live server
name; this fix follows the repo's own convention (`mcp__ida-pro-vm__*`) —
worker_budget_sinks matches the tolerant prefix `mcp__ida` for both faces.

GREEN shape:
  - tools/_INDEX.yaml registers `ida-decompile` (category static,
    capability ida:decompile — mirroring the ghidra:decompile shape)
  - tools/validate_index.py _CAPABILITY_TAGS admits ida:decompile
  - tools/_index-static.md carries the #339 contract entry
  - agents/{kunglao-worker,kunglao-redteam,ghidra-light}.md allowedTools
    carry mcp__ida-pro-vm__* (the decompiler-capable rack — every agent
    whose allowedTools already grant mcp__ghidra__*)
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import validate_index as vi  # noqa: E402
import worker_budget_gates as wbg  # noqa: E402

IDA_TOOL = "ida-decompile"
IDA_MCP_WILDCARD = "mcp__ida-pro-vm__*"

# agents whose allowedTools already grant the sibling decompiler MCP
# (mcp__ghidra__*) — the decompiler-capable rack. Agents that DISALLOW
# ghidra (floss-filter, pefile-signature, verdict-scorer, web-re-worker,
# kunglao-init-worker) are deliberately untouched.
DECOMPILER_RACK_AGENTS = ("kunglao-worker", "kunglao-redteam", "ghidra-light")


def _agent_allowedtools(agent: str) -> list[str]:
    text = (ROOT / "agents" / f"{agent}.md").read_text(encoding="utf-8")
    fm = text.split("---", 2)[1]
    data = yaml.safe_load(fm) or {}
    return [str(t).strip() for t in (data.get("allowedTools") or [])]


# ---------- LOCK 2 (gate): keyword map + marker match ----------

def test_ida_keyword_registered_in_gate_keyword_map():
    keywords = wbg._load_tool_index_keywords(wbg._SKILL_ROOT)
    assert keywords.get("ida") == IDA_TOOL, (
        "tools/_INDEX.yaml must register an ida capability so the "
        "tool-catalog keyword map knows 'ida' (LOCK 2)")


def test_ida_dispatch_marker_reaches_matched():
    text = ("decompile function sub_140001000 in the ida database and "
            "quote pseudocode into the fact file")
    ev = wbg._toolfirst_evaluate(text, IDA_TOOL)
    assert ev["mode"] == "matched", (
        f"expected matched, got {ev} — a dispatch citing the ida tool must "
        "have a compliant path through the tool-catalog gate")


def test_ida_dispatch_check_tool_first_passes():
    ok, reason = wbg.check_tool_first(
        {}, "use ida to decompile the crypto routine",
        f"tool-catalog: {IDA_TOOL}")
    assert ok is True, f"gate must pass an ida-citing dispatch: {reason}"


def test_ida_capability_tag_in_closed_vocabulary():
    assert "ida:decompile" in vi._CAPABILITY_TAGS, (
        "validate_index closed vocabulary must admit ida:decompile "
        "(one tag = one routing capability, #729 Rule B)")


def test_shipped_index_still_validates_with_ida_entry():
    data = yaml.safe_load(
        (ROOT / "tools" / "_INDEX.yaml").read_text(encoding="utf-8"))
    names = [t.get("name") for t in data["tools"]]
    assert IDA_TOOL in names, f"{IDA_TOOL} missing from _INDEX.yaml"
    assert vi.validate_index(data) == [], "shipped index must stay valid"


# ---------- LOCK 1 (allowlists): agent frontmatter ----------

def test_worker_rack_allows_ida_mcp():
    tools = _agent_allowedtools("kunglao-worker")
    assert IDA_MCP_WILDCARD in tools, (
        "kunglao-worker allowedTools must grant mcp__ida-pro-vm__* "
        "(LOCK 1 — the worker rack is the issue's subject)")


def test_decompiler_rack_agents_allow_ida_mcp():
    for agent in DECOMPILER_RACK_AGENTS:
        tools = _agent_allowedtools(agent)
        assert IDA_MCP_WILDCARD in tools, (
            f"{agent} grants mcp__ghidra__* (decompiler-capable rack) but "
            "not mcp__ida-pro-vm__*")
        assert "mcp__ghidra__*" in tools, (
            f"{agent} is expected to be a ghidra-granting agent; if it "
            "dropped ghidra, drop it from this test's rack list too")


def test_ghidra_disallowing_agents_do_not_gain_ida():
    # scope guard: the fix targets the decompiler-capable rack only
    for agent in ("floss-filter", "pefile-signature", "verdict-scorer",
                  "web-re-worker"):
        tools = _agent_allowedtools(agent)
        assert IDA_MCP_WILDCARD not in tools, (
            f"{agent} disallows mcp__ghidra__*; it must not silently gain "
            "the ida MCP either")


# ---------- LOCK 1 enforcement face: #760 tools-rack gate ----------

def test_rack_gate_accepts_ida_tool_for_worker():
    import dispatch_gate as dg
    violation = dg._tools_contract_violation(
        ["mcp__ida-pro-vm__decompile_function", "Write"], "kunglao-worker")
    assert violation is None, (
        f"a rack citing the ida MCP bridge must clear #760: {violation}")


# ---------- naming resolution anchor ----------

def test_mcp_registers_as_ida_pro_vm():
    sys.path.insert(0, str(ROOT / "scripts"))
    import toolchain
    assert "ida-pro-vm" in toolchain._DECOMPILER_MCP_NAMES, (
        "the repo's own convention names the IDA MCP 'ida-pro-vm'; the "
        "wildcard must match the registered name (issue title says "
        "mcp__ida-pro-mcp__* — see module docstring)")


# ---------- regressions: ghidra/android paths unchanged ----------

def test_ghidra_keyword_and_marker_still_matched():
    text = "decompile the guard dispatcher and recover the vtable"
    ev = wbg._toolfirst_evaluate(text, "ghidra-decompile-functions")
    assert ev["mode"] == "matched", f"ghidra path regressed: {ev}"


def test_android_keywords_unaffected():
    # keywords derive from category + capability halves, not tool names
    # (android:java-source -> jadx-decompile, android:bytecode-truth ->
    # baksmali-xref) — the ida entry must not shadow any of them
    keywords = wbg._load_tool_index_keywords(wbg._SKILL_ROOT)
    assert keywords.get("android") == "jadx-decompile"
    assert keywords.get("java-source") == "jadx-decompile"
    assert keywords.get("bytecode-truth") == "baksmali-xref"
    ev = wbg._toolfirst_evaluate(
        "recover the java-source tree from the dex (android target)",
        "jadx-decompile")
    assert ev["mode"] == "matched", f"android path regressed: {ev}"


def test_ghidra_agent_rack_still_matches_after_ida_addition():
    tools = _agent_allowedtools("ghidra-light")
    assert "mcp__ghidra__*" in tools
    assert "mcp__ida-pro-vm__*" in tools
