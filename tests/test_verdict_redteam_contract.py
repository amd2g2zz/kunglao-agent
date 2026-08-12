"""tests/test_verdict_redteam_contract.py -- issue #107 verdict-redteam PQ blind-verify rewrite.

Contract tests for agents/verdict-redteam.md ensuring:
  (a) BLIND invariant is present (never reads verdict-scorer's verdict.json)
  (b) Banned terms from old scope (maliciousness, attribution) are absent
  (c) New PQ coverage + correctness framing is present
  (d) CONFIRMED / REFUTED / DIFF semantics are preserved
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_FILE = ROOT / "agents" / "verdict-redteam.md"


@pytest.fixture
def agent_text() -> str:
    """Load verdict-redteam.md as text."""
    if not AGENT_FILE.exists():
        pytest.skip(f"agent file not found: {AGENT_FILE}")
    return AGENT_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) BLIND invariant: agent must state it does NOT read verdict.json
# ---------------------------------------------------------------------------

class TestBlindInvariant:
    """The agent markdown must encode the maker-checker blind-verify rule:
    it reads raw evidence but NEVER reads verdict-scorer's conclusion."""

    def test_blind_without_reading(self, agent_text: str) -> None:
        """Agent MUST contain 'WITHOUT reading' (case-insensitive)."""
        assert re.search(r"without\s+reading", agent_text, re.IGNORECASE), (
            "verdict-redteam.md must contain 'WITHOUT reading' to express the "
            "BLIND invariant (maker-checker: the checker never reads the maker's conclusion)"
        )

    def test_blind_verdict_json_ref(self, agent_text: str) -> None:
        """Agent MUST reference verdict.json in its BLIND constraint."""
        assert "verdict.json" in agent_text, (
            "verdict-redteam.md must name 'verdict.json' as the forbidden read target "
            "(the maker's conclusion that the blind checker must not see)"
        )

    def test_blind_never_read(self, agent_text: str) -> None:
        """Agent MUST contain 'MUST NOT read' or 'NEVER read'."""
        assert re.search(r"(MUST\s+NOT|NEVER)\s+read", agent_text, re.IGNORECASE), (
            "verdict-redteam.md must contain an explicit 'MUST NOT read' or 'NEVER read' "
            "instruction for the BLIND protocol"
        )


# ---------------------------------------------------------------------------
# (b) Banned terms: old scope vocabulary must be completely absent
# ---------------------------------------------------------------------------

class TestBannedTermsAbsent:
    """Terms from the old 'maliciousness + attribution' scope must not appear
    anywhere in the new verdict-redteam.md contract."""

    BANNED_TERMS = [
        "maliciousness",
        "attribution",
    ]

    @pytest.mark.parametrize("term", BANNED_TERMS)
    def test_no_banned_term(self, agent_text: str, term: str) -> None:
        """No banned term (case-insensitive) may appear in agent markdown."""
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        matches = pattern.findall(agent_text)
        assert len(matches) == 0, (
            f"verdict-redteam.md must not contain '{term}' (old scope term). "
            f"Found {len(matches)} occurrence(s)"
        )


# ---------------------------------------------------------------------------
# (c) New scope: PQ coverage + correctness framing
# ---------------------------------------------------------------------------

class TestPQCoverageFraming:
    """The agent must frame its scope around primary-question coverage and
    correctness, not classification or attribution."""

    def test_references_primary_questions(self, agent_text: str) -> None:
        """Agent MUST reference 'primary_questions' or 'primary questions'."""
        assert re.search(r"primary[_\s-]?question", agent_text, re.IGNORECASE), (
            "verdict-redteam.md must reference 'primary_questions' or 'primary questions' "
            "as the unit of coverage judgment"
        )

    def test_references_coverage(self, agent_text: str) -> None:
        """Agent MUST reference 'coverage' in its scope or output description."""
        assert "coverage" in agent_text.lower(), (
            "verdict-redteam.md must reference 'coverage' as the judgment dimension"
        )

    def test_output_schema_has_coverage_or_overall(self, agent_text: str) -> None:
        """Agent output schema MUST contain a 'coverage' or 'overall' field."""
        assert '"coverage"' in agent_text or '"overall"' in agent_text, (
            "verdict-redteam.md output schema must contain a 'coverage' or 'overall' field"
        )

    def test_references_task_spec(self, agent_text: str) -> None:
        """Agent MUST reference 'task_spec' as an input."""
        assert "task_spec" in agent_text, (
            "verdict-redteam.md must reference 'task_spec' as a primary input"
        )

    def test_references_facts(self, agent_text: str) -> None:
        """Agent MUST reference 'facts/' or 'facts' as evidence input."""
        assert re.search(r"\bfacts\b", agent_text), (
            "verdict-redteam.md must reference 'facts' as evidence input"
        )


# ---------------------------------------------------------------------------
# (d) CONFIRMED / REFUTED / DIFF semantics preserved
# ---------------------------------------------------------------------------

class TestVerdictSemantics:
    """The agent must preserve the established verdict vocabulary."""

    def test_confirmed_present(self, agent_text: str) -> None:
        """Agent MUST mention 'CONFIRMED'."""
        assert "CONFIRMED" in agent_text, (
            "verdict-redteam.md must mention 'CONFIRMED' as a verdict status"
        )

    def test_refuted_present(self, agent_text: str) -> None:
        """Agent MUST mention 'REFUTED'."""
        assert "REFUTED" in agent_text, (
            "verdict-redteam.md must mention 'REFUTED' as a verdict status"
        )

    def test_diff_present(self, agent_text: str) -> None:
        """Agent MUST mention 'DIFF' as a divergence indicator."""
        assert "DIFF" in agent_text, (
            "verdict-redteam.md must mention 'DIFF' as a divergence indicator"
        )


# ---------------------------------------------------------------------------
# (e) Structural: frontmatter and basic hygiene
# ---------------------------------------------------------------------------

class TestStructuralHygiene:
    """Basic structural checks on the agent markdown."""

    def test_has_frontmatter(self, agent_text: str) -> None:
        """Agent file MUST have YAML frontmatter (--- delimited)."""
        assert agent_text.startswith("---"), (
            "verdict-redteam.md must start with YAML frontmatter (--- delimiter)"
        )

    def test_frontmatter_name(self, agent_text: str) -> None:
        """Frontmatter MUST declare name: verdict-redteam."""
        assert re.search(r"^name:\s*verdict-redteam\s*$", agent_text, re.MULTILINE), (
            "verdict-redteam.md frontmatter must declare 'name: verdict-redteam'"
        )

    def test_write_disallowed(self, agent_text: str) -> None:
        """Frontmatter MUST list Write in disallowedTools."""
        assert re.search(r"disallowedTools", agent_text), (
            "verdict-redteam.md must have disallowedTools section"
        )
        # Extract frontmatter block and check Write is disallowed
        fm_match = re.match(r"---\n(.*?)\n---", agent_text, re.DOTALL)
        if fm_match:
            fm = fm_match.group(1)
            assert "- Write" in fm or "- Edit" in fm, (
                "verdict-redteam.md must disallow Write (blind checker returns JSON message, not files)"
            )

    def test_maker_checker_mentioned(self, agent_text: str) -> None:
        """Agent MUST reference maker-checker principle."""
        assert "maker-checker" in agent_text.lower(), (
            "verdict-redteam.md must reference the maker-checker principle"
        )
