# -*- coding: utf-8 -*-
"""Fact schema_rev (#536 work item V-2).

The schema authority lives in the skill package's active
templates/fact-frontmatter.md. lint_facts output must carry the active
schema_rev so consumers can detect silent drift when a fact file is opened
against an older or newer skill.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

TEMPLATE = ROOT / "templates" / "fact-frontmatter.md"
LINT = ROOT / "scripts" / "lint_facts.py"


def test_fact_template_has_schema_rev() -> None:
    assert TEMPLATE.exists(), "templates/fact-frontmatter.md missing"
    text = TEMPLATE.read_text(encoding="utf-8")
    assert re.search(r"`schema_rev:\s*2`", text), (
        "fact template missing the schema_rev pin row — facts will silently "
        "drift when the schema evolves"
    )
    # the example frontmatter carries the pin too
    assert re.search(r"^schema_rev:\s*2$", text, re.MULTILINE), (
        "complete-example frontmatter lacks schema_rev: 2"
    )


def test_lint_active_schema_rev_constant_exists() -> None:
    import lint_facts
    assert isinstance(lint_facts.ACTIVE_SCHEMA_REV, int)
    assert lint_facts.ACTIVE_SCHEMA_REV >= 1


def test_lint_facts_json_output_carries_schema_rev(tmp_path: Path) -> None:
    """Machine output must include active_schema_rev for drift detection."""
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir()
    result = subprocess.run(
        [sys.executable, str(LINT), "--json", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    data = json.loads(result.stdout)
    assert data["active_schema_rev"] >= 1, data


def test_lint_facts_text_output_carries_schema_rev(tmp_path: Path) -> None:
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir()
    result = subprocess.run(
        [sys.executable, str(LINT), str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    combined = result.stdout + result.stderr
    assert "active_schema_rev" in combined, (
        f"lint_facts text output missing schema_rev (cannot detect drift): {combined!r}"
    )
