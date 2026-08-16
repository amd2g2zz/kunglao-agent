# -*- coding: utf-8 -*-
"""tests/test_kunglao_redteam_verdict_layer.py -- issue #240 verifier consolidation.

Contract tests for agents/kunglao-redteam.md's verdict-layer mode, which absorbs
verdict-redteam (deleted 2026-08-13). Ensures the unified agent still carries:
  (a) BLIND invariant in BOTH layers (never reads the maker's conclusion:
      the claim's fact file / evidence/verdict.json)
  (b) Verdict-layer input pattern (--target <evidence-dir>, evidence/*.json,
      task_spec primary_questions, facts base)
  (c) PQ coverage + correctness framing (verdict-redteam issue #107 contract)
  (d) Admiralty+ACH+Diamond attribution method (ported on consolidation)
  (e) CONFIRMED / REFUTED / UNVERIFIED-WITH-GAP / DIFF semantics
  (f) Output: JSON message OR runs/verify-redteam-<target>.md
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_FILE = ROOT / "agents" / "kunglao-redteam.md"


@pytest.fixture
def agent_text() -> str:
    """Load kunglao-redteam.md as text."""
    if not AGENT_FILE.exists():
        pytest.skip(f"agent file not found: {AGENT_FILE}")
    return AGENT_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) BLIND invariant: both layers must state they never read the maker's conclusion
# ---------------------------------------------------------------------------

class TestBlindInvariant:
    """The agent markdown must encode the maker-checker blind-verify rule in
    both modes: claim layer (never read the target fact) and verdict layer
    (never read verdict.json)."""

    def test_blind_without_reading(self, agent_text: str) -> None:
        """Agent MUST express that it derives WITHOUT reading the conclusion
        ('WITHOUT reading' or 'never read the conclusion')."""
        assert re.search(r"(without\s+reading|never\s+read)", agent_text, re.IGNORECASE), (
            "kunglao-redteam.md must express the BLIND invariant "
            "(maker-checker: the checker never reads the maker's conclusion)"
        )

    def test_claim_layer_blind_never_read(self, agent_text: str) -> None:
        """Claim layer MUST forbid reading the target's fact file."""
        assert re.search(r"(MUST\s+NOT|NEVER)\s+read", agent_text, re.IGNORECASE), (
            "kunglao-redteam.md must contain an explicit 'MUST NOT read' or 'NEVER read' "
            "instruction for the BLIND protocol"
        )

    def test_verdict_layer_blind_verdict_json(self, agent_text: str) -> None:
        """Verdict layer MUST name verdict.json as the forbidden read target."""
        assert "verdict.json" in agent_text, (
            "kunglao-redteam.md must name 'verdict.json' as the forbidden read target "
            "in the verdict-layer mode (the maker's conclusion that the blind checker must not see)"
        )


# ---------------------------------------------------------------------------
# (b) Verdict-layer input pattern
# ---------------------------------------------------------------------------

class TestVerdictLayerInputs:
    """The unified agent must expose the verdict-layer --target mode and its
    read-only inputs (evidence/*.json, task_spec, facts)."""

    def test_target_modes(self, agent_text: str) -> None:
        """Agent MUST declare the --target claim|<evidence-dir> input modes."""
        assert "--target" in agent_text, (
            "kunglao-redteam.md must declare the --target input parameter "
            "(claim layer vs verdict layer)"
        )

    def test_evidence_json_input(self, agent_text: str) -> None:
        """Verdict layer MUST read evidence/*.json as its raw evidence input."""
        assert re.search(r"evidence/\*\.json", agent_text), (
            "kunglao-redteam.md verdict layer must read evidence/*.json"
        )

    def test_references_task_spec(self, agent_text: str) -> None:
        """Verdict layer MUST reference 'task_spec' as an input."""
        assert "task_spec" in agent_text, (
            "kunglao-redteam.md must reference 'task_spec' as a verdict-layer input"
        )

    def test_references_facts(self, agent_text: str) -> None:
        """Verdict layer MUST reference 'facts/' or 'facts' as evidence input."""
        assert re.search(r"\bfacts\b", agent_text), (
            "kunglao-redteam.md must reference 'facts' as evidence input"
        )


# ---------------------------------------------------------------------------
# (c) PQ coverage + correctness framing (verdict-redteam issue #107 contract)
# ---------------------------------------------------------------------------

