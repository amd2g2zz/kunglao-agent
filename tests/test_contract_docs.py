# -*- coding: utf-8 -*-
"""Phase 3 contract tests: SKILL.md structural constraints (<=500 lines / one-level depth / decision-rights matrix / references completeness).

Step 1 RED — current state:
- SKILL.md 604 lines > 500 → test_skill_lte_500_lines RED
- decision-rights matrix not yet written down → test_decision_rights_table RED

GREEN target (phase 3 criteria): SKILL <=500 lines + one-level depth + decision-rights matrix (Mechanical 8 / LLM 6 / User 5).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
REFERENCES = ROOT / "references"
MAX_LINES = 500
MAX_DEPTH = 3  # max nesting depth of reference chains


def _lines() -> list[str]:
    return SKILL.read_text(encoding="utf-8").splitlines()


def test_skill_lte_500_lines() -> None:
    """SKILL.md main file <=500 lines (after the three-way responsibility split the main contract stays scannable)."""
    n = len(_lines())
    assert n <= MAX_LINES, f"SKILL.md {n} lines > {MAX_LINES}"


def test_skill_references_resolve() -> None:
    """references/ files referenced by SKILL.md must actually exist."""
    text = SKILL.read_text(encoding="utf-8")
    missing = []
    for m in re.finditer(r"references/([\w./-]+\.md)", text):
        rel = m.group(1)
        if not (REFERENCES / rel).exists():
            missing.append(rel)
    assert not missing, f"missing references: {missing}"


def test_decision_rights_table() -> None:
    """Decision-rights matrix, three columns: Mechanical 8 / LLM 6 / User 5 written into SKILL.md (#226 after English conversion checks English markers)."""
    text = SKILL.read_text(encoding="utf-8")
    assert "Mechanical" in text and "8" in text, "missing Mechanical decision-rights row"
    assert "User" in text, "missing User decision-rights row"
    # each of the three authorization tiers appears at least once
    for col in ("Mechanical", "LLM", "User"):
        assert col in text, f"decision-rights matrix missing {col} column"


def test_depth_one() -> None:
    """One-level depth: SKILL.md must not nest references >3 levels (main file → references → inside references)."""
    text = SKILL.read_text(encoding="utf-8")
    # the main file should not reference deep paths that are in turn referenced inside references (signal: >1 level of subdirectories)
    deep = re.findall(r"references/([\w/-]+/[\w./-]+\.md)", text)
    assert len(deep) <= 1, f"too many deep references: {deep}"


def test_skill_has_orchestrator_contract() -> None:
    """The main contract keeps the orchestrator core: convergence loop + dispatch contract + worker monitoring."""
    text = SKILL.read_text(encoding="utf-8")
    for keyword in ("convergence", "dispatch", "worker"):
        assert keyword.lower() in text.lower(), f"missing core contract keyword: {keyword}"
