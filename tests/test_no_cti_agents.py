"""RED test for issue #105 — B4-1 remove CTI agents.

Asserts that banned agent names are absent from the codebase.
The banned names are defined inline to keep this file self-contained.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"
REFERENCES_DIR = ROOT / "references"
RELEASE_MANIFEST = ROOT / "release-manifest.yaml"

# Banned agent identifiers — what we are removing
_BANNED = ["cti-correlator", "shodan-host"]

EXCLUDE_DIRS = {"openspec", ".venv", "__pycache__", ".git", "node_modules"}

# This file itself references the banned tokens in docstrings/constants
_SELF = Path(__file__).resolve().relative_to(ROOT)


class TestCtiAgentsRemoved:
    """B4-1: CTI agent files must not exist."""

    def test_cti_correlator_md_absent(self) -> None:
        assert not (AGENTS_DIR / "cti-correlator.md").exists(), (
            "agents/cti-correlator.md must be deleted (CTI agent, not RE)"
        )

    def test_shodan_host_md_absent(self) -> None:
        assert not (AGENTS_DIR / "shodan-host.md").exists(), (
            "agents/shodan-host.md must be deleted (CTI agent, not RE)"
        )


class TestNoCtiReferences:
    """B4-1: no references to banned tokens in scoped files."""

    @pytest.mark.parametrize("token", _BANNED)
    def test_no_references_in_agents(self, token: str) -> None:
        """No .md files under agents/ should mention banned tokens."""
        hits: list[str] = []
        for f in sorted(AGENTS_DIR.glob("*.md")):
            if any(exc in f.parts for exc in EXCLUDE_DIRS):
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            if token in text:
                hits.append(str(f.relative_to(ROOT)))
        assert not hits, f"Found '{token}' in agents/: {hits}"

    @pytest.mark.parametrize("token", _BANNED)
    def test_no_references_in_references(self, token: str) -> None:
        """No .md files under references/ should mention banned tokens."""
        hits: list[str] = []
        for f in sorted(REFERENCES_DIR.glob("**/*.md")):
            if any(exc in f.parts for exc in EXCLUDE_DIRS):
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            if token in text:
                hits.append(str(f.relative_to(ROOT)))
        assert not hits, f"Found '{token}' in references/: {hits}"

    @pytest.mark.parametrize("token", _BANNED)
    def test_no_references_in_release_manifest(self, token: str) -> None:
        """release-manifest.yaml should not mention banned tokens."""
        text = RELEASE_MANIFEST.read_text(encoding="utf-8", errors="ignore")
        assert token not in text, f"Found '{token}' in release-manifest.yaml"

    @pytest.mark.parametrize("token", _BANNED)
    def test_no_references_in_other_tests(self, token: str) -> None:
        """Other test files should not assert presence of banned agent names.
        This test file is excluded from the scan.
        """
        tests_dir = ROOT / "tests"
        hits: list[str] = []
        for f in sorted(tests_dir.glob("**/*.py")):
            rel = f.relative_to(ROOT)
            if any(exc in f.parts for exc in EXCLUDE_DIRS):
                continue
            # Skip this file itself
            if str(rel) == str(_SELF):
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                # Skip comment/docstring lines
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if token in line:
                    hits.append(f"{rel}:{i}")
        assert not hits, f"Found '{token}' in test code: {hits}"
