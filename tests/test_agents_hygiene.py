#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_agents_hygiene.py — mechanical hygiene pins for agents/*.md.

Governance sweep pins: every agent definition file must carry ZERO
tracker-reference tokens, ZERO dated narration fragments, and MUST provide
the operator-facing plan/status panels. Parametrized over sorted filenames
so a failure names the offending file.

Pins per agents/*.md (whole file, frontmatter included):
  - regex r"#\d{3}" finds ZERO matches
  - regex r"20\d\d-\d\d-\d\d" finds ZERO matches
  - contains "## Plan-to-execute" AND "## Status reporting" panels
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_FILES = sorted((REPO_ROOT / "agents").glob("*.md"))
assert AGENT_FILES, f"no agent definitions under {REPO_ROOT / 'agents'} (fail-closed)"

TRACKER_TOKEN_RE = re.compile(r"#\d{3}")
DATED_NARRATION_RE = re.compile(r"20\d\d-\d\d-\d\d")
PANEL_HEADINGS = ("## Plan-to-execute", "## Status reporting")


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.name)
def test_no_tracker_refs(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    hits = TRACKER_TOKEN_RE.findall(text)
    assert not hits, f"{path.name}: tracker tokens present: {sorted(set(hits))}"


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.name)
def test_no_dated_narration(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    hits = DATED_NARRATION_RE.findall(text)
    assert not hits, f"{path.name}: dated narration present: {sorted(set(hits))}"


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.name)
def test_plan_status_panels(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [h for h in PANEL_HEADINGS if h not in text]
    assert not missing, f"{path.name}: missing panel headings: {missing}"


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.name)
def test_no_conflict_markers(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "<<<<<<<" not in text and ">>>>>>>" not in text, (
        f"{path.name}: leftover merge-conflict markers"
    )

# ---------- #790 follow-up: tooling-matrix pins (docs/agent-tooling-matrix.md) ----------

def _fm(role: str) -> dict:
    import yaml
    p = REPO_ROOT / "agents" / f"{role}.md"
    return yaml.safe_load(p.read_text(encoding="utf-8").split("---")[1])


def _allow(role: str):
    return set(_fm(role)["allowedTools"])


def _deny(role: str):
    return set(_fm(role)["disallowedTools"])


MATRIX_SPOT = {
    # role: (must-have allow entries, must-have deny entries)
    "verdict-scorer": (["Read", "mcp__sequential-thinking__sequentialthinking"], ["Bash"]),
    "web-re-worker": (["mcp__camoufox-reverse__*", "mcp__gitnexus__*"],
                      ["mcp__ghidra__*", "mcp__x64dbg__*",
                       "mcp__frida__*", "mcp__volatility__*"]),
    "kunglao-worker": (["mcp__ghidra__*", "Skill"],
                       ["NotebookEdit"]),
}


def test_tooling_matrix_spot_pins():
    import yaml as _y
    for role, (need_allow, need_deny) in MATRIX_SPOT.items():
        fm = _y.safe_load(
            (REPO_ROOT / "agents" / f"{role}.md").read_text(encoding="utf-8")
            .split("---")[1])
        allow = [str(x) for x in fm.get("allowedTools") or []]
        deny = [str(x) for x in fm.get("disallowedTools") or []]
        for n in need_allow:
            assert any(n in a for a in allow), (
                f"{role}: expected allowance {n!r} missing -> {allow}")
        for n in need_deny:
            assert any(n in d for d in deny), (
                f"{role}: expected explicit denial {n!r} missing -> {deny}")
