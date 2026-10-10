# -*- coding: utf-8 -*-
"""tests/test_index_row_format_505.py — issue 505 contract (TDD).

Field evidence (round-8B, live): workers hand-write facts/_INDEX.md rows
in at least three shapes; the partial-facts probe parsed by POSITION
(parts[1] = status), so leading-pipe rows made it read the FACT-ID
column as the status — every row invisible, partial_count=0,
DISPATCH_VERIFIER never fired (the 8A/8B symptom's second root).
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import convergence_check as cc  # noqa: E402

# the three observed row shapes (pinned from the live 8B workspace)
CANONICAL = "F002 | INFERRED | C-004 | sigma candidates CK0..CK3 | pending"
LEADING_PIPE_5COL = ("| F002 | INFERRED | C-004 | sigma candidates CK0..CK3 "
                     "| pending |")
PARENTHETICAL_ID = ("| F002 (C-005 worker, bare file) | OPEN | C-005 | "
                    "clean-lane call graph |")


def _ws(tmp_path: Path, row: str, verified: str = "pending") -> Path:
    facts = tmp_path / "facts"
    facts.mkdir(exist_ok=True)
    (facts / "_INDEX.md").write_text("# _INDEX\n" + row + "\n",
                                     encoding="utf-8")
    (facts / "F002.md").write_text(
        "---\nid: F002\nstatus: INFERRED\nverified: " + verified +
        "\n---\nbody\n", encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n    question: q\n",
        encoding="utf-8")
    return tmp_path


# ---------- reader: content-based parsing under all three shapes ----------

def test_canonical_row_counts(tmp_path):
    assert [p["fact"] for p in cc._partial_facts(_ws(tmp_path, CANONICAL))] \
        == ["F002"]


def test_leading_pipe_5col_row_counts(tmp_path):
    """THE 8B regression: the leading pipe shifted parts[1] onto the
    fact-id column — the row must still parse by content."""
    assert [p["fact"] for p in
            cc._partial_facts(_ws(tmp_path, LEADING_PIPE_5COL))] == ["F002"]


def test_parenthetical_id_row_counts(tmp_path):
    ws = _ws(tmp_path, PARENTHETICAL_ID)
    partials = cc._partial_facts(ws)
    # OPEN status is not the INFERRED branch — must NOT count (the
    # id-recovery half below proves the row still parses)
    assert partials == [], partials
    sub = tmp_path / "b"
    sub.mkdir()
    ws2 = _ws(sub, PARENTHETICAL_ID.replace("| OPEN |",
                                                       "| PARTIAL |"))
    assert any("F002" in p["fact"]
               for p in cc._partial_facts(ws2)), "id with suffix unparsed"


def test_decide_level_8b_shape_fires_dispatch_verifier(tmp_path):
    """A workspace whose whole index is leading-pipe rows decides
    DISPATCH_VERIFIER (the 8B decide-level regression)."""
    ws = _ws(tmp_path, LEADING_PIPE_5COL)
    out = cc.decide(ws, emit_snapshot=False)
    assert out.get("decision") == "DISPATCH_VERIFIER", out.get("decision")
