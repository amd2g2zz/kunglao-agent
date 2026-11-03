# -*- coding: utf-8 -*-
"""tests/test_blind_settler_wire_802.py — the blind settler is WIRED
(issue-802): production settlement routes through the blind face.

issue-687 built the barrier family (settlement_scorer + the read barrier +
the kunglao-settler agent face) and left it ARMED-UNWIRED: no
production writer built a blind-settlement-input/1 doc, and the
unblinded ``settle_step`` judgment is what ran. issue-802 closes the gap:

  1. THE WRITER — settlement_wire.park_blind_input builds the blind
     input doc from the step's raw artifacts: producer faces (notes/,
     facts/, worker-status, verification narratives, the learning
     ledgers) are excluded BY CONSTRUCTION — a forbidden face in the
     artifact list is RED, and a legal park carries zero poison bytes;
  2. THE CONSUMER — settle_parked re-verifies the artifact bytes
     against the parked sha256s (settle over exactly what was blinded;
     drift refuses), re-checks the ruling identity, and routes through
     settlement_scorer.settle_blind (blind gate -> scalar.
     validate_verdict_doc stack -> rollout ledger);
  3. THE issue-800/issue-809 ALIGNMENT — the claim mint rides claims_store.apply:
     an oracle-pass blind settlement mints PROVEN only through
     settle_proven WITH a verification reference that RESOLVES to a
     PASSED record (the store refuses otherwise, fail-closed); an
     oracle-fail maps to settle_refuted. The provenance rows carry the
     settler identity (actor ``settler:<id>``);
  4. THE EVAL GATE — the unblinded settle_step judgment is eval-only:
     the production stop face defaults to the blind mode (no unblinded
     step credit banked) and KUNGLAO_EVAL_SETTLE=1 opts back into the
     legacy behavior explicitly;
  5. THE LIVENESS FINGERPRINT — every blind settlement event lands a
     settlement-wire/1 row (runs/settlement.jsonl) carrying the
     non-empty settler identity: production settlements show
     settler-identity rows from the blind path.

Fixtures are SYNTHETIC and deliberately POISONED (sentinel strings in
every forbidden face) — no production log ever enters the repo.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import settlement_wire as wire  # noqa: E402
from rlvr import step_grain as sg  # noqa: E402

T0 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------ fixtures

def _ws(tmp_path: Path) -> Path:
    """Poisoned workspace: every forbidden face carries a sentinel."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-9\n    status: IN_PROGRESS\n", encoding="utf-8")
    (ws / "evidence").mkdir()
    (ws / "evidence" / "raw-step.bin").write_bytes(b"raw-step-artifact-bytes")
    (ws / "runs").mkdir()
    for name, body in (("worker-status-w9.md", "POISON_WORKER_STATUS"),
                       ("W9-verify-note.md", "POISON_VERIFY_NOTE"),
                       ("verification-C-9.md", "POISON_VERIFICATION"),
                       ("method-family-log.jsonl", "POISON_METHOD_FAMILY"),
                       ("q-cell-log.jsonl", "POISON_Q_CELL"),
                       ("experience.jsonl", "POISON_EXPERIENCE")):
        (ws / "runs" / name).write_text(body + "\n", encoding="utf-8")
    (ws / "notes").mkdir()
    (ws / "notes" / "worker-report.md").write_text(
        "POISON_PRODUCER_NARRATIVE\n", encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text(
        "---\nid: F001\ntype: fact\n---\nPOISON_FACT_CONCLUSION\n",
        encoding="utf-8")
    return ws


def _rules(tmp_path: Path) -> Path:
    p = tmp_path / "reward-rules.yaml"
    p.write_text("rules: synthetic-settlement-rules\n", encoding="utf-8")
    return p


def _input_doc(ws: Path, rules: Path) -> dict:
    return wire.park_blind_input(
        ws, "C-9", ["evidence/raw-step.bin"],
        rules_path=rules)["doc"]


def _verdict(credit: float = 0.5, cite: str = "evidence/raw-step.bin",
             identity: str = "kunglao-settler") -> dict:
    return {"schema": "settlement-verdict/1",
            "identity": identity,
            "claim": "C-9",
            "actions": [{"action_id": "step-1", "credit": credit,
                         "evidence": [cite]}],
            "trajectory_credit": credit}


def _seed_claim_dispatch(ws: Path, claim: str = "C-9") -> None:
    """A pending worker step: launch stash + session rows (the mechanical
    step-grain settle surface)."""
    from rlvr import incremental_reward as ir
    ir.record_launch(ws, claim, "grab", 0.5, action_type="dispatch")
    from rlvr import step_ledger as sl
    sl.record_step(ws, {"schema": "step-record/1",
                        "ts": "2026-10-24T11:59:30Z",
                        "session_id": "sess-w", "call_id": "c1",
                        "tool_name": "Bash", "duration_ms": 10})


def _verification(ws: Path, word: str = "verified") -> Path:
    p = ws / "runs" / "verification-C-9.md"
    p.write_text(f"verdict: {word}\n", encoding="utf-8")
    return p


def _rollout_rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "rollout-ledger.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _wire_rows(ws: Path) -> list[dict]:
    return [r for r in cl.read(ws, "settlement")
            if str(r.get("schema") or "") == "settlement-wire/1"]


def _provenance_rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "claims-provenance.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ------------------------------------------------- 1. the writer (blind)

def test_park_builds_blind_input_and_carries_no_poison(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    out = wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                                rules_path=rules)
    assert out["parked"] is True
    doc = json.loads((ws / "runs" / "settlement-input-C-9.json")
                     .read_text(encoding="utf-8"))
    blob = json.dumps(doc)
    assert doc["schema"] == "blind-settlement-input/1"
    assert doc["identity"] == "kunglao-settler"
    assert doc["artifacts"] == [
        {"path": "evidence/raw-step.bin",
         "sha256": doc["artifacts"][0]["sha256"]}]
    # every forbidden face stays out — the producer surfaces are not in
    # the doc in any shape (content, path list, or rules pin)
    for poison in ("POISON_", "worker-status", "verify-note",
                   "notes/", "facts/", "method-family",
                   "q-cell-log", "experience.jsonl", "verdict.json"):
        assert poison not in blob, poison


def test_park_is_deterministic_and_never_rewrites_verdict_window(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    first = wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                                  rules_path=rules)
    again = wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                                  rules_path=rules)
    assert again["parked"] is False  # identical bytes — no rewrite churn
    assert first["doc"] == again["doc"]
    # once the settler ruled, the ruling window is closed: a re-park
    # with DIFFERENT bytes refuses instead of blindside-invalidating
    (ws / "evidence" / "other.bin").write_bytes(b"second-artifact")
    (ws / "runs" / "settlement-verdict-C-9.json").write_text(
        json.dumps(_verdict()), encoding="utf-8")
    moved = wire.park_blind_input(ws, "C-9", ["evidence/other.bin"],
                                  rules_path=rules)
    assert moved["parked"] is False
    assert "verdict" in (moved.get("reason") or "")


