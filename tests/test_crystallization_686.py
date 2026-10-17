# -*- coding: utf-8 -*-
"""tests/test_crystallization_686.py — the settlement writes knowledge
back (issue 686).

The transfer protocol's read side is wired (negative pools into the
sampler, the broadcast into the cross-task answer face) but the write
side is dead: no production caller records a class-level dead end or
broadcasts a proven method, and no derived row carries the provenance
the acceptance demands. The faces under test:

  - ``crystallize_settlement`` — the failed step lands ONE attributed
    class negative (deduped per step); the completed certified step
    broadcasts the method with the banked step credit (never the
    answer); honest gaps write nothing;
  - ``revoke_claim`` — an atomic rewrite that drops exactly the claim's
    derived rows from both derived stores;
  - the settle cage wires the write-back; the amendment flip revokes.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import crystallize  # noqa: E402
from rlvr import marl  # noqa: E402
from rlvr import strategy_store  # noqa: E402

import method_families  # noqa: E402

FAM = "upx-unpack"
TOOLS = ["upx", "strings"]


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "store"))


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _usage(ws: Path, claim: str, family: str = FAM) -> None:
    method_families.append_usage_row(ws, claim, family, "analyst",
                                     tools=list(TOOLS))


def _facts_index(ws: Path, claim: str, status: str = "PROVEN") -> None:
    facts = ws / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    (facts / "_INDEX.md").write_text(
        f"F-001 | {status} | {claim} | synthetic conclusion\n",
        encoding="utf-8")


def _neg_rows() -> list[dict]:
    return [r for r in marl.read_negatives()
            if str(r.get("claim_ref") or "")]


# ---- 1. the failed step lands an attributed dead end -----------------------

def test_blocked_step_records_attributed_negative(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-007")
    out = crystallize.crystallize_settlement(
        ws, claim="C-007", step_id="step-1", outcome="blocked")
    assert out["negative"] is True
    rows = _neg_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["method_family"] == FAM
    assert row["claim_ref"] == "C-007"
    assert row["step_ref"] == "step-1"
    assert row["tool_chain"] == "strings|upx"


def test_negative_pools_consumes_the_recorded_dead_end(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-007")
    crystallize.crystallize_settlement(
        ws, claim="C-007", step_id="step-1", outcome="blocked")
    pools = marl.negative_pools(ws, [FAM])
    assert FAM in pools
    assert pools[FAM].failure > 0.0


def test_settlement_replay_is_idempotent(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-007")
    crystallize.crystallize_settlement(
        ws, claim="C-007", step_id="step-1", outcome="blocked")
    again = crystallize.crystallize_settlement(
        ws, claim="C-007", step_id="step-1", outcome="blocked")
    assert again["negative"] is False
    assert again["reason"] == "duplicate"
    assert len(_neg_rows()) == 1


# ---- 2. the certified completion broadcasts the method ---------------------

def test_completed_certified_step_broadcasts_method(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-003")
    _facts_index(ws, "C-003", "PROVEN")
    out = crystallize.crystallize_settlement(
        ws, claim="C-003", step_id="step-9", outcome="completed",
        step_credit=0.8)
    assert out["broadcast"] is True
    rows = [r for r in strategy_store.load_rows()
            if str(r.get("claim") or "") == "C-003"]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "proven"
    assert row["method_family"] == FAM
    assert row["credit"] == pytest.approx(0.8)
    assert row["provenance"]["dispatch_id"] == "step-9"
    assert "answer" not in row


def test_broadcast_requires_banked_credit(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-003")
    _facts_index(ws, "C-003", "PROVEN")
    out = crystallize.crystallize_settlement(
        ws, claim="C-003", step_id="step-9", outcome="completed",
        step_credit=None)
    assert out["broadcast"] is False
    assert not [r for r in strategy_store.load_rows()
                if str(r.get("claim") or "") == "C-003"]


def test_completed_without_certified_answer_writes_nothing(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-003")
    _facts_index(ws, "C-003", "OPEN")
    out = crystallize.crystallize_settlement(
        ws, claim="C-003", step_id="step-9", outcome="completed",
        step_credit=0.5)
    assert out["broadcast"] is False
    assert strategy_store.load_rows() == []


def test_no_usage_row_writes_nothing(tmp_path):
    ws = _ws(tmp_path)
    out = crystallize.crystallize_settlement(
        ws, claim="C-404", step_id="step-1", outcome="blocked")
    assert out["negative"] is False
    assert out["reason"] == "no-method"
    assert marl.read_negatives() == []


# ---- 3. revocation ----------------------------------------------------------

def test_revoke_claim_removes_only_claim_rows(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-007")
    crystallize.crystallize_settlement(
        ws, claim="C-007", step_id="step-1", outcome="blocked")
    _usage(ws, "C-008")
    crystallize.crystallize_settlement(
        ws, claim="C-008", step_id="step-2", outcome="blocked")
    _usage(ws, "C-003", family="static-recon")
    _facts_index(ws, "C-003", "PROVEN")
    crystallize.crystallize_settlement(
        ws, claim="C-003", step_id="step-3", outcome="completed",
        step_credit=0.9)
    keep_neg = next(r for r in marl.read_negatives()
                    if r.get("claim_ref") == "C-008")
    keep_bcast = [r for r in strategy_store.load_rows()
                  if r.get("claim") == "C-003"]

    out = crystallize.revoke_claim(ws, "C-007")
    assert out["negatives_removed"] == 1
    remaining = {r.get("claim_ref") for r in marl.read_negatives()}
    assert remaining == {"C-008"}
    assert [r for r in strategy_store.load_rows()
            if r.get("claim") == "C-003"] == keep_bcast
    assert keep_neg in marl.read_negatives()


def test_revoke_claim_no_rows_is_noop(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-007")
    crystallize.crystallize_settlement(
        ws, claim="C-007", step_id="step-1", outcome="blocked")
    neg_before = marl.read_negatives()
    out = crystallize.revoke_claim(ws, "C-999")
    assert out == {"negatives_removed": 0, "broadcasts_removed": 0}
    assert marl.read_negatives() == neg_before


def test_revoke_claim_removes_the_broadcast(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-003")
    _facts_index(ws, "C-003", "PROVEN")
    crystallize.crystallize_settlement(
        ws, claim="C-003", step_id="step-1", outcome="completed",
        step_credit=0.8)
    assert len([r for r in strategy_store.load_rows()
                if r.get("claim") == "C-003"]) == 1
    out = crystallize.revoke_claim(ws, "C-003")
    assert out["broadcasts_removed"] == 1
    assert [r for r in strategy_store.load_rows()
            if r.get("claim") == "C-003"] == []


def test_worker_outcome_reads_retry_suffixed_log(tmp_path):
    sys.path.insert(0, str(ROOT / "hooks"))
    import round_closure as rc
    ws = _ws(tmp_path)
    runs = ws / "runs"
    (runs / "worker-status-C-011.md").write_text(
        "status: done\n", encoding="utf-8")
    (runs / "worker-status-C-011-2.md").write_text(
        "status: blocked\n", encoding="utf-8")
    assert rc._worker_outcome(ws, {"claim": "C-011"}) == "blocked"


def test_legacy_rows_without_provenance_still_read(tmp_path):
    ws = _ws(tmp_path)
    legacy = {"schema": marl.NEG_SCHEMA, "ts": "2026-10-17T00:00:00Z",
              "signature_class": marl.UNKNOWN_CLASS, "agent_type": None,
              "method_family": FAM, "tool_chain": "upx", "fails": 1}
    neg_path = marl.neg_store_path()
    neg_path.parent.mkdir(parents=True, exist_ok=True)
    with neg_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(legacy) + "\n")
    rows = marl.read_negatives()
    assert len(rows) == 1 and rows[0].get("claim_ref") is None
    assert FAM in marl.negative_pools(ws, [FAM])


# ---- 4. the production wiring ----------------------------------------------

def test_settle_step_wires_the_writeback(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-007")
    from rlvr import step_grain
    (ws / "runs" / "dispatch-launch-1.json").write_text(
        json.dumps({"schema": "dispatch-launch/1", "claim": "C-007",
                    "action_type": "dispatch", "attempt_id": "a1",
                    "ts": "2026-10-17T00:00:00Z"}), encoding="utf-8")
    receipt = step_grain.settle_step(ws, "sess-1", outcome="blocked")
    assert receipt is not None
    expected_step = step_grain.step_id_for("sess-1", 0)
    rows = _neg_rows()
    assert len(rows) == 1
    assert rows[0]["step_ref"] == expected_step
    assert rows[0]["claim_ref"] == "C-007"
    assert receipt.get("crystallized") is not None


# ---- 5. prior-inflation walls ----------------------------------------------

def test_second_certified_step_is_a_broadcast_duplicate(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-003")
    _facts_index(ws, "C-003", "PROVEN")
    first = crystallize.crystallize_settlement(
        ws, claim="C-003", step_id="step-1", outcome="completed",
        step_credit=0.8)
    second = crystallize.crystallize_settlement(
        ws, claim="C-003", step_id="step-2", outcome="completed",
        step_credit=0.3)
    assert first["broadcast"] is True
    assert second["broadcast"] is False and second["reason"] == "duplicate"
    assert len([r for r in strategy_store.load_rows()
                if r.get("claim") == "C-003"]) == 1


def test_zero_credit_broadcast_withheld(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-003")
    _facts_index(ws, "C-003", "PROVEN")
    out = crystallize.crystallize_settlement(
        ws, claim="C-003", step_id="step-1", outcome="completed",
        step_credit=0.0)
    assert out["broadcast"] is False and out["reason"] == "no-credit"
    assert strategy_store.load_rows() == []


def test_revoke_empty_claim_is_inert(tmp_path):
    ws = _ws(tmp_path)
    _usage(ws, "C-007")
    crystallize.crystallize_settlement(
        ws, claim="C-007", step_id="step-1", outcome="blocked")
    before = marl.read_negatives()
    out = crystallize.revoke_claim(ws, "")
    assert out == {"negatives_removed": 0, "broadcasts_removed": 0}
    assert marl.read_negatives() == before


def test_flipped_register_withholds_rebroadcast(tmp_path):
    import yaml
    ws = _ws(tmp_path)
    _usage(ws, "C-003")
    _facts_index(ws, "C-003", "PROVEN")
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": [{"id": "C-003", "status": "REFUTED"}]}),
        encoding="utf-8")
    out = crystallize.crystallize_settlement(
        ws, claim="C-003", step_id="step-1", outcome="completed",
        step_credit=0.8)
    assert out["broadcast"] is False and out["reason"] == "not-certified"
    assert strategy_store.load_rows() == []


# ---- 6. the production outcome derivation -----------------------------------

def test_worker_outcome_derives_from_status_log(tmp_path):
    sys.path.insert(0, str(ROOT / "hooks"))
    import round_closure as rc
    ws = _ws(tmp_path)
    runs = ws / "runs"
    (runs / "worker-status-C-009.md").write_text(
        "status: running\nstatus: blocked\n", encoding="utf-8")
    assert rc._worker_outcome(ws, {"claim": "C-009"}) == "blocked"
    (runs / "worker-status-C-010.md").write_text(
        "status: done\n", encoding="utf-8")
    assert rc._worker_outcome(ws, {"claim": "C-010"}) == "completed"
    assert rc._worker_outcome(ws, {"claim": "C-404"}) == "completed"
    assert rc._worker_outcome(ws, None) == "completed"


def test_amendment_flip_revokes_derived_rows(tmp_path):
    import yaml
    import settle_round_credit as src
    ws = _ws(tmp_path)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": [{"id": "C-007", "status": "REFUTED"}]}),
        encoding="utf-8")
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "OC-1.yaml").write_text(yaml.safe_dump({
        "id": "OC-1", "channel": "probe", "target_pq": "PQ-1",
        "hypothesis_ref": "H-001",
        "update_map": {"red_up": ["H-002"]},
        "expected": [{"field": "probe", "value": "observed",
                      "evidence_refs": ["E-001"]}],
        "mutations": [{"kind": "omit", "target": "E-001"}],
    }), encoding="utf-8")
    src._apply_case_observations(ws, [("OC-1", "C-007", True)],
                                 source="fresh")
    _usage(ws, "C-007")
    crystallize.crystallize_settlement(
        ws, claim="C-007", step_id="step-1", outcome="blocked")
    assert len(_neg_rows()) == 1

    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 1
    assert _neg_rows() == []
    assert out.get("revoked_claims") == ["C-007"]
