# -*- coding: utf-8 -*-
"""tests/test_entry_sweep_585.py — #585: the 8 kunglao-* entry scripts share
one __main__ dispatcher.

Adjudicated scope: the FULL 89-file sweep collides with every feature branch
— this PR lands the LIMITED form first: the 8 kunglao-*.py entry scripts.
Contract preserved (#370): the router (kunglao.py) imports main(argv) from
these modules to pass the caller's workspace — the dispatcher only replaces
the `if __name__` boilerplate, never the callable.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY_SCRIPTS = sorted((ROOT / "scripts").glob("kunglao-*.py"))
ENTRY_NAMES = [p.name for p in ENTRY_SCRIPTS]


def test_eight_entries_present():
    assert len(ENTRY_NAMES) == 8, f"expected the 8 entries, got {ENTRY_NAMES}"


def test_entry_module_exists_and_importable():
    sys.path.insert(0, str(ROOT / "scripts"))
    import _entry
    assert hasattr(_entry, "run")


def test_entries_delegate_to_entry():
    for p in ENTRY_SCRIPTS:
        src = p.read_text(encoding="utf-8")
        assert "_entry" in src, f"{p.name} must use the shared dispatcher"


def test_router_import_surface_untouched():
    """#370: the router imports main(argv) from entry modules — the dispatcher
    must not shadow or remove the module-level callable path."""
    for p in ENTRY_SCRIPTS:
        src = p.read_text(encoding="utf-8")
        assert ("def main" in src or "import main" in src
                or "from kunglao_" in src), \
            f"{p.name}: keeps its main-callable (router contract)"
