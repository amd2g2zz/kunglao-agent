# -*- coding: utf-8 -*-
"""tests/test_partial_fact_vocab_500.py — issue 500 contract (TDD).

Field evidence (round-8A, 2026-10-02): workers write facts with the
schema-layer frontmatter (status INFERRED, verified pending) AND copy that
schema status into the facts/_INDEX.md status column. The convergence probe
_partial_facts matched only the workflow vocabulary (PARTIAL_STATUSES), so
partial_count=0 on every tick, DISPATCH_VERIFIER never fired, and the loop
re-dispatched workers toward the noop-breaker. state-mapping.md §2 keeps the
index column workflow-layer, but the probe must be robust to either
vocabulary — the fact needing verification is the same fact either way.
"""
from __future__ import annotations

from pathlib import Path


import convergence_check as cc

LEGACY_ROW = ("F001-alpha | PARTIALLY-VERIFIED | C-001 | legacy workflow "
              "vocabulary row\n")
WORKER_ROW = ("F002-beta | INFERRED | C-002 | schema vocabulary written by "
              "the worker\n")
VERIFIED_ROW = ("F003-gamma | INFERRED | C-003 | verified fact (schema "
                "vocab; frontmatter says passes)\n")


def _fact(path: Path, status: str, verified: str) -> None:
    path.write_text(
        "---\nid: {id}\nstatus: {st}\nverified: {vs}\n---\nbody\n".format(
            id=path.stem, st=status, vs=verified),
        encoding="utf-8")


def _ws(tmp_path: Path, index_rows: str, facts: list[tuple[str, str, str]]
        ) -> Path:
    """Minimal workspace: register with one open claim + facts dir."""
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir()
    (facts_dir / "_INDEX.md").write_text(index_rows, encoding="utf-8")
    for fid, st, vs in facts:
        _fact(facts_dir / f"{fid}.md", st, vs)
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n    question: q\n",
        encoding="utf-8")
    return tmp_path


# ---------- probe-level: the vocabulary bridge ----------

def test_workflow_row_still_counts(tmp_path):
    ws = _ws(tmp_path, LEGACY_ROW,
             [("F001-alpha", "INFERRED", "pending")])
    partials = cc._partial_facts(ws)
    assert [p["fact"] for p in partials] == ["F001-alpha"]


def test_schema_vocab_row_with_pending_verification_counts(tmp_path):
    """THE 8A shape: worker wrote INFERRED into the index column while the
    fact file says verified: pending — the fact still needs a verifier."""
    ws = _ws(tmp_path, WORKER_ROW,
             [("F002-beta", "INFERRED", "pending")])
    partials = cc._partial_facts(ws)
    assert [p["fact"] for p in partials] == ["F002-beta"], (
        "schema-vocabulary (INFERRED + verified pending) fact invisible to "
        "the partial probe — DISPATCH_VERIFIER will never fire (#500)")


def test_schema_vocab_row_with_partial_verification_counts(tmp_path):
    ws = _ws(tmp_path, WORKER_ROW,
             [("F002-beta", "INFERRED", "partial")])
    partials = cc._partial_facts(ws)
    assert [p["fact"] for p in partials] == ["F002-beta"]


def test_schema_vocab_row_with_passing_verification_does_not_count(tmp_path):
    """verified: passes means no verifier is owed — never counted."""
    ws = _ws(tmp_path, VERIFIED_ROW,
             [("F003-gamma", "INFERRED", "passes")])
    assert cc._partial_facts(ws) == []


def test_missing_fact_file_degrades_to_row_status_only(tmp_path):
    """Index row INFERRED with no fact file behind it still counts — an
    unverifiable claim about verification state must not silently vanish."""
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir()
    (facts_dir / "_INDEX.md").write_text(WORKER_ROW, encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n    question: q\n",
        encoding="utf-8")
    partials = cc._partial_facts(tmp_path)
    assert [p["fact"] for p in partials] == ["F002-beta"]


# ---------- decide-level: the 8A regression ----------

def test_8a_shape_decides_dispatch_verifier(tmp_path):
    """Regression: open claim + free slots + only worker-shaped facts —
    the decision must be DISPATCH_VERIFIER, not DISPATCH (the 8A loop
    spun re-dispatching workers while verifier dispatch never fired)."""
    ws = _ws(tmp_path, WORKER_ROW,
             [("F002-beta", "INFERRED", "pending")])
    out = cc.decide(ws, emit_snapshot=False)
    assert out.get("decision") == "DISPATCH_VERIFIER", out.get("decision")


# ---------- fail-closed faces (review finding 1) ----------

def test_fails_and_stale_values_count_as_owed(tmp_path):
    """Note-layer values cross-copied into the fact verified field are
    owed verification — they must not silently vanish (fail-closed)."""
    for i, bad in enumerate(("fails", "stale", "passsed")):
        case = tmp_path / f"case{i}"
        case.mkdir()
        ws = _ws(case, WORKER_ROW,
                 [("F002-beta", "INFERRED", bad)])
        assert cc._partial_facts(ws), f"verified: {bad!r} vanished — not owed?"


def test_date_shaped_verified_value_not_owed(tmp_path):
    """The migrated verified-at form (a date) is a settled fact."""
    ws = _ws(tmp_path, WORKER_ROW, [("F002-beta", "INFERRED", "2026-10-02")])
    assert cc._partial_facts(ws) == []


def test_body_text_verified_line_is_ignored(tmp_path):
    """A 'verified:' line in the BODY (not frontmatter) never counts."""
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir()
    (facts_dir / "_INDEX.md").write_text(WORKER_ROW, encoding="utf-8")
    (facts_dir / "F002-beta.md").write_text(
        "---\nid: F002-beta\nstatus: INFERRED\n---\n"
        "narrative: verified: passes appeared in prose\n",
        encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n    question: q\n",
        encoding="utf-8")
    # frontmatter lacks verified: -> owed (the body line must not save it)
    assert [p["fact"] for p in cc._partial_facts(tmp_path)] == ["F002-beta"]
