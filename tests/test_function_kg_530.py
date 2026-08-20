# -*- coding: utf-8 -*-
"""tests/test_function_kg_530.py — issue #530 disposition lock: function_kg removed.

function_kg.py had zero runtime consumers (only its own dedicated test file,
the scripts/README.md catalog row, and the generated tools/_INDEX.ext.yaml
enumeration). Deleted per the #395 runtime-zero-consumer precedent.

These anchors prevent silent re-introduction without a named runtime consumer.
"""
from __future__ import annotations

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_function_kg_module_does_not_exist():
    """RED contract: the module is gone from every code directory."""
    candidates = (
        list((ROOT / "tools").rglob("function_kg.py"))
        + list((ROOT / "scripts").rglob("function_kg.py"))
        + list((ROOT / "hooks").rglob("function_kg.py"))
    )
    assert candidates == [], (
        f"function_kg.py still present at {candidates}; "
        "delete per #530 decision (rationale: no runtime consumer, #395 precedent)"
    )


def test_dedicated_test_file_removed():
    """The orphan's exclusive test suite goes with it."""
    assert not (ROOT / "tests" / "test_orchestration_function_kg.py").exists(), (
        "tests/test_orchestration_function_kg.py exclusively tested the deleted "
        "module; keep dead tests out of the suite"
    )


def test_scripts_readme_catalog_row_removed():
    """scripts/README.md must not catalog a nonexistent script (ghost row)."""
    text = (ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
    assert "function_kg.py" not in text, (
        "scripts/README.md still catalogs function_kg.py after deletion — "
        "drop the row (test_declaration_scan.py ghosts lock)"
    )


def test_ext_index_no_longer_enumerates_function_kg():
    """tools/_INDEX.ext.yaml must not point at the deleted source."""
    ext_index = ROOT / "tools" / "_INDEX.ext.yaml"
    if not ext_index.exists():
        return  # absence trivially satisfies the anchor
    data = yaml.safe_load(ext_index.read_text(encoding="utf-8")) or {}
    names = [e.get("name") for e in data.get("ext") or []]
    assert "function_kg" not in names, (
        "tools/_INDEX.ext.yaml still enumerates function_kg — regenerate via "
        "`python tools/ext-scan.py` after the module deletion"
    )
