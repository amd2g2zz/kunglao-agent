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