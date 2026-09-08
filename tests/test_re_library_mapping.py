# -*- coding: utf-8 -*-
"""Real-tree contract for the re-library mapping (single home of placement).

The committed mapping must biject the re-library tree, respect the depth
cap, and agree with every card's frontmatter. The hygiene lint enforces
the same invariants as hard CI failures; these pytest-level pins exist so
the lint cannot drift silently and the mapping cannot rot without a red
suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import comment_hygiene_lint as chl  # noqa: E402

MAPPING_PATH = ROOT / chl.MAPPING_REL


def _rows() -> list[dict]:
    doc = yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8"))
    assert doc["schema"] == chl.MAPPING_SCHEMA
    return doc["cards"]


def test_mapping_pass_is_clean_on_the_real_tree():
    assert chl.mapping_violations(ROOT) == []


def test_mapping_rows_are_unique_and_complete():
    rows = _rows()
    sources = [r["from"] for r in rows]
    assert len(sources) == len(set(sources))
    disk = {p.relative_to(ROOT).as_posix()
            for p in (ROOT / chl.RELIB_REL).rglob("*") if p.is_file()}
    disk.discard(chl.MAPPING_REL)
    declared = {r["from"] for r in rows} | {r["to"] for r in rows}
    assert disk <= declared, f"files outside the mapping: {sorted(disk - declared)}"


def test_mapping_destinations_respect_depth_cap():
    for row in _rows():
        rest = row["to"][len(chl.RELIB_PREFIX):]
        depth = len(Path(rest).parent.parts)
        assert depth <= chl.MAX_DEPTH, row["to"]


def test_every_card_frontmatter_matches_its_row():
    for row in _rows():
        existing = ROOT / row["to"]
        if not existing.is_file():
            existing = ROOT / row["from"]
        if existing.suffix != ".md":
            continue
        text = existing.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{existing.name}: no frontmatter"
        fm = yaml.safe_load(text.split("---\n", 2)[1])
        assert fm["domain"] == row["domain"], existing.name
        assert fm["family"] == row["family"], existing.name
