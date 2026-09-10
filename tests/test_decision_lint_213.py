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
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert imported <= {"__future__", "re", "dataclasses", "sys", "json"}, imported


# ---------- finding 2 (issue 225): case/separator-folded package match ----------

@pytest.mark.parametrize("action", [
    "pip install IDAPRO",
    "pip install ida-pro",
    "pip install ida_pro",
    "pip install ./idapro-9.0.whl",
])
def test_package_token_match_is_case_and_separator_folded(action):
    """The canonical field mistake must be caught in every spelling a field
    command uses: IDAPRO, ida-pro, ida_pro, a wheel path."""
    v = decision_lint.check(action, {"python_version": "3.14"})
    assert v.blocked is True, action
    assert any("idapro" in r for r in v.reasons), v.reasons


def test_near_miss_package_name_does_not_block():
    """Folding must not turn every lookalike into idapro: an unknown
    package name stays OK-with-note (unknowns never block)."""
    v = decision_lint.check("pip install idaproduction",
                            {"python_version": "3.14"})
    assert v.blocked is False


def test_cli_blocks_the_uppercase_spelling():
    """The reviewer's CLI repro: pip install IDAPRO + python 3.14 facts on
    stdin -> BLOCKED, exit 1 (not the literal-match miss)."""
    r = subprocess.run(
        [sys.executable, str(Path(decision_lint.__file__)),
         "pip install IDAPRO"],
        input='{"python_version": "3.14"}', capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "VERDICT: BLOCKED" in r.stdout, r.stdout


# ---------- finding 9 (issue 225): arch aliases, stdin bytes, uninstall ----------

@pytest.mark.parametrize("lib_arch,python_arch", [
    ("x64", "amd64"),
    ("amd64", "x64"),
    ("x86-64", "x86_64"),
    ("aarch64", "arm64"),
])
def test_arch_aliases_normalize_before_judging(lib_arch, python_arch):
    """x64 / amd64 / x86-64 are one family; so are aarch64 / arm64. A known
    alias spelling difference is not an incompatibility."""
    v = decision_lint.check(
        "pip install idapro",
        {"libidalib_arch": lib_arch, "python_arch": python_arch,
         "python_version": "3.12"})
    assert v.blocked is False, (lib_arch, python_arch, v.matrix)


def test_real_arch_mismatch_still_blocks():
    v = decision_lint.check(
        "pip install idapro",
        {"libidalib_arch": "x86_64", "python_arch": "arm64",
         "python_version": "3.12"})
    assert v.blocked is True


def test_unknown_arch_alias_never_grounds_a_block():
    """The docstring contract: an unmatched alias degrades to a note, it
    cannot ground a block (a false-positive gate gets ignored)."""
    v = decision_lint.check(
        "pip install idapro",
        {"libidalib_arch": "riscv64", "python_arch": "arm64",
         "python_version": "3.12"})
    assert v.blocked is False
    assert any("note" in r.lower() for r in v.reasons), v.reasons


def test_uninstall_is_not_judged_as_an_install():
    """`pip uninstall idapro` removes the binding — it must never be blocked
    as if it were the install the rule was written for."""
    v = decision_lint.check("pip uninstall idapro", {"python_version": "3.14"})
    assert v.blocked is False
    assert any("note" in r.lower() for r in v.reasons), v.reasons


def test_undecodable_stdin_is_ok_with_note_never_blocked_by_crash():
    """Non-UTF-8 stdin raised UnicodeDecodeError -> traceback, exit 1 (the
    BLOCKED exit code). Undecodable facts are unknowns: OK-with-note."""
    r = subprocess.run(
        [sys.executable, str(Path(decision_lint.__file__)),
         "pip install idapro"],
        input=b'{"python_version": "\xff\xfe not utf-8"}',
        capture_output=True, timeout=60)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    out = r.stdout.decode("utf-8", errors="replace")
    assert "VERDICT: OK" in out, out
    assert "note" in out.lower(), out
