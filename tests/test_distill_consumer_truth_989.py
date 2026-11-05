# -*- coding: utf-8 -*-
"""tests/test_distill_consumer_truth_989.py — the distill surface's
declared-vs-consumed contract (issue 989).

The audit found two duplicate faces with zero production consumers: the
top-level spine module and the package lifecycle ladder. The
no-backcompat policy retires both. This file pins the surviving truth:

  1. every live distill module keeps at least one PRODUCTION consumer
     (scripts/ outside the rlvr package, hooks/, tools/, experiments/)
     at a pinned anchor — an import in a test keeps a module collectible,
     not alive;
  2. the retired modules stay gone: no file, no facade export, no
     README row, no Python import anywhere;
  3. the README catalog rows for the distill family are unique and
     carry no false producer claim.
"""
from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SELF = Path(__file__).resolve()

#: The rlvr submodules newer code reaches through ``from rlvr import X``.
RLVR_SUBMODULES = frozenset({
    "distill_dgate",
    "distill_rollout",
    "distill_score",
    "playbook_distill",
    "family_playbook",
})

#: Live module -> the production files that must keep consuming it.
#: ``hooks/round_closure.py`` fires the online engine at round close;
#: ``tools/auxiliary/hybrid_distill.py`` is the collection kernel that
#: imports the four rlvr faces; ``scripts/eval_loop_runner.py`` calls the
#: terminal playbook distillation.
LIVE_CONSUMERS: dict[str, set[str]] = {
    "online_distill": {
        "hooks/round_closure.py",
        "scripts/script_harvest.py",
        "scripts/action_space.py",
    },
    "distill_schema": {
        "tools/auxiliary/hybrid_distill.py",
        "scripts/rlvr/distill_score.py",
    },
    "distill_dgate": {"tools/auxiliary/hybrid_distill.py"},
    "distill_rollout": {"tools/auxiliary/hybrid_distill.py"},
    "distill_score": {"tools/auxiliary/hybrid_distill.py"},
    "playbook_distill": {"scripts/eval_loop_runner.py"},
    "family_playbook": {"scripts/eval_loop_runner.py"},
}

PRODUCTION_ROOTS = ("scripts", "hooks", "tools", "experiments")

RETIRED = {
    "scripts/distill_spine.py": (
        "duplicate landing face (online_distill.land_candidate is the "
        "live one) and zero production consumers"),
    "scripts/rlvr/distill_lifecycle.py": (
        "zero imports; the removal filter it fed lives in distill_score"),
}

#: README row names owned by the distill family (top-level catalog rows).
DISTILL_ROW_NAMES = frozenset({
    "online_distill.py",
    "distill_schema.py",
    "distill_spine.py",
    "distill_lifecycle.py",
})


@lru_cache(maxsize=None)
def _python_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root_rel in PRODUCTION_ROOTS + ("tests", "devkit", "evals"):
        root = ROOT / root_rel
        if root.is_dir():
            files.extend(p for p in root.rglob("*.py")
                         if "__pycache__" not in p.parts)
    return tuple(sorted(files))


def _references_module(tree: ast.AST, name: str, *,
                       submodule: bool) -> bool:
    """True when the AST references ``name`` (a top-level script module,
    or an ``rlvr.<name>`` submodule) — every import shape included."""
    want = f"rlvr.{name}" if submodule else name
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == want or alias.name.startswith(want + "."):
                    return True
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            if submodule:
                if module == "rlvr" and any(
                        alias.name == name for alias in node.names):
                    return True
                if module == want or module.startswith(want + "."):
                    return True
            elif module == name or module.startswith(name + "."):
                return True
        elif (isinstance(node, ast.Attribute)
              and isinstance(node.value, ast.Name)
              and node.value.id == "rlvr" and node.attr == name):
            return True
    return False


