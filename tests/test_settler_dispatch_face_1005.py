# -*- coding: utf-8 -*-
"""tests/test_settler_dispatch_face_1005.py — the settler dispatch face.

S2 fixed the blind settlement INPUT; nothing dispatched the settler, so
the round-closure settle face never received a verdict and the loop ran
without settling (the live audit: zero settle events, `dispatched_ids`
empty on every verifier decision). This face is the decision payload's
`pending_settlements` (conditional, so the byte-frozen anchors stay
identical when nothing is parked) plus the skill contract that drains it
before the next worker dispatch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(SCRIPTS), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import convergence_check as cc  # noqa: E402
import test_decide_regression_anchor as anchor  # noqa: E402


def _parked(ws: Path, claim: str = "C-1", *, verdict: bool = False) -> Path:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    p = ws / "runs" / f"settlement-input-{claim}.json"
    p.write_text(json.dumps({
        "schema": "blind-settlement-input/1",
        "identity": "kunglao-settler", "claim": claim, "question": "q?",
        "artifacts": [{"path": "evidence/x.bin", "sha256": "0" * 64}],
        "rules": None}) + "\n", encoding="utf-8")
    if verdict:
        (ws / "runs" / f"settlement-verdict-{claim}.json").write_text(
            json.dumps({"schema": "settlement-verdict/1",
                        "identity": "kunglao-settler", "claim": claim,
                        "actions": [], "trajectory_credit": 0.0}) + "\n",
            encoding="utf-8")
    return p


def test_decision_payload_carries_pending_settlements(tmp_path) -> None:
    ws = anchor.build_case("drain_converged_full", tmp_path)
    _parked(ws, "C-1")
    d = cc.decide(ws)
    assert d["pending_settlements"] == [
        {"claim": "C-1", "path": "runs/settlement-input-C-1.json"}]


def test_absent_when_no_parked_input(tmp_path) -> None:
    """Conditional key: the byte-frozen decide anchors stay identical."""
    ws = anchor.build_case("drain_converged_full", tmp_path)
    d = cc.decide(ws)
    assert "pending_settlements" not in d


def test_a_ruled_claim_is_not_pending(tmp_path) -> None:
    ws = anchor.build_case("drain_converged_full", tmp_path)
    _parked(ws, "C-1", verdict=True)
    d = cc.decide(ws)
    assert "pending_settlements" not in d


def test_a_hostile_filename_does_not_suppress_the_drain(tmp_path) -> None:
    """One bad file is ONE warn: a hostile token (``settlement-input-..``)
    must not switch off the dispatch that polices the producer."""
    ws = anchor.build_case("drain_converged_full", tmp_path)
    _parked(ws, "C-1")
    (ws / "runs" / "settlement-input-..json").write_text(
        "{}", encoding="utf-8")
    d = cc.decide(ws)
    assert d["pending_settlements"] == [
        {"claim": "C-1", "path": "runs/settlement-input-C-1.json"}]


def test_a_corrupt_verdict_keeps_the_claim_pending(tmp_path) -> None:
    """A file named like a verdict but unparseable is NOT a ruling:
    ``settle_parked`` would refuse it, so the claim must stay pending
    instead of stranding as ruled-but-unsettleable."""
    ws = anchor.build_case("drain_converged_full", tmp_path)
    _parked(ws, "C-1")
    (ws / "runs" / "settlement-verdict-C-1.json").write_text(
        "{not json", encoding="utf-8")
    d = cc.decide(ws)
    assert d["pending_settlements"] == [
        {"claim": "C-1", "path": "runs/settlement-input-C-1.json"}]


def test_a_pathologically_nested_doc_does_not_suppress_the_drain(
        tmp_path) -> None:
    """RecursionError is part of the unreadable family: a ~2 KB nested
    doc must not take the whole drain down with it."""
    ws = anchor.build_case("drain_converged_full", tmp_path)
    _parked(ws, "C-1")
    (ws / "runs" / "settlement-input-deep.json").write_text(
        "[" * 200000 + "]" * 200000, encoding="utf-8")
    d = cc.decide(ws)
    assert d["pending_settlements"] == [
        {"claim": "C-1", "path": "runs/settlement-input-C-1.json"}]


def test_human_view_surfaces_pending_settlements(tmp_path) -> None:
    """The Phase 2 command runs without --json: the human view must show
    the drain or the orchestrator never sees it."""
    ws = anchor.build_case("drain_converged_full", tmp_path)
    _parked(ws, "C-1")
    text = cc._human(cc.decide(ws))
    assert "settler pending: 1" in text
    assert "kunglao-settler" in text and "C-1" in text


def test_skill_contract_teaches_the_drain() -> None:
    root = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
        encoding="utf-8")
    analysis = (ROOT / "skills" / "analysis" / "SKILL.md").read_text(
        encoding="utf-8")
    for text in (root, analysis):
        assert "pending_settlements" in text
        assert "kunglao-settler" in text
        assert "facts-snapshot" in text and "≤3" in text
