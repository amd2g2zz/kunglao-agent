#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_scan_proven_507.py — the #505 sibling: _scan_proven_facts.

Field evidence (issue #507): the contradiction gate's PROVEN scan still
reads the _INDEX row POSITIONALLY (parts[1].upper() == "PROVEN"), so the
leading-pipe 5-column shape workers actually hand-write parses as
['', F-id, status, tier, conclusion] — parts[1] is the fact id, the row
is skipped, and PROVEN facts silently vanish from the contradiction
heuristic. The #505 fix (_row_fact_and_status, content-based) never
reached this sibling scanner.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import convergence_check as cc  # noqa: E402


def _idx(ws: Path, body: str) -> Path:
    d = ws / "facts"
    d.mkdir(parents=True)
    p = d / "_INDEX.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_leading_pipe_proven_row_is_scanned(tmp_path):
    _idx(tmp_path, (
        "| F001 | PROVEN | l1 | the pad is 6d1f0b9ac2 |\n"
        "| F002 | INFERRED | l1 | unproven sibling |\n"))
    proven = cc._scan_proven_facts(tmp_path)
    assert proven.get("F001") == "the pad is 6d1f0b9ac2", proven


def test_canonical_shape_still_scanned(tmp_path):
    _idx(tmp_path, (
        "F001 | PROVEN | l1 | key recovered |\n"))
    proven = cc._scan_proven_facts(tmp_path)
    assert proven.get("F001") == "key recovered", proven


def test_parenthetical_id_suffix(tmp_path):
    _idx(tmp_path, (
        "| F003 (dup) | PROVEN | l2 | sigma confirmed |\n"))
    proven = cc._scan_proven_facts(tmp_path)
    assert proven.get("F003") == "sigma confirmed", proven
