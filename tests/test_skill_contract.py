# -*- coding: utf-8 -*-
"""SKILL.md contract (#226): the skill file is a machine-checkable contract.

Rules: <400 lines; English-only body (CJK allowed in frontmatter triggers);
no hardcoded instance values (Windows paths / VM IPs) in the body; every
markdown link target exists; the 8 workflow sections appear in order;
no duplicated narrative sections.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
SECTIONS = [
    "Phase 0 Environment Probe",
    "Phase 1 Activate",
    "Phase 2 Dispatch Loop",
    "Phase 3 Verify",
    "Phase 4 Completion Transaction",
    "Phase 5 Delivery",
    "Failure Routing",
    "Operator Boundaries",
]
CJK = re.compile(r"[一-鿿]")
HARDCODED = re.compile(r"[A-Z]:[\\/]|192\.168\.20|/Users/hr|kong-refactor")
NARRATIVE = ["WHY=", "single most-violated", "traces to violating", "case-book"]


def _body() -> str:
    text = SKILL.read_text(encoding="utf-8")
    parts = text.split("---", 2)  # frontmatter | body
    return parts[2] if len(parts) == 3 else ""


def test_skill_md_under_400_lines():
    assert len(SKILL.read_text(encoding="utf-8").splitlines()) < 400


def test_skill_md_body_english_only():
    body = _body()
    assert not CJK.search(body), "CJK characters found in SKILL.md body"


def test_skill_md_no_hardcoded_instance_values():
    body = _body()
    assert not HARDCODED.search(body), "hardcoded path/IP found in SKILL.md body"


def test_skill_md_sections_in_order():
    body = _body()
    positions = [body.find(s) for s in SECTIONS]
    assert all(p >= 0 for p in positions), "missing section(s)"
    assert positions == sorted(positions), "sections out of order"


def test_skill_md_links_resolve():
    body = _body()
    broken = []
    for m in re.finditer(r"\]\(([^)#]+)(?:#[^)]*)?\)", body):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (SKILL.parent / target).exists():
            broken.append(target)
    assert not broken, f"broken links: {broken}"


def test_skill_md_no_narrative_phrases():
    body = _body()
    hits = [w for w in NARRATIVE if w in body]
    assert not hits, f"self-narrative phrases remain: {hits}"
