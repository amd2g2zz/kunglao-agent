# -*- coding: utf-8 -*-
r"""Issue #690 — tests/ must not hardcode drive-letter absolute paths.

User policy (2026-08-25): "肯定不能写绝对路径，只能写相对路径。"
Absolute path shapes in tests derive from tmp_path; inert string values use
relative forms or os.sep; detection needles / parser fixtures that must
carry a drive shape are built by concatenating inert fragments ("C:" +
"/Users/"). Docstring/comment prose citing a concrete historical incident
(e.g. the #356/#367 user-path purge) stays verbatim behind the
HISTORICAL-PATH-EXAMPLE line sentinel.

Regex notes (#690 design.md D1): a forward slash is never an escape, so any
uppercase drive + '/' is a hit; the backslash form excludes the common
escape letters (n/r/t) so 'WORD:\n' fixture text and 'a:\n' code do not
trip, while doubled '\\\\' (an escaped backslash) still hits. Known blind
spot, none in this tree: a raw single-backslash path whose first segment
starts with n/r/t (X:\temp shape).

Run: uv run python -m pytest tests/test_no_absolute_paths.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# Uppercase drive letter + ':' + slash, or backslash not followed by an
# escape letter. House lineage: test_skill_contract.py HARDCODED.
DRIVE = re.compile(r"[A-Z]:/|[A-Z]:\\(?![nrt])")
# Platform-independent sentinels — inert for DRIVE (no letter+colon), kept
# as an explicit tested category so future pattern extensions (POSIX
# absolute paths) inherit the carve-out.
SENTINELS = ("/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr")
# Line sentinel for documented historical counterexamples (docstring or
# comment prose only — never to excuse a path VALUE in use).
HISTORICAL = "HISTORICAL-PATH-EXAMPLE"


EXEMPT_DIRS = ("v013_acceptance",)  # private acceptance harness (untracked; auditor's verification env)


def scan(root: Path) -> list[str]:
    """Return '<relpath>:<line>' violations for drive-letter literals.

    Skips dirs in EXEMPT_DIRS — v013_acceptance/ is the auditor's private
    acceptance verification harness (untracked gitignored); the user policy
    #690 targets tracked test code, not this auditor-private dir.
    """
    out: list[str] = []
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if rel.split("/", 1)[0] in EXEMPT_DIRS:
            continue
        for i, line in enumerate(
            py.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if HISTORICAL in line:
                continue
            if any(s in line for s in SENTINELS):
                continue
            if DRIVE.search(line):
                out.append(f"{rel}:{i}")
    return out


def test_tests_tree_has_no_drive_letter_paths():
    """The live guard: any PR that lands a hardcoded absolute path in
    tests/ goes red here (#690 acceptance: 112 -> 0)."""
    violations = scan(TESTS)
    assert not violations, (
        f"{len(violations)} hardcoded absolute-path site(s) in tests/ — "
        "derive from tmp_path, use relative/os.sep forms, build needles by "
        f"fragment concat, or mark documented historical examples with "
        f"{HISTORICAL}. First 15: {violations[:15]}")


def test_scanner_flags_planted_violation(tmp_path: Path):
    """Negative sample: the guard must provably go red. Violation content
    is assembled from inert fragments so this file stays self-clean."""
    leak = "D:" + "/leak/path"
    (tmp_path / "test_planted.py").write_text(
        f"x = {leak!r}\n", encoding="utf-8")
    assert scan(tmp_path) == ["test_planted.py:1"]


def test_scanner_passes_clean_tree(tmp_path: Path):
    (tmp_path / "test_clean.py").write_text(
        "from pathlib import Path\n"
        "home = str(Path(__file__).parent / 'ghidra')\n"
        "rel = 'hooks/worker_budget.py'\n",
        encoding="utf-8")
    assert scan(tmp_path) == []


def test_historical_sentinel_line_is_skipped(tmp_path: Path):
    ref = "C:" + "/Users/hr/... pre-#356 incident"
    (tmp_path / "test_doc.py").write_text(
        f'"""purged in #356: {ref} HISTORICAL-PATH-EXAMPLE"""\n',
        encoding="utf-8")
    assert scan(tmp_path) == []


def test_sentinel_does_not_mask_neighbor_lines(tmp_path: Path):
    """The sentinel excuses only its own line, never the file."""
    ref = "C:" + "/Users/hr/... pre-#356 incident"
    leak = "D:" + "/leak/path"
    (tmp_path / "test_doc2.py").write_text(
        f'"""{ref} HISTORICAL-PATH-EXAMPLE"""\nleak = {leak!r}\n',
        encoding="utf-8")
    assert scan(tmp_path) == ["test_doc2.py:2"]


def test_escape_shaped_text_is_not_flagged(tmp_path: Path):
    r"""False-positive pins: WORD:\n fixture text, \d regex classes, and
    URL schemes must not fire (design.md D1 table)."""
    nl = chr(92) + "n"  # a literal backslash-n pair, built inertly
    (tmp_path / "test_escapes.py").write_text(
        f'msg = "state PENDING:{nl}"\n'
        'ts = re.sub(r"\\d\\d:\\d\\d", "TS", s)\n'
        'url = "https://example.invalid/x"\n',
        encoding="utf-8")
    assert scan(tmp_path) == []


def test_platform_sentinels_are_skipped(tmp_path: Path):
    (tmp_path / "test_sentinel.py").write_text(
        'sink = "/dev/null"\n', encoding="utf-8")
    assert scan(tmp_path) == []
