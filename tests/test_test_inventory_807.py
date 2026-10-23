# -*- coding: utf-8 -*-
"""tests/test_test_inventory_807.py — the bloat inventory classifier.

Evidence BEFORE deletion (Face 1) is only as good as its classifier.
This file pins the two contract faces the deletion audit depends on:

  1. NO false positives: a symbol referenced by a NON-defining imported
     module (the hooks/session_start.py → compact_continuity
     .consume_stashed_note live-call shape) must never classify dead —
     the 2026-10-23 fix excludes only the symbol's OWN defining module
     from the reference scan, not every imported stem.
  2. NO false negatives: a def-only symbol (zero non-test references)
     still classifies dead.

All fixtures are SYNTHETIC scratch trees (privacy rule; the real suite
is never classified here).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "test_inventory_mod", ROOT / "scripts" / "test_inventory.py")
ti = importlib.util.module_from_spec(_spec)
sys.modules["test_inventory_mod"] = ti  # dataclass _is_type needs the module
_spec.loader.exec_module(ti)


@pytest.fixture
def scratch_tree(tmp_path: Path, monkeypatch) -> Path:
    """A fake repo root: scripts/ producer pair + tests/ consumer file.

    producer_lib defines `def-only_symbol` (dead) and `shared_symbol`
    (dead in producer_lib); producer_user CALLS shared_symbol — the
    live cross-module reference the pre-fix classifier could not see.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts" / "producer_lib.py").write_text(
        "def def_only_symbol(x):\n"
        "    return x\n"
        "\n"
        "\n"
        "def shared_symbol(x):\n"
        "    return x + 1\n",
        encoding="utf-8")
    (tmp_path / "scripts" / "producer_user.py").write_text(
        "from producer_lib import shared_symbol\n"
        "\n"
        "\n"
        "def call_face():\n"
        "    return shared_symbol(1)\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_scratch.py").write_text(
        "import producer_lib\n"
        "import producer_user\n"
        "\n"
        "\n"
        "def test_uses_shared():\n"
        "    assert producer_user.call_face() == 2\n"
        "\n"
        "\n"
        "def test_uses_def_only():\n"
        "    assert producer_lib.def_only_symbol(1) == 1\n",
        encoding="utf-8")
    monkeypatch.setattr(ti, "ROOT", tmp_path)
    ti._prod_ref_words._cache = None
    ti._module_defs._cache = {}
    ti._module_selfref_cache.clear()
    return tmp_path


def _classify(tree: Path) -> dict:
    stats = ti.SuiteStats()
    ti.classify_file(tree / "tests" / "test_scratch.py",
                     "tests/test_scratch.py", stats)
    out = {}
    for cls, items in stats.by_class.items():
        for it in items:
            out[it.name] = cls
    return out


def test_live_cross_module_reference_is_never_dead(scratch_tree) -> None:
    """The fixed false-positive class: shared_symbol has a REAL caller in
    producer_user.py (an imported, non-defining module). Before the fix
    the classifier excluded every imported stem and misread it dead."""
    classes = _classify(scratch_tree)
    assert "test_uses_shared" not in classes.get("dead_code_pin", ())


def test_def_only_symbol_still_classifies_dead(scratch_tree) -> None:
    """No false negatives: def_only_symbol has zero non-test references."""
    classes = _classify(scratch_tree)
    assert classes.get("test_uses_def_only") == "dead_code_pin"


def test_reports_are_describe_only(scratch_tree, tmp_path) -> None:
    """The inventory tool never modifies the tree it describes."""
    before = {p: p.read_bytes() for p in scratch_tree.rglob("*.py")}
    ti._prod_ref_words._cache = None
    ti._prod_ref_words()
    after = {p: p.read_bytes() for p in scratch_tree.rglob("*.py")}
    assert before == after
