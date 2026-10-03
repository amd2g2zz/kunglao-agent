# -*- coding: utf-8 -*-
"""tests/test_partial_proven_510.py — issue 510 contract (TDD).

Field evidence (round-8B resume-3): both claims PROVEN via the full
note+red-team chains, but the fact files were never re-marked — the
probe counted 12 partials forever, DISPATCH_VERIFIER no-op'd on held
V-keys, and CONVERGED was unreachable. The register is authoritative
(state-mapping.md): a fact of a PROVEN claim owes no independent
verification.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import convergence_check as cc  # noqa: E402


def _ws(tmp_path: Path, claim_status: str) -> Path:
    facts = tmp_path / "facts"
    facts.mkdir()
    (facts / "_INDEX.md").write_text(
        "# _INDEX\n"
        "F002 | INFERRED | C-004 | sigma | pending\n"
        "F007 | INFERRED | C-005 | reimpl | pending\n",
        encoding="utf-8")
    for fid in ("F002", "F007"):
        (facts / f"{fid}.md").write_text(
            f"---\nid: {fid}\nstatus: INFERRED\nverified: pending\n---\n",
            encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(
        f"claims:\n"
        f"  - id: C-004\n    status: {claim_status}\n    question: q\n"
        f"    answers_question: pq-1\n"
        f"  - id: C-005\n    status: PROVEN\n    question: q\n"
        f"    answers_question: pq-2\n",
        encoding="utf-8")
    (tmp_path / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "- id: pq-1\n  question: q1\n"
        "- id: pq-2\n  question: q2\n",
        encoding="utf-8")
    return tmp_path


def test_proven_claim_facts_do_not_owe(tmp_path):
    """The 8B3 terminal regression: all claims PROVEN, facts unmarked —
    zero partials, decide CONVERGED."""
    out = cc.decide(_ws(tmp_path, "PROVEN"), emit_snapshot=False)
    # the #466/#498 delivery face: the done verdict rides DISPATCH/exit-1
    # with the Claim-loop-done action (the loop's break signal)
    assert out.get("decision") == "DISPATCH" and out.get("exit_code") == 1
    assert "Claim loop done" in str(out.get("action"))


def test_refuted_negated_claim_facts_do_not_owe(tmp_path):
    assert cc._partial_facts(_ws(tmp_path, "REFUTED")) == []


def test_nonterminal_claim_facts_still_owe(tmp_path):
    """The #500/#505 behavior is unchanged for open work."""
    partials = cc._partial_facts(_ws(tmp_path, "PARTIALLY-VERIFIED"))
    assert [p["fact"] for p in partials] == ["F002"]  # C-005 PROVEN excluded


def test_unreadable_register_degrades_to_fact_state(tmp_path):
    ws = _ws(tmp_path, "PROVEN")
    (ws / "claim-register.yaml").write_text("claims: [broken", encoding="utf-8")
    # fail-open: the fact-level signal stands (both facts owed)
    assert len(cc._partial_facts(ws)) == 2
