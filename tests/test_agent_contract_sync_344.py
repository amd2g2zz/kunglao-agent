#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_agent_contract_sync_344.py — contract-sync pins for maker-type
agent files (issue 344, pure contract resync of agents/web-re-worker.md).

agents/kunglao-worker.md is the canonical contract carrier: dispatch envelope
+ tier table (D1), plan dispatch-anchor + per-step if-fails (D2), four-field
failure block (D3), LEARN→TRY→ESCALATE ladder (D4), trace echo (D5),
recall_useful + tool-catalog markers (D6). web-re-worker.md historically
drifted off those sections; this file pins the marker set mechanically on
BOTH files so future drift fails CI instead of surfacing as an unequipped
specialist worker.

Also pins the D8 phrasing fix: the jsvmp_triage verdict rule is "any two of
three features" (tools/web/jsvmp_triage.py: `votes = int(f1) + int(f2) +
int(f3); confident = votes >= 2`; F3 votes only when a case table exists).
The backwards coinage "three-of-two" must not reappear in agent files.

Scope note: ghidra-light / go-symbols / pefile-signature / floss-filter
legitimately lack parts of this marker set today. Extending the pin to them
is deliberate follow-up work — this card does NOT mass-edit specialist files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / "agents"

# The two files this card touches: the canonical carrier + the resync target.
PINNED_AGENT_FILES = ("kunglao-worker.md", "web-re-worker.md")

FAILURE_FIELDS = (
    "method_assumption",
    "assumption_validity",
    "what_I_tried",
    "possible_next",
)


def _text(name: str) -> str:
    path = AGENTS_DIR / name
    assert path.exists(), f"missing agent definition: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_dispatch_format_envelope_or_tier_sketch(name: str) -> None:
    """D1: the dispatch format section — v1 JSON envelope or the v0 tier
    sketch, plus the T1/T2/T3 tier meanings."""
    text = _text(name)
    has_envelope = ("kunglao_dispatch" in text) or ("[T<" in text)
    assert has_envelope, f"{name}: no dispatch envelope (v1 kunglao_dispatch / v0 [T<) documented"
    for tier in ("T1", "T2", "T3"):
        assert tier in text, f"{name}: tier meaning {tier} not documented"
    assert "self-restrict" in text, f"{name}: tools/tier self-restriction rule missing"


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_plan_dispatch_anchor_rule(name: str) -> None:
    """D2: the plan cites its dispatch anchor."""
    assert "dispatch-anchor:" in _text(name), (
        f"{name}: no dispatch-anchor citation rule in the plan contract"
    )


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_plan_per_step_if_fails_rule(name: str) -> None:
    """D2: every enumerated plan step carries an if-fails branch."""
    assert "if-fails:" in _text(name), f"{name}: no per-step if-fails rule in the plan contract"


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_failure_block_four_fields(name: str) -> None:
    """D3: the four-field failure report block."""
    text = _text(name)
    missing = [f for f in FAILURE_FIELDS if f not in text]
    assert not missing, f"{name}: failure block missing fields: {missing}"


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_self_drive_ladder(name: str) -> None:
    """D4: the LEARN→TRY→ESCALATE ladder before any blocker."""
    assert "LEARN→TRY→ESCALATE" in _text(name), f"{name}: no LEARN→TRY→ESCALATE ladder"


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_blocker_contract(name: str) -> None:
    """D4: ESCALATE lands as blockers/<claim>.md, never a bare 'blocked'."""
    text = _text(name)
    assert "blockers/" in text, f"{name}: no blockers/ contract"
    assert "blocker" in text.lower(), f"{name}: blocker protocol not named"


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_trace_echo_rule(name: str) -> None:
    """D5: trace_id echoes into worker-status lines and fact frontmatter."""
    text = _text(name)
    assert "| trace: " in text, f"{name}: no worker-status trace echo"
    assert "trace_id:" in text, f"{name}: no fact-frontmatter trace_id echo"


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_recall_useful_verdict(name: str) -> None:
    """D6: the done line carries the recall_useful verdict."""
    assert "recall_useful:" in _text(name), f"{name}: no recall_useful verdict on the done line"


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_tool_catalog_marker(name: str) -> None:
    """D6: the tool-catalog marker rule (worker_budget toolfirst gate)."""
    assert "tool-catalog:" in _text(name), f"{name}: no tool-catalog marker rule"


@pytest.mark.parametrize("name", PINNED_AGENT_FILES)
def test_no_three_of_two_misphrase(name: str) -> None:
    """D8: the jsvmp vote rule is two-of-three; ban the backwards coinage."""
    text = _text(name)
    assert "three-of-two" not in text, (
        f"{name}: 'three-of-two' misphrase present (actual rule: votes >= 2 "
        f"of three features, jsvmp_triage.py triage())"
    )


def test_web_re_states_two_of_three_rule() -> None:
    """D8 (web-re only): the corrected rule phrasing is present."""
    text = _text("web-re-worker.md")
    assert "two-of-three" in text, "web-re-worker.md: corrected two-of-three vote phrasing missing"
