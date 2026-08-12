"""tests/test_verdict_scorer_contract.py — contract tests for verdict-scorer agent (issue #106).

Validates that agents/verdict-scorer.md:
1. Contains the new v11 PQ-coverage JSON schema keys.
2. Does NOT contain any banned out-of-scope terms (maliciousness, attribution, etc.).
3. Has unchanged frontmatter tool lists.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_FILE = ROOT / "agents" / "verdict-scorer.md"

# New v11 schema keys that MUST be present in the spec
REQUIRED_SCHEMA_KEYS = [
    "analysis_verdict",
    "primary_questions",
    "sample_sha256",
    "schema_version",
    "self_audit",
    "evidence_strength",
    "contradictions",
    "unresolved",
    "degraded",
    "complete",
    "correct",
]

# Banned terms from out-of-scope capabilities
BANNED_TERMS = [
    ("maliciousness", False),   # case-insensitive substring
    ("attribution", False),     # case-insensitive substring
    ("admiralty", False),       # case-insensitive substring
    ("diamond", False),         # case-insensitive substring
    ("\\bach\\b", True),        # word-boundary regex (case-insensitive)
    ("classification", False),   # case-insensitive substring
    ("named_actor", False),      # case-insensitive substring
    ("threat actor", False),     # case-insensitive substring (two words)
    ("APT", True),               # word-boundary regex (case-insensitive)
]

# Required frontmatter fields that must remain
REQUIRED_FRONTMATTER = {
    "allowedTools": ["Read", "Grep", "Write", "mcp__sequential-thinking__sequentialthinking"],
}


def _read_agent() -> str:
    return AGENT_FILE.read_text(encoding="utf-8")


def _parse_frontmatter() -> dict:
    text = _read_agent()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            import yaml
            return yaml.safe_load(parts[1]) or {}
    return {}


class TestVerdictScorerSchemaPresence:
    """The new v11 PQ-coverage schema keys MUST be present in the spec."""

    def test_analysis_verdict_key_present(self):
        text = _read_agent()
        assert "analysis_verdict" in text, "analysis_verdict key missing from verdict-scorer.md"

    def test_primary_questions_key_present(self):
        text = _read_agent()
        assert "primary_questions" in text, "primary_questions key missing from verdict-scorer.md"

    def test_schema_version_present(self):
        text = _read_agent()
        assert "schema_version" in text, "schema_version missing from verdict-scorer.md"

    def test_self_audit_key_present(self):
        text = _read_agent()
        assert "self_audit" in text, "self_audit key missing from verdict-scorer.md"

    def test_evidence_strength_present(self):
        text = _read_agent()
        assert "evidence_strength" in text, "evidence_strength missing from verdict-scorer.md"

    def test_contradictions_key_present(self):
        text = _read_agent()
        assert "contradictions" in text, "contradictions key missing from verdict-scorer.md"

    def test_unresolved_key_present(self):
        text = _read_agent()
        assert "unresolved" in text, "unresolved key missing from verdict-scorer.md"

    def test_degraded_key_present(self):
        text = _read_agent()
        assert "degraded" in text, "degraded key missing from verdict-scorer.md"

    def test_complete_key_present(self):
        text = _read_agent()
        assert '"complete"' in text or "'complete'" in text, "complete key missing from verdict-scorer.md"

    def test_correct_key_present(self):
        text = _read_agent()
        assert '"correct"' in text or "'correct'" in text, "correct key missing from verdict-scorer.md"


class TestVerdictScorerBannedTermsAbsent:
    """Out-of-scope terms MUST NOT appear in the spec."""

    @staticmethod
    def _check_banned_term(text: str, term: str, is_regex: bool) -> tuple[str, list[str]]:
        flags = re.IGNORECASE
        if is_regex:
            matches = re.findall(term, text, flags)
        else:
            pattern = re.compile(re.escape(term), flags)
            matches = pattern.findall(text)
        return term, matches

    def test_no_maliciousness(self):
        term, matches = self._check_banned_term(_read_agent(), "maliciousness", False)
        assert not matches, f"banned term '{term}' found {len(matches)} times in verdict-scorer.md"

    def test_no_attribution(self):
        term, matches = self._check_banned_term(_read_agent(), "attribution", False)
        assert not matches, f"banned term '{term}' found {len(matches)} times in verdict-scorer.md"

    def test_no_admiralty(self):
        term, matches = self._check_banned_term(_read_agent(), "admiralty", False)
        assert not matches, f"banned term '{term}' found {len(matches)} times in verdict-scorer.md"

    def test_no_diamond(self):
        term, matches = self._check_banned_term(_read_agent(), "diamond", False)
        assert not matches, f"banned term '{term}' found {len(matches)} times in verdict-scorer.md"

    def test_no_ach(self):
        term, matches = self._check_banned_term(_read_agent(), "\\bach\\b", True)
        assert not matches, f"banned term 'ach' found {len(matches)} times in verdict-scorer.md"

    def test_no_classification(self):
        term, matches = self._check_banned_term(_read_agent(), "classification", False)
        assert not matches, f"banned term '{term}' found {len(matches)} times in verdict-scorer.md"

    def test_no_named_actor(self):
        term, matches = self._check_banned_term(_read_agent(), "named_actor", False)
        assert not matches, f"banned term '{term}' found {len(matches)} times in verdict-scorer.md"

    def test_no_threat_actor(self):
        term, matches = self._check_banned_term(_read_agent(), "threat actor", False)
        assert not matches, f"banned term '{term}' found {len(matches)} times in verdict-scorer.md"

    def test_no_apt(self):
        term, matches = self._check_banned_term(_read_agent(), "APT", True)
        assert not matches, f"banned term 'APT' found {len(matches)} times in verdict-scorer.md"


class TestVerdictScorerFrontmatterUnchanged:
    """Frontmatter tool lists MUST remain unchanged."""

    def test_allowed_tools_unchanged(self):
        fm = _parse_frontmatter()
        allowed = fm.get("allowedTools", [])
        for tool in REQUIRED_FRONTMATTER["allowedTools"]:
            assert tool in allowed, f"allowedTool '{tool}' missing from frontmatter allowedTools (got {allowed})"

    def test_disallowed_tools_present(self):
        text = _read_agent()
        for tool in ["Edit", "NotebookEdit", "Bash", "WebFetch", "WebSearch"]:
            assert tool in text, f"disallowedTool '{tool}' missing from verdict-scorer.md frontmatter"

    def test_isolation_none(self):
        text = _read_agent()
        assert "isolation: none" in text, "isolation: none missing from verdict-scorer.md frontmatter"


class TestVerdictScorerProvenance:
    """Provenance note MUST reference scope boundary correction."""

    def test_provenance_mentions_scope_boundary(self):
        text = _read_agent()
        assert "scope boundary" in text.lower() or "scope-boundary" in text.lower(), \
            "provenance should mention scope boundary correction"


class TestVerdictScorerPureLocal:
    """verdict-scorer MUST be pure-local (no external API calls)."""

    def test_no_external_api_calls(self):
        text = _read_agent()
        # Check the hard constraints / anti-patterns section for "no external API" language
        assert re.search(r"no external api|no.*external.*call|pure local|local only",
                         text, re.IGNORECASE), \
            "spec should state no external API calls are made"
