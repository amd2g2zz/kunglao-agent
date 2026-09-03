# -*- coding: utf-8 -*-
"""Issue #819 — register_proven_gate: evidence-gated ->PROVEN transitions.

豆包 pathology: register edited to PROVEN while verify said REJECTED — no
evidence predicate existed on the ->PROVEN migration. Fail-closed: a ->PROVEN
transition without (latest verify-note == passes AND red-team ran AND latest
red-team != REFUTED) — or a justified waiver — is a violation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from register_proven_gate import check_register_transitions  # noqa: E402

REG = (
    "claims:\n"
    "  - id: {c1}\n"
    "    status: {s1}\n"
    "    statement: synthetic claim for gate tests\n"
    "  - id: {c2}\n"
    "    status: {s2}\n"
    "    statement: synthetic claim for gate tests\n"
)


def _reg(s1: str, s2: str = "OPEN") -> str:
    return REG.format(c1="C-001", c2="C-002", s1=s1, s2=s2)


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _verify(ws, claim, verdict):
    d = ws / "runs"
    (d / f"2026-08-31-verify-{claim}.md").write_text(
        f"---\nclaim_id: {claim}\n---\n\n## Overall verdict\n{verdict}\n",
        encoding="utf-8")


def _redteam(ws, claim, verdict):
    d = ws / "runs"
    (d / f"verify-redteam-{claim}.md").write_text(
        f"---\ntarget: {claim}\n---\n\nRED-TEAM VERDICT: {verdict}\nclaim: {claim}\n\nverifier-identity: rt-worker-1",
        encoding="utf-8")


def _waiver(ws, claim, justify):
    d = ws / "runs"
    (d / f"proven-waiver-{claim}.md").write_text(
        f"---\nclaim_id: {claim}\n---\n\njustify: {justify}\n", encoding="utf-8")


OLD = _reg("OPEN")
NEW = _reg("PROVEN")
NEW_MIXED = _reg("PROVEN", "PROVEN")


def test_no_evidence_blocks(tmp_path):
    ws = _mk_ws(tmp_path)
    res = check_register_transitions(ws, NEW, OLD)
    assert res["ok"] is False
    assert any("C-001" in v for v in res["violations"])
    assert all("C-002" not in v for v in res["violations"])


def test_full_evidence_allows(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify(ws, "C-001", "passes")
    _redteam(ws, "C-001", "CONFIRMED")
    res = check_register_transitions(ws, NEW, OLD)
    assert res["ok"] is True, res["violations"]
    assert res["violations"] == []


def test_verify_partial_not_enough(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify(ws, "C-001", "partial")
    _redteam(ws, "C-001", "CONFIRMED")
    res = check_register_transitions(ws, NEW, OLD)
    assert res["ok"] is False


def test_redteam_refuted_blocks(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify(ws, "C-001", "passes")
    _redteam(ws, "C-001", "REFUTED")
    res = check_register_transitions(ws, NEW, OLD)
    assert res["ok"] is False
    assert any("REFUTED" in v for v in res["violations"])


def test_redteam_missing_blocks(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify(ws, "C-001", "passes")
    res = check_register_transitions(ws, NEW, OLD)
    assert res["ok"] is False


def test_redteam_unverified_runs_counts_as_ran(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify(ws, "C-001", "passes")
    _redteam(ws, "C-001", "UNVERIFIED-WITH-GAP")
    res = check_register_transitions(ws, _reg("PROVEN"), OLD)
    assert res["ok"] is True, res["violations"]


def test_waiver_with_justify_allows(tmp_path):
    ws = _mk_ws(tmp_path)
    _waiver(ws, "C-001", "operator override: sample already public family X")
    res = check_register_transitions(ws, NEW, OLD)
    assert res["ok"] is True, res["violations"]
    assert res["waivers"] and res["waivers"][0]["claim_id"] == "C-001"
    assert "operator override" in res["waivers"][0]["justify"]


def test_waiver_empty_justify_blocks(tmp_path):
    ws = _mk_ws(tmp_path)
    _waiver(ws, "C-001", "")
    res = check_register_transitions(ws, NEW, OLD)
    assert res["ok"] is False


def test_no_transition_is_noop(tmp_path):
    ws = _mk_ws(tmp_path)
    res = check_register_transitions(ws, OLD, OLD)
    assert res["ok"] is True
    assert res["violations"] == []
    assert res["waivers"] == []


def test_non_proven_transitions_not_gated(tmp_path):
    ws = _mk_ws(tmp_path)
    res = check_register_transitions(ws, _reg("VERIFIED"), OLD)
    assert res["ok"] is True


def test_new_claim_direct_proven_is_gated(tmp_path):
    ws = _mk_ws(tmp_path)
    reg = "claims:\n  - id: C-009\n    status: PROVEN\n    statement: x\n"
    res = check_register_transitions(ws, reg, OLD)
    assert res["ok"] is False
    assert any("C-009" in v for v in res["violations"])


def test_ledger_row_alone_not_sufficient(tmp_path):
    """Design decision (#819): the gate reads the PRIMARY evidence source
    (runs/*.md, same as outcome_capture) only. A ledger OUTCOME row whose
    runs file is gone is stale bookkeeping, not evidence."""
    ws = _mk_ws(tmp_path)
    import json
    row = {"type": "outcome", "ts": "2026-08-31T00:00:00+00:00",
           "claim_id": "C-001", "result": "passes", "checker": "verify-note"}
    with (ws / ".convergence_ledger.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    _redteam(ws, "C-001", "CONFIRMED")
    res = check_register_transitions(ws, NEW, OLD)
    assert res["ok"] is False
