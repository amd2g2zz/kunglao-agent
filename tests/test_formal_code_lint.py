# -*- coding: utf-8 -*-
"""tests/test_formal_code_lint.py — the formal-content ratchet pins:
formal code carries no issue numbers / version narration / date stamps
in comments or docstrings (owner ruling); the ledger freezes existing
debt; new debt fails; strings (schema stamps) stay exempt."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import formal_code_lint as fcl  # noqa: E402


def test_issue_reference_detected_in_comment():
    text = "# see the dispatch contract (#539) for the seam\nx = 1\n"
    assert fcl.RE_ISSUE.search(fcl._comment_text(text))
    assert fcl.RE_ISSUE.search("Fixed per issue 428 note")


def test_version_and_date_narration_detected():
    assert fcl.RE_VERSION.search("# landed in v0.1.6")
    assert fcl.RE_VERSION.search("# PR-2 of the wave")
    assert not fcl.RE_VERSION.search("# see PR face")
    assert fcl.RE_DATE.search("# observed 2026-10-08")


def test_schema_strings_are_exempt_by_shape():
    # the detectors never match protocol strings, but the docstring-only
    # scope makes even a hypothetical match impossible for literals
    text = 'SCHEMA = "posterior-store/1"\nVERSION = "1"\n'
    assert not fcl.RE_VERSION.search(fcl._comment_text(text))
    assert fcl._docstrings("x = 1\n") == []


def test_two_digit_numbers_not_flagged():
    assert not fcl.RE_ISSUE.search("# 42 steps")
    assert not fcl.RE_ISSUE.search("#rc=3")


def test_ratchet_new_debt_fails_and_shrink_only():
    counts = {"a.py": 2}
    assert fcl.compare(counts, {}) == [
        {"file": "a.py", "kind": "unbaselined",
         "detail": "markers 2 with no ledger entry"}]
    assert fcl.compare({"a.py": 3}, {"a.py": 2}) == [
        {"file": "a.py", "kind": "increase", "detail": "grew 2 -> 3"}]
    # shrinking is legal; reaching zero deletes the entry
    assert fcl.compare({"a.py": 0}, {"a.py": 2}) == []
    # a ledger entry for a cleaned file is stale and must be deleted
    assert fcl.compare({}, {"a.py": 2}) == [
        {"file": "a.py", "kind": "stale-entry",
         "detail": "ledger entry for a file with no markers (delete it)"}]


def test_real_tree_gate_is_green():
    assert fcl.main([]) == 0
