# -*- coding: utf-8 -*-
"""tests/test_tier_census.py — the gate-chain completeness invariant.

The acceleration work slices the suite into CI legs (-m fast, -m "not
fast", -m docs). Slicing relocates tests between jobs; it must never drop
one out of the gate chain. This module pins that invariant:

  1. the root conftest classifies every collected item into exactly one
     tier (fast / slow / integration default) and records the census on
     the config object;
  2. no item ever carries both tier markers (fast and slow);
  3. the census covers every test module on disk — a partial collection
     cannot hide a dropped module from the gate chain (run this module
     from a full-suite collection; that is the only surface it pins);
  4. the registries in _tiers are valid: every listed module exists and
     the two tier sets are disjoint;
  5. fast membership is re-derived from module source: a fast module
     contains no subprocess, network or golden-replay constructs.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import _tiers

# the construct ban a fast module must satisfy: the registry was built
# against this exact rule and the census keeps enforcing it
_FAST_BANNED = re.compile(r"subprocess|golden_master|socket|urllib|requests\.|http")


def _census(request):
    census = getattr(request.config, "_kunglao_tier_census", None)
    assert census, (
        "tier census missing from config: the root conftest did not record "
        "it during collection (pytest_collection_modifyitems contract "
        "broken)")
    return census


def test_census_classifies_the_whole_collection(request):
    """Every collected item lands in exactly one tier bucket."""
    census = _census(request)
    tiers = {"fast": 0, "slow": 0, "integration": 0}
    for name, entry in census.items():
        assert entry["items"] > 0, f"census entry with no items: {name}"
        assert entry["tier"] in tiers, f"unknown tier for {name}: {entry['tier']}"
        tiers[entry["tier"]] += entry["items"]
    total = sum(e["items"] for e in census.values())
    assert total == sum(tiers.values()), (total, tiers)


def test_no_item_carries_both_tier_markers(request):
    """fast and slow are exclusive at the item level, not just in the
    registry — the conftest counts dual-marked items as it goes."""
    census = _census(request)
    dual = {name: e["dual"] for name, e in census.items() if e["dual"]}
    assert not dual, f"items carrying both fast and slow markers: {dual}"


def test_registries_are_disjoint_and_exist():
    assert not (_tiers.FAST_MODULES & _tiers.SLOW_MODULES), (
        "modules listed in both FAST_MODULES and SLOW_MODULES: "
        f"{sorted(_tiers.FAST_MODULES & _tiers.SLOW_MODULES)}")
    for registry, label in ((_tiers.FAST_MODULES, "FAST_MODULES"),
                            (_tiers.SLOW_MODULES, "SLOW_MODULES"),
                            (_tiers.DOCS_MODULES, "DOCS_MODULES")):
        missing = sorted(m for m in registry
                         if not (TESTS_DIR / f"{m}.py").is_file())
        assert not missing, f"{label} lists missing modules: {missing}"


def _module_declines_collection(path: Path) -> bool:
    """True iff the module guards its own import with pytest.importorskip:
    it self-deselects in EVERY leg whenever its optional engine is absent,
    so absence from collection is uniform, not a gate-chain gap."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False  # a broken module MUST trip the census
    for node in tree.body:  # module level only
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        if (isinstance(func, ast.Attribute) and func.attr == "importorskip"
                and isinstance(func.value, ast.Name) and func.value.id == "pytest"):
            return True
    return False


def test_census_covers_every_test_module_on_disk(request):
    """Collection saw every tests/test_*.py on disk: no CI leg, -m filter
    or collection error can silently shrink the gate chain. A module may
    be absent only when it declines collection itself (module-level
    pytest.importorskip) — every leg sees the same absence."""
    census = _census(request)
    disk = {p.stem: p.resolve() for p in TESTS_DIR.glob("test_*.py")}
    seen_paths = {}
    for name, entry in census.items():
        path = entry.get("path")
        seen_paths[name] = Path(path).resolve() if path else None
    unaccounted = sorted(
        name for name in set(disk) - set(seen_paths)
        if not _module_declines_collection(TESTS_DIR / f"{name}.py"))
    assert not unaccounted, (
        f"{len(unaccounted)} test modules on disk never reached collection "
        f"and carry no importorskip guard: {unaccounted[:10]}")
    mismatched = sorted(
        name for name, path in seen_paths.items()
        if path is None or path != disk.get(name))
    assert not mismatched, (
        f"census module paths disagree with disk files: {mismatched[:10]}")


def test_fast_registry_modules_are_actually_pure_unit():
    """The fast tier's contract, re-checked at every run: no subprocess,
    no network client, no golden-master replay inside a fast module."""
    offenders = []
    for name in sorted(_tiers.FAST_MODULES):
        src = (TESTS_DIR / f"{name}.py").read_text(encoding="utf-8")
        hit = _FAST_BANNED.search(src)
        if hit:
            offenders.append(f"{name}.py ({hit.group(0)!r})")
    assert not offenders, (
        "fast registry violates the pure-unit ban: " + ", ".join(offenders)
        + " — demote the module to the integration tier instead")


def test_fast_modules_exist_in_collection(request):
    """The fast slice is non-trivial and every fast module was seen by
    collection (guards against a registry typo emptying the CI fast leg)."""
    census = _census(request)
    seen_fast = {n for n, e in census.items() if e["tier"] == "fast"}
    assert len(seen_fast) >= 100, (
        f"fast census suspiciously small: {len(seen_fast)} modules")
    missing = sorted(_tiers.FAST_MODULES - set(census))
    assert not missing, f"fast modules absent from collection: {missing[:10]}"