def test_park_refuses_forbidden_faces_red(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    for forbidden in ("facts/F001.md", "notes/worker-report.md",
                      "runs/worker-status-w9.md",
                      "runs/verification-C-9.md",
                      "runs/method-family-log.jsonl",
                      "runs/q-cell-log.jsonl",
                      "runs/experience.jsonl",
                      "evidence/verdict.json",
                      "Runs/WORKER-STATUS-W9.MD"):  # case alias
        with pytest.raises(ValueError, match="excluded"):
            wire.park_blind_input(ws, "C-9", [forbidden], rules_path=rules)
    # an unsafe claim never becomes a parked path (traversal defense)
    with pytest.raises(ValueError):
        wire.park_blind_input(ws, "../escape", ["evidence/raw-step.bin"],
                              rules_path=rules)


def test_step_window_artifacts_exclude_forbidden_faces(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    # mechanical pin: whatever the window scan hands back, the writer
    # filters it through the scorer's exclusion wall before listing
    monkeypatch.setattr(
        wire, "_scan_window", lambda ws, since, until: [
            "evidence/raw-step.bin", "facts/F001.md",
            "notes/worker-report.md", "runs/worker-status-w9.md"])
    arts = wire.step_window_artifacts(
        ws, "2026-10-24T11:00:00Z",
        until=T0)
    assert arts == ["evidence/raw-step.bin"]


# --------------------------------------------- 2. the consumer (settle)

def test_settle_parked_routes_through_the_blind_stack(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                          rules_path=rules)
    (ws / "runs" / "settlement-verdict-C-9.json").write_text(
        json.dumps(_verdict()), encoding="utf-8")
    res = wire.settle_parked(ws, "C-9", oracle_verdict="", now=T0)
    assert res["settled"] is True, res
    # the reused validator stack: rail-clamped actions + oracle fields
    row = _rollout_rows(ws)[-1]
    settlement = row["settlement"]
    assert settlement["trajectory_actions"][0]["credit"] == 0.5
    assert "verifier_credit" in settlement
    # the liveness fingerprint: a settler-identity wire row landed
    rows = _wire_rows(ws)
    assert len(rows) == 1
    assert rows[0]["schema"] == "settlement-wire/1"
    assert rows[0]["identity"] == "kunglao-settler"
    assert rows[0]["settled"] is True


def test_settle_parked_refuses_sha_drift(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                          rules_path=rules)
    (ws / "runs" / "settlement-verdict-C-9.json").write_text(
        json.dumps(_verdict()), encoding="utf-8")
    # the bytes drift AFTER the ruling was blinded — settling over
    # unseen bytes fabricates credit: loud refusal, nothing written
    (ws / "evidence" / "raw-step.bin").write_bytes(b"TAMPERED")
    res = wire.settle_parked(ws, "C-9", oracle_verdict="", now=T0)
    assert res["settled"] is False
    assert "sha" in (res.get("reason") or "").lower()
    assert _rollout_rows(ws) == []
    # the refusal is a LOUD receipt (settler-identity row, settled=false)
    rows = _wire_rows(ws)
    assert len(rows) == 1
    assert rows[0]["settled"] is False
    assert "sha" in (rows[0].get("reason") or "").lower()


def test_settle_parked_refuses_identity_mismatch(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                          rules_path=rules)
    (ws / "runs" / "settlement-verdict-C-9.json").write_text(
        json.dumps(_verdict(identity="someone-else")), encoding="utf-8")
    res = wire.settle_parked(ws, "C-9", oracle_verdict="", now=T0)
    assert res["settled"] is False
    assert "identity" in (res.get("reason") or "")
    assert _rollout_rows(ws) == []


def test_settle_parked_refuses_hand_built_doc_with_forbidden_face(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    # a hand-built doc smuggles a producer narrative past the builder —
    # the SETTLEMENT gate must refuse it (the issue-687 wall, wired)
    smuggled = {"schema": "blind-settlement-input/1",
                "identity": "kunglao-settler", "claim": "C-9",
                "question": "", "rules": {"path": str(rules)},
                "artifacts": [{"path": "runs/worker-status-w9.md",
                               "sha256": "x"}]}
    (ws / "runs" / "settlement-input-C-9.json").write_text(
        json.dumps(smuggled), encoding="utf-8")
    (ws / "runs" / "settlement-verdict-C-9.json").write_text(
        json.dumps(_verdict()), encoding="utf-8")
    res = wire.settle_parked(ws, "C-9", oracle_verdict="", now=T0)
    assert res["settled"] is False
    assert "excluded" in (res.get("reason") or "")
    assert _rollout_rows(ws) == []


def test_pending_settlements_read_face(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                          rules_path=rules)
    pending = wire.pending_settlements(ws)
    assert [p["claim"] for p in pending] == ["C-9"]
    (ws / "runs" / "settlement-verdict-C-9.json").write_text(
        json.dumps(_verdict()), encoding="utf-8")
    assert wire.pending_settlements(ws) == []


# ------------------------------------------ 3. the issue-800/issue-809 alignment

def test_oracle_pass_mints_proven_through_claims_store(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                          rules_path=rules)
    (ws / "runs" / "settlement-verdict-C-9.json").write_text(
        json.dumps(_verdict()), encoding="utf-8")
    _verification(ws, "verified")
    res = wire.settle_parked(ws, "C-9", oracle_verdict="pass", now=T0)
    assert res["settled"] is True
    mint = res["claim_transition"]
    assert mint["ok"] is True
    assert (mint["from"], mint["to"]) == ("IN_PROGRESS", "PROVEN")
    prov = [r for r in _provenance_rows(ws)
            if r.get("event") == "settle_proven" and r.get("outcome") == "applied"]
    assert len(prov) == 1
    # the settler-identity row: the mint's actor is the blind grader
    assert prov[0]["actor"] == "settler:kunglao-settler"


def test_oracle_pass_without_passed_record_never_mints_proven(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                          rules_path=rules)
    (ws / "runs" / "settlement-verdict-C-9.json").write_text(
        json.dumps(_verdict()), encoding="utf-8")
    # the verifier REJECTED — the store's issue-809 wall must hold through
    # the blind face: no PASSED record, no PROVEN mint (fail-closed)
    _verification(ws, "rejected")
    res = wire.settle_parked(ws, "C-9", oracle_verdict="pass", now=T0)
    mint = res["claim_transition"]
    assert mint["ok"] is False
    assert "verification" in (mint.get("reason") or "")
    # the register is untouched — settlement never mints around a
    # failing verifier
    reg = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert "PROVEN" not in reg
    # the refusal is LOUD on the wire row, never silent
    rows = _wire_rows(ws)
    assert rows and rows[0]["claim_transition"]["ok"] is False


def test_oracle_fail_maps_settle_refuted(tmp_path):
    ws = _ws(tmp_path)
    rules = _rules(tmp_path)
    wire.park_blind_input(ws, "C-9", ["evidence/raw-step.bin"],
                          rules_path=rules)
    (ws / "runs" / "settlement-verdict-C-9.json").write_text(
        json.dumps(_verdict(credit=0.05)), encoding="utf-8")
    res = wire.settle_parked(ws, "C-9", oracle_verdict="fail", now=T0)
    assert res["settled"] is True
    mint = res["claim_transition"]
    assert mint["ok"] is True
    assert mint["to"] == "REFUTED"


# ---------------------------------------------------- 4. the eval gate

def test_eval_gate_defaults_blind_and_env_opts_in(monkeypatch):
    monkeypatch.delenv("KUNGLAO_EVAL_SETTLE", raising=False)
    assert wire.eval_settle_enabled() is False
    monkeypatch.setenv("KUNGLAO_EVAL_SETTLE", "1")
    assert wire.eval_settle_enabled() is True


def test_settle_step_blind_mode_skips_unblinded_judgment(tmp_path):
    ws = _ws(tmp_path)
    _seed_claim_dispatch(ws)
    out = sg.settle_step(ws, "sess-w", outcome="completed", now=T0,
                         blind=True)
    assert out is not None
    # the mechanical bookkeeping (hash-only act closure) still ran
    assert out["transition"] is not None
    # the UNBLINDED judgment legs did not: no producer-surface credit,
    # no crystallization, no belief row off facts/
    assert out.get("step_credit") is None
    assert out.get("credit_banked") is False
    assert out.get("crystallized") is None
    assert out.get("belief") is None


def test_round_closure_blind_mode_parks_and_skips_unblinded_credit(
        tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_EVAL_SETTLE", raising=False)
    ws = _ws(tmp_path)
    _seed_claim_dispatch(ws)
    sys.path.insert(0, str(ROOT / "hooks"))
    try:
        import round_closure as rc
        receipt = rc._kernel_faces(ws, session_id="sess-w",
                                   agent_id="w9") or {}
        # production default: the unblinded judgment is OFF...
        assert receipt.get("step_credit") is None
        # ...and the blind writer parked the input doc for the settler
        assert (ws / "runs" / "settlement-input-C-9.json").is_file()
        assert receipt["blind_settlement"]["parked_claims"] == ["C-9"]
    finally:
        sys.path.remove(str(ROOT / "hooks"))


def test_round_closure_eval_mode_keeps_legacy_face(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_EVAL_SETTLE", "1")
    ws = _ws(tmp_path)
    _seed_claim_dispatch(ws)
    sys.path.insert(0, str(ROOT / "hooks"))
    try:
        import round_closure as rc
        receipt = rc._kernel_faces(ws, session_id="sess-w",
                                   agent_id="w9") or {}
        # the explicit eval gate: the legacy unblinded face ran (the
        # issue-712 judgment legs live — the marker reads eval, not blind),
        # and nothing was parked
        assert receipt.get("blind") is False
        assert "blind_settlement" not in receipt
        assert not (ws / "runs" / "settlement-input-C-9.json").exists()
    finally:
        sys.path.remove(str(ROOT / "hooks"))
