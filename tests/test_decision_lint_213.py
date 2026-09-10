# -*- coding: utf-8 -*-
"""tests/test_decision_lint_213.py — issue 213 contract (pre-action lint).

The field failure: facts already gathered (x86_64 libidalib + python 3.14)
did not gate the next action — the binding was pip-installed anyway, an
incompatibility knowable BEFORE acting. Contract pinned here:

- check(action, facts) BLOCKS only known-incompatible (package, fact)
  pairs and prints the compatibility-matrix lines that name the mismatch;
- unknown packages and unknown/missing facts are OK-with-note — the lint
  NEVER blocks on unknowns (a false-positive gate gets ignored);
- the module is PURE: facts are caller-supplied, the environment is never
  probed (imports pinned below).
"""
from __future__ import annotations

import ast
from pathlib import Path

import decision_lint  # pytest.ini pythonpath includes scripts/


# ---------- block on known-incompatible pairs ----------

def test_blocks_install_against_gathered_facts_with_matrix():
    v = decision_lint.check(
        "pip install idapro",
        {"libidalib_arch": "x86_64", "python_version": "3.14"})
    assert v.blocked is True, "facts forbid this install — must BLOCK"
    assert v.matrix, "a block must print the compatibility matrix"
    assert any("python_version" in line for line in v.matrix)
    assert any("INCOMPATIBLE" in line for line in v.matrix)
    assert any("idapro" in reason for reason in v.reasons)


def test_blocks_arch_mismatch_only_when_both_sides_gathered():
    both = decision_lint.check(
        "pip install idapro",
        {"libidalib_arch": "x86_64", "python_arch": "arm64",
         "python_version": "3.12"})
    assert both.blocked is True
    assert any("libidalib_arch" in line for line in both.matrix)

    one_side = decision_lint.check(
        "pip install idapro", {"libidalib_arch": "x86_64"})
    assert one_side.blocked is False, "missing python_arch must not block"


def test_compatible_facts_pass_clean():
    v = decision_lint.check(
        "pip install idapro",
        {"python_version": "3.12", "libidalib_arch": "arm64",
         "python_arch": "arm64"})
    assert v.blocked is False
    assert v.matrix, "a judged action still renders its matrix"


# ---------- never block on unknowns ----------

def test_missing_facts_degrade_to_ok_with_note():
    v = decision_lint.check("pip install idapro", {})
    assert v.blocked is False
    assert any("note" in reason.lower() for reason in v.reasons)


def test_unknown_package_degrades_to_ok_with_note():
    v = decision_lint.check("pip install requests", {})
    assert v.blocked is False
    assert any("note" in reason.lower() for reason in v.reasons)


def test_unparseable_fact_values_never_block():
    v = decision_lint.check("pip install idapro", {"python_version": "future"})
    assert v.blocked is False


# ---------- purity: no environment probing ----------

def test_module_imports_stay_pure_no_probing():
    src = Path(decision_lint.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"re", "dataclasses", "sys", "json"}, imported