@lru_cache(maxsize=None)
def _production_consumers(name: str, *, submodule: bool) -> frozenset[str]:
    """Production files importing ``name``. The owning module file never
    counts; the rlvr package is the declaration site, so its own files
    never count as consumers of a package submodule."""
    own = (f"scripts/rlvr/{name}.py" if submodule
           else f"scripts/{name}.py")
    out: set[str] = set()
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == own:
            continue
        if submodule and rel.startswith("scripts/rlvr/"):
            continue
        if rel.startswith("tests/") or rel.startswith("devkit/") \
                or rel.startswith("evals/"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if name not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        if _references_module(tree, name, submodule=submodule):
            out.add(rel)
    return frozenset(out)


@pytest.mark.parametrize("name", sorted(LIVE_CONSUMERS))
def test_live_distill_module_keeps_its_production_consumers(name: str) -> None:
    consumers = _production_consumers(name,
                                      submodule=name in RLVR_SUBMODULES)
    assert consumers, (
        f"{name}: no production consumer — a distill module pinned only by "
        "tests is declared but not live; wire a real caller or retire it")
    missing = LIVE_CONSUMERS[name] - consumers
    assert not missing, (
        f"{name}: pinned consumer(s) no longer reference the module: "
        f"{sorted(missing)} — re-pin the truth or retire the module")


def test_hybrid_distill_is_a_registered_dispatch_surface() -> None:
    """The collection kernel is agent-dispatched, so its consumer is the
    execution registry row — not a static import."""
    registry = yaml.safe_load(
        (ROOT / "tools" / "_INDEX.yaml").read_text(encoding="utf-8"))
    rows = {row["name"]: row for row in registry["tools"]}
    assert "hybrid-distill" in rows
    row = rows["hybrid-distill"]
    assert row["category"] == "auxiliary"
    assert row["capability"] == "aux:distill-engine"
    assert "tools/auxiliary/hybrid_distill.py" in row["input_output"]["input"]


@pytest.mark.parametrize("rel", sorted(RETIRED))
def test_retired_module_is_gone(rel: str) -> None:
    assert not (ROOT / rel).exists(), (
        f"{rel} is retired ({RETIRED[rel]}) — the no-backcompat policy "
        "keeps it deleted")


def test_retired_lifecycle_left_the_facade() -> None:
    sys_path_scripts = str(SCRIPTS)
    import sys
    inserted = sys_path_scripts not in sys.path
    if inserted:
        sys.path.insert(0, sys_path_scripts)
    try:
        import rlvr
    finally:
        if inserted:
            sys.path.remove(sys_path_scripts)
    assert "distill_lifecycle" not in rlvr.__all__
    assert not hasattr(rlvr, "distill_lifecycle")


@pytest.mark.parametrize("name", sorted({"distill_spine",
                                         "distill_lifecycle"}))
def test_retired_name_has_no_python_reference(name: str) -> None:
    hits = []
    for path in _python_files():
        if path == SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if name in text:
            hits.append(path.relative_to(ROOT).as_posix())
    assert not hits, (
        f"{name} is retired but still referenced by: {sorted(hits)}")


def test_scripts_readme_distill_rows_are_unique_and_truthful() -> None:
    text = (SCRIPTS / "README.md").read_text(encoding="utf-8")
    rows = [name for name in re.findall(r"^\|\s*`([^`]+)`\s*\|", text,
                                       re.MULTILINE)
            if name in DISTILL_ROW_NAMES]
    duplicates = sorted({name for name in rows if rows.count(name) > 1})
    assert not duplicates, (
        f"duplicate distill catalog rows in scripts/README.md: {duplicates}")
    assert "distill_spine.py" not in text
    assert "distill_lifecycle" not in text
    assert "producers import the library" not in text


def test_rlvr_readme_has_no_retired_row() -> None:
    text = (SCRIPTS / "rlvr" / "README.md").read_text(encoding="utf-8")
    assert "distill_lifecycle" not in text
