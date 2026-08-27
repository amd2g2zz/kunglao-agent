# -*- coding: utf-8 -*-
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
# #790 governance: scorer is a PURE READ-SIDE judge (docs/agent-tooling-matrix.md)
# — Write removed; Bash/WEB/mcp analysis families explicitly denied.
REQUIRED_FRONTMATTER = {
    "allowedTools": ["Read", "Glob", "Grep",
                     "mcp__sequential-thinking__sequentialthinking"],
}

# Keys that only appear in quotes in the spec (e.g. JSON keys) — matched
# literally (with quotes) to avoid matching prose that merely mentions them.
QUOTED_SCHEMA_KEYS = {"complete", "correct"}


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

    def test_all_schema_keys_present(self):
        text = _read_agent()
        for key in REQUIRED_SCHEMA_KEYS:
            if key in QUOTED_SCHEMA_KEYS:
                assert f'"{key}"' in text or f"'{key}'" in text, \
                    f"{key} key missing from verdict-scorer.md"
            else:
                assert key in text, f"{key} key missing from verdict-scorer.md"


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

    def test_no_banned_terms(self):
        text = _read_agent()
        for term, is_regex in BANNED_TERMS:
            _, matches = self._check_banned_term(text, term, is_regex)
            assert not matches, \
                f"banned term '{term}' found {len(matches)} times in verdict-scorer.md"


class TestVerdictScorerFrontmatterUnchanged:
    """Frontmatter tool lists MUST remain unchanged."""

    def test_allowed_tools_unchanged(self):
        fm = _parse_frontmatter()
        allowed = fm.get("allowedTools", [])
        for tool in REQUIRED_FRONTMATTER["allowedTools"]:
            assert tool in allowed, f"allowedTool '{tool}' missing from frontmatter allowedTools (got {allowed})"

    def test_disallowed_tools_present(self):
        text = _read_agent()
        for tool in ["Edit", "NotebookEdit", "Bash", "WebFetch", "WebSearch",
                     "Write"]:
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
