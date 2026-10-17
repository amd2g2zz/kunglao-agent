# -*- coding: utf-8 -*-
"""tests/test_rlvr_facade_756.py — the package facade's contract (issue 756).

The rlvr ``__init__`` is submodule-direct: one ``from . import`` line
per submodule, and ``__all__`` enumerating exactly the submodule names
with at least one external consumer. The facade's alias layer once
carried 171 zero-consumer names (the audit's decorative surface) —
these pins keep the drift a test failure, as the contract claims.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


@pytest.fixture(autouse=True)
def _facade_path(monkeypatch):
    """Scripts+root on sys.path for THIS test only — a leaked insert
    reorders resolution for every later module in the worker (the
    syspath-hygiene card's exact shadow: test_env_manifest's bare-name
    imports died on a partial heartbeat_touch)."""
    monkeypatch.syspath_prepend(str(ROOT))
    monkeypatch.syspath_prepend(str(SCRIPTS))


def _external_consumers() -> dict[str, set[str]]:
    """{name → consuming files} for every ``from rlvr import X`` /
    ``rlvr.X`` reference outside the package itself (AST walk —
    parenthesized and aliased imports included)."""
    consumers: dict[str, set[str]] = {}
    files = [f for f in list(Path(SCRIPTS).rglob("*.py"))
             + list((ROOT / "hooks").rglob("*.py"))
             + list((ROOT / "tests").rglob("*.py"))
             if not str(f).startswith(str(SCRIPTS / "rlvr" / ""))]
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8",
                                         errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom) and node.module == "rlvr"
                    and node.level == 0):
                for a in node.names:
                    consumers.setdefault(a.name, set()).add(str(f))
            elif (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "rlvr"):
                consumers.setdefault(node.attr, set()).add(str(f))
    return consumers


def test_facade_all_names_resolve():
    import rlvr
    assert rlvr.__all__, "the facade exports nothing"
    for name in rlvr.__all__:
        assert hasattr(rlvr, name), f"__all__ name {name!r} does not resolve"


def test_facade_exports_exactly_the_consumed_names():
    """Bidirectional: ``__all__`` equals the externally-consumed
    submodule-name set — no decorative exports, no missing exports
    (both directions are the contract; a one-sided pin let the first
    cut of this facade ship 12 names short)."""
    import rlvr
    consumers = _external_consumers()
    submods = {f.stem for f in (SCRIPTS / "rlvr").glob("*.py")
               if f.stem != "__init__"}
    true_set = {n for n in consumers if n in submods}
    exported = set(rlvr.__all__)
    missing = sorted(true_set - exported)
    extra = sorted(exported - true_set)
    assert not missing, (
        f"consumed submodule names missing from rlvr.__all__: {missing}")
    assert not extra, (
        "decorative surface regrown — names in rlvr.__all__ with zero "
        f"external consumers: {extra}")


def test_facade_all_names_are_submodules():
    """The facade is submodule-direct: every export is the package's
    own submodule (the 171-name alias layer is gone for good)."""
    import rlvr
    for name in rlvr.__all__:
        mod = importlib.import_module(f"rlvr.{name}")
        assert mod is not None


def test_every_submodule_has_its_package_line():
    """A bare ``import rlvr`` must make every submodule addressable —
    each file under scripts/rlvr/ (except private helpers) carries its
    ``from . import`` line."""
    import rlvr
    pkg_dir = SCRIPTS / "rlvr"
    private = {"__init__.py"}
    for f in sorted(pkg_dir.glob("*.py")):
        if f.name in private:
            continue
        name = f.stem
        assert hasattr(rlvr, name), (
            f"submodule {name!r} has no 'from . import {name}' package "
            "line — a bare 'import rlvr' cannot reach it")
