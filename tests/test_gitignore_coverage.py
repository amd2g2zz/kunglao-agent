# -*- coding: utf-8 -*-
"""tests/test_gitignore_coverage.py — verify .gitignore covers all required exclusions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITIGNORE = ROOT / ".gitignore"

REQUIRED_PATTERNS = [
    "**/bins/",
    ".claude/settings.json",
    ".claude/hooks/",
    ".claude/skills/",
    "analysis_space/",
    ".venv/",
    "__pycache__/",
    ".review-gate/",
    "progress.txt",
    "*.dmp",
    "*.raw",
    "*.vmem",
    ".pytest_cache/",
]


def test_gitignore_exists():
    assert GITIGNORE.exists(), ".gitignore missing"


def test_gitignore_covers_required_patterns():
    content = GITIGNORE.read_text(encoding="utf-8")
    missing = [p for p in REQUIRED_PATTERNS if p not in content]
    assert not missing, f".gitignore missing required patterns: {missing}"