class TestPQCoverageFraming:
    """The verdict layer must keep the primary-question coverage + correctness
    judgment unit carried over from verdict-redteam."""

    def test_references_primary_questions(self, agent_text: str) -> None:
        """Verdict layer MUST reference 'primary_questions' or 'primary questions'."""
        assert re.search(r"primary[_\s-]?question", agent_text, re.IGNORECASE), (
            "kunglao-redteam.md verdict layer must reference 'primary_questions' "
            "as the unit of coverage judgment"
        )

    def test_references_coverage(self, agent_text: str) -> None:
        """Verdict layer MUST reference 'coverage' in its scope or output description."""
        assert "coverage" in agent_text.lower(), (
            "kunglao-redteam.md must reference 'coverage' as the judgment dimension"
        )

    def test_output_schema_has_coverage_or_overall(self, agent_text: str) -> None:
        """Verdict-layer output schema MUST contain a 'coverage' or 'overall' field."""
        assert '"coverage"' in agent_text or '"overall"' in agent_text, (
            "kunglao-redteam.md verdict-layer output schema must contain a "
            "'coverage' or 'overall' field"
        )


# ---------------------------------------------------------------------------
# (d) Admiralty + ACH + Diamond attribution method (ported on consolidation)
# ---------------------------------------------------------------------------

class TestAdmiraltyAchDiamond:
    """The verdict layer must carry the Admiralty+ACH+Diamond attribution
    method ported from verdict-redteam on consolidation (issue #240)."""

    def test_admiralty_present(self, agent_text: str) -> None:
        assert "Admiralty" in agent_text, (
            "kunglao-redteam.md verdict layer must reference Admiralty source credibility"
        )

    def test_ach_present(self, agent_text: str) -> None:
        assert re.search(r"\bACH\b", agent_text), (
            "kunglao-redteam.md verdict layer must reference the ACH hypothesis matrix"
        )

    def test_diamond_present(self, agent_text: str) -> None:
        assert "Diamond" in agent_text, (
            "kunglao-redteam.md verdict layer must reference the Diamond model"
        )

    def test_named_actor_gate(self, agent_text: str) -> None:
        """S5 named-actor gate must survive the consolidation."""
        assert "named-actor" in agent_text or "named_actor" in agent_text, (
            "kunglao-redteam.md verdict layer must keep the S5 named-actor gate"
        )


# ---------------------------------------------------------------------------
# (e) CONFIRMED / REFUTED / UNVERIFIED-WITH-GAP / DIFF semantics preserved
# ---------------------------------------------------------------------------

class TestVerdictSemantics:
    """The unified agent must preserve the established verdict vocabulary."""

    def test_confirmed_present(self, agent_text: str) -> None:
        assert "CONFIRMED" in agent_text

    def test_refuted_present(self, agent_text: str) -> None:
        assert "REFUTED" in agent_text

    def test_unverified_with_gap_present(self, agent_text: str) -> None:
        assert "UNVERIFIED-WITH-GAP" in agent_text

    def test_diff_present(self, agent_text: str) -> None:
        assert "DIFF" in agent_text


# ---------------------------------------------------------------------------
# (f) Output: JSON message OR runs/verify-redteam-<target>.md
# ---------------------------------------------------------------------------

class TestVerdictLayerOutput:
    """The verdict layer must declare both accepted delivery channels."""

    def test_json_message_output(self, agent_text: str) -> None:
        assert "JSON message" in agent_text or '"redteam_verdict"' in agent_text, (
            "kunglao-redteam.md verdict layer must support the JSON message output"
        )

    def test_run_file_output(self, agent_text: str) -> None:
        assert "verify-redteam-" in agent_text, (
            "kunglao-redteam.md must support runs/verify-redteam-<target>.md output"
        )


# ---------------------------------------------------------------------------
# (g) Structural: frontmatter and basic hygiene
# ---------------------------------------------------------------------------

class TestStructuralHygiene:
    """Basic structural checks on the agent markdown."""

    def test_has_frontmatter(self, agent_text: str) -> None:
        assert agent_text.startswith("---"), (
            "kunglao-redteam.md must start with YAML frontmatter (--- delimiter)"
        )

    def test_frontmatter_name(self, agent_text: str) -> None:
        assert re.search(r"^name:\s*kunglao-redteam\s*$", agent_text, re.MULTILINE), (
            "kunglao-redteam.md frontmatter must declare 'name: kunglao-redteam'"
        )

    def test_maker_checker_mentioned(self, agent_text: str) -> None:
        assert "maker-checker" in agent_text.lower(), (
            "kunglao-redteam.md must reference the maker-checker principle"
        )
