# -*- coding: utf-8 -*-
"""Issue #523 eval closure — the PQ spine, preflight, and the harness-failure
class (the 2026-10-06 smoke pilot's "先修实验闭环" batch).

Pilot evidence: loop-arm sessions entered with ZERO open claims (nothing to
dispatch on, no answers_question binding), and rows whose spine never
engaged (dispatch=0, q-cell-log absent) were still counted as capability
numbers. The closure contract pinned here:

  1. every eval task carries an explicit primary_questions set (authored
     or anchor-derived — never silent empty);
  2. the harness seeds ONE OPEN claim per question, answers_question-bound,
     ids continuing after the scaffold seeds, register written canonically;
  3. preflight refuses to start a session without open claims, a valid
     task oracle, and a passing hooks self-check;
  4. zero dispatches + zero q-cell observations classifies as
     harness_failure — excluded_from_performance, governance split out.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_dataset as ds  # noqa: E402
import eval_loop_runner as elr  # noqa: E402
from ws_yaml import canonical_dump  # noqa: E402

SMOKE_DIR = ROOT / "eval" / "v1" / "tasks" / "smoke"


# ---- face 1: the question set --------------------------------------------

def test_explicit_questions_pass_through_validated():
    task = ds.load_task(SMOKE_DIR / "go-arx-v1")
    pqs = ds.primary_questions(task)
    assert [q["id"] for q in pqs] == ["PQ-CONSTANTS", "PQ-DELIVER"]
    assert pqs[1]["reproduction"] is True
    assert pqs[1]["need"] == "yes_no_with_evidence"


def test_absent_questions_derive_the_completion_default():
    task = ds.load_task(SMOKE_DIR / "go-arx-v1")
    task.pop("primary_questions")
    pqs = ds.primary_questions(task)
    assert len(pqs) == 1
    assert pqs[0]["id"] == "PQ-DELIVER"
    assert pqs[0]["need"] == "yes_no_with_evidence"
    assert "success criterion" in pqs[0]["q"]
    # reproduction method arms the controlled-comparison bit
    assert pqs[0]["reproduction"] is True
    static = dict(task, anchors=dict(task["anchors"],
                                     verification_method="static"))
    assert ds.primary_questions(static)[0].get("reproduction") is not True


def test_malformed_explicit_questions_refuse():
    import pytest
    task = ds.load_task(SMOKE_DIR / "go-arx-v1")
    task["primary_questions"] = [{"id": "PQ-1"}]  # no q text
    with pytest.raises(ValueError):
        ds.primary_questions(task)


# ---- face 2: the seeded spine ---------------------------------------------

def _mini_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    reg = {"claims": [
        {"id": "C-001", "status": "PROVEN", "claim_class": "scaffold",
         "title": "lane", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 0, "promotion_attempts": 0,
         "depends_on": [], "evidence": "init"},
        {"id": "C-002", "status": "PROVEN", "claim_class": "scaffold",
         "title": "type", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 0, "promotion_attempts": 0,
         "depends_on": [], "evidence": "init"},
        {"id": "C-003", "status": "PROVEN", "claim_class": "scaffold",
         "title": "material", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 0, "promotion_attempts": 0,
         "depends_on": [], "evidence": "init"},
    ]}
    (ws / "claim-register.yaml").write_text(
        canonical_dump(reg), encoding="utf-8")
    (ws / "task_spec.yaml").write_text(canonical_dump({
        "lane": "algorithm",
        "goal_verbatim": "recover the constants",
        "success_criterion": "pairs reproduce byte-exact",
        "verification_method": "reproduction",
    }), encoding="utf-8")
    (ws / "task-oracle.yaml").write_text(canonical_dump({
        "task_text": "recover the constants",
        "open_items": [],
    }), encoding="utf-8")
    (ws / "runs").mkdir()
    return ws


def test_seed_question_spine_binds_claims_to_questions(tmp_path):
    ws = _mini_ws(tmp_path)
    task = ds.load_task(SMOKE_DIR / "go-arx-v1")
    seeded = elr.seed_question_spine(ws, task)
    assert seeded == ["C-004", "C-005"]

    reg = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    open_claims = [c for c in reg["claims"] if c["status"] == "OPEN"]
    assert [c["answers_question"] for c in open_claims] == \
        ["PQ-CONSTANTS", "PQ-DELIVER"]
    # canonical serialization: the register round-trips through the
    # single-writer face's own dump
    assert yaml.safe_load(canonical_dump(reg)) == reg

    spec = yaml.safe_load(
        (ws / "task_spec.yaml").read_text(encoding="utf-8"))
    assert [q["id"] for q in spec["primary_questions"]] == \
        ["PQ-CONSTANTS", "PQ-DELIVER"]

    # idempotent: a re-seed adds nothing
    assert elr.seed_question_spine(ws, task) == []


# ---- face 3: preflight -----------------------------------------------------

def test_preflight_passes_on_a_seeded_workspace(tmp_path):
    ws = _mini_ws(tmp_path)
    task = ds.load_task(SMOKE_DIR / "go-arx-v1")
    elr.seed_question_spine(ws, task)
    ok, reasons = elr.preflight(ws, run_selfcheck=lambda w: (0, "ok"))
    assert ok, reasons


def test_preflight_refuses_a_claimless_workspace(tmp_path):
    ws = _mini_ws(tmp_path)  # register holds only PROVEN scaffold seeds
    ok, reasons = elr.preflight(ws, run_selfcheck=lambda w: (0, "ok"))
    assert not ok
    assert any("open_claims" in r for r in reasons)


def test_preflight_refuses_bad_oracle_and_unwired_hooks(tmp_path):
    ws = _mini_ws(tmp_path)
    task = ds.load_task(SMOKE_DIR / "go-arx-v1")
    elr.seed_question_spine(ws, task)
    (ws / "task-oracle.yaml").write_text(
        canonical_dump({"task_text": "", "open_items": []}),
        encoding="utf-8")
    ok, reasons = elr.preflight(ws, run_selfcheck=lambda w: (0, "ok"))
    assert not ok and any("task_text" in r for r in reasons)

    (tmp_path / "w2").mkdir(exist_ok=True)
    ws2 = _mini_ws(tmp_path / "w2")
    elr.seed_question_spine(ws2, task)
    ok2, reasons2 = elr.preflight(ws2, run_selfcheck=lambda w: (1, "boom"))
    assert not ok2 and any("hooks_selfcheck" in r for r in reasons2)


# ---- face 4: the harness-failure class + the governance split --------------

def test_spineless_rows_classify_harness_failure():
    ok, reason = elr.classify_harness_failure(
        {"dispatch_count": 0}, q_cell_rows=0)
    assert ok and "spine never engaged" in reason
    assert not elr.classify_harness_failure(
        {"dispatch_count": 1}, q_cell_rows=0)[0]
    assert not elr.classify_harness_failure(
        {"dispatch_count": 0}, q_cell_rows=2)[0]


def test_governance_block_splits_from_the_verdict():
    g = elr.governance_block(
        {"converged": 1, "rounds": 2, "dispatch_count": 3,
         "proven_claims": 4, "oracle_green_rate": 1.0},
        status="exhausted", q_cell_rows=5)
    assert g == {
        "converged": True, "session_status": "exhausted", "rounds": 2,
        "dispatch_count": 3, "proven_claims": 4,
        "oracle_green_rate": 1.0, "q_cell_observations": 5,
    }


# ---- face 5: the cc-warm-context attribution arm ---------------------------

def test_warm_context_renders_train_material_and_cold_marker(tmp_path):
    train = tmp_path / "train"
    cards_dir = train / "runs" / "strategy-cards"
    cards_dir.mkdir(parents=True)
    # card ids follow the compose ledger contract:
    # <hex8>-(success_recipe|dead_path|exogenous_pitfall)-<hex12>
    cid = "deadbeef-dead_path-0123456789ab"
    (cards_dir / f"{cid}.yaml").write_text(
        f"id: {cid}\n"
        "kind: anti-hint\n"
        "text: on this family, strings-first probing loses to constant "
        "diffing\n"
        "backing_refs: [settle-1, settle-2]\n",
        encoding="utf-8")
    fam_log = train / "runs" / "method-family-log.jsonl"
    fam_log.parent.mkdir(parents=True, exist_ok=True)
    fam_log.write_text(
        '{"method_family": "constant-diffing", "outcome": "green"}\n'
        '{"method_family": "constant-diffing", "outcome": "red"}\n'
        '{"method_family": "strings-probe", "outcome": "green"}\n',
        encoding="utf-8")
    block = elr.warm_context_block(train)
    assert "CONTEXT CARDS" in block
    assert "anti-hint" in block and "constant diffing" in block
    assert "constant-diffing: 1/2" in block
    assert "strings-probe: 1/1" in block

    cold = elr.warm_context_block(tmp_path / "nowhere")
    assert "cold" in cold  # a source without train material is marked, not an error
