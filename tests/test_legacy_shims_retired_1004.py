# -*- coding: utf-8 -*-
"""tests/test_legacy_shims_retired_1004.py — the adapter shims are GONE
(legacy-surface retirement).

`scripts/rollout_ledger.py` and `scripts/reward_settlement.py` were pure
re-export adapters kept only so old bare-name imports kept working. The
no-backcompat ruling retires them: every importer now addresses
``rlvr.ledger`` / ``rlvr.reward`` directly, and this scan pins that the
files and the imports never come back.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

SHIMS = ("rollout_ledger", "reward_settlement")


def _py_files():
    for base in (SCRIPTS, ROOT / "hooks", ROOT / "tests"):
        yield from base.rglob("*.py")


def test_the_shim_files_are_gone() -> None:
    for name in SHIMS:
        assert not (SCRIPTS / f"{name}.py").exists(), (
            f"scripts/{name}.py is a retired re-export shim — import the "
            f"rlvr package module instead")


def test_no_module_imports_a_retired_shim() -> None:
    bad: list[str] = []
    for path in _py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8",
                                            errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in SHIMS:
                    bad.append(f"{path.relative_to(ROOT)}: {name}")
    assert not bad, f"retired shim import(s) remain: {bad}"
