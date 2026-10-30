# -*- coding: utf-8 -*-
"""tests/test_rl_v2_progress_898.py — the evidence-ladder progress face (898).

RED-first pins for the learning loop's structured subgoal states:

  1. P(s) — the deterministic status-weighted sum over the goal tree's
     subgoals, weights IMPORTED from step_credit's CREDIT_BY_CLASS
     ladder (no new fitted parameters);
  2. monotonicity — a subgoal moving unverified -> cross-validated
     strictly raises P; within the cross-validated band P is flat
     (weakly monotone) — the ladder's own pricing;
  3. the NEGATIVE correction — a reproduced rule-out prices at FULL
     cross-validated strength (1.0, nonzero: 排除错误方向是进展);
     REFUTED prices exactly 0.0 (the hypothesis was wrong);
  4. delta_P — exact deltas; a subgoal BORN into the tree banks nothing
     at the unverified floor (the spawn-farm wall); a REMOVED subgoal
     claws its mass back;
  5. R(tau) = delta_P - lam * cost, exact;
  6. V wiring — values_from(P_history): empty or flat history -> None
     (the pinned cold start: A == R exactly); a moving history -> the
     array credit.advantage.advantages consumes;
  7. the evaluation document `trajectory-evaluation/1` — fail-closed
     validator; the banking rule: a proposal into a cross-validated
     status MUST carry evidence_refs (the #799 posture — an LLM-claimed
     transition without evidence class banks NOTHING); the
     single-authority wall: an evaluation full of LLM scores but no
     evidence-backed proposals moves P by exactly 0;
  8. the stagnation face — N consecutive flat segments fire an
     ADVISORY `stagnation-advice/1` receipt (never a terminator
     decision), idempotent (pure function, no clock), the N-1 boundary
     does not fire;
  9. ledger landing — g_i transitions and evaluations append q-cell
     observation rows with source="state" and credit=None (no credit
     column -> no posterior mass);
 10. fail-closed reject pins (garbage statuses/refs/confidence raise).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from credit import advantage  # noqa: E402
from rlvr import q_cells  # noqa: E402
from state import evaluation, progress, stagnation  # noqa: E402

_REF = "evidence/F001.md#L10-L12"


def _g(gid: str, status: str, refs=(_REF,), conf: float = 0.8):
    return progress.Subgoal(id=gid, status=status,
                            evidence_refs=refs, confidence=conf)


def _legal_doc(**over):
    doc = {
        "schema": "trajectory-evaluation/1",
        "new_facts": ["F001"],
        "validated_hypotheses": ["H-01"],
        "rejected_hypotheses": [],
        "unresolved_questions": ["Q-02"],
        "exploration_progress": 0.4,
        "redundancy": 0.1,
        "possible_new_directions": ["try lane B"],
        "proposals": [
            {"subgoal_id": "g1", "to_status": "PROVEN",
             "evidence_refs": [_REF]},
        ],
    }
    doc.update(over)
    return doc


# ------------------------------------------------------------- the P face

def test_p_is_exact_status_weighted_sum():
    tree = [_g("g1", "UNVERIFIED", refs=()),
            _g("g2", "PROVEN"),
            _g("g3", "NEGATIVE"),
            _g("g4", "REFUTED", refs=())]
    assert progress.P(tree) == pytest.approx(0.3 + 1.0 + 1.0 + 0.0)


def test_p_weights_borrow_the_step_credit_ladder():
    # the weights are IMPORTED, not fitted: the cross-validated band
    # prices at CREDIT_BY_CLASS["cross_validated"], the floor at
    # CREDIT_BY_CLASS["unverified"], REFUTED at CREDIT_BY_CLASS["refuted"]
    for status in progress.STATUSES:
        assert progress.STATUS_WEIGHTS[status] in (0.0, 0.3, 1.0)
    assert progress.STATUS_WEIGHTS["NEGATIVE"] == 1.0
    assert progress.STATUS_WEIGHTS["REFUTED"] == 0.0
    assert progress.STATUS_WEIGHTS["UNVERIFIED"] == 0.3
    assert progress.STATUS_WEIGHTS["PROVEN"] == 1.0
    assert progress.STATUS_WEIGHTS["VERIFIED"] == 1.0


def test_p_monotone_under_ladder_climb():
    base = [_g("g1", "UNVERIFIED", refs=()), _g("g2", "UNVERIFIED", refs=())]
    p_floor = progress.P(base)
    for up in ("VERIFIED", "PROVEN", "NEGATIVE"):
        climbed = [_g("g1", up), _g("g2", "UNVERIFIED", refs=())]
        assert progress.P(climbed) > p_floor
    # within the cross-validated band the ladder's own pricing is flat
    assert progress.P([_g("g1", "VERIFIED")]) \
        == progress.P([_g("g1", "PROVEN")])


def test_negative_prices_nonzero_rule_out_is_progress():
    # 排除错误方向是进展: a reproduced proven-negative finding is
    # cross-validated STRENGTH — it must NOT price at REFUTED's 0.0
    assert progress.status_weight("NEGATIVE") == 1.0
    assert progress.status_weight("NEGATIVE") > 0.0
    assert progress.status_weight("NEGATIVE") \
        != progress.status_weight("REFUTED")


def test_refuted_prices_zero():
    assert progress.status_weight("REFUTED") == 0.0


def test_p_empty_tree_is_zero():
    assert progress.P([]) == 0.0


def test_p_deterministic_under_reordering():
    tree = [_g("g1", "PROVEN"), _g("g2", "UNVERIFIED", refs=())]
    assert progress.P(tree) == progress.P(list(reversed(tree)))


# ------------------------------------------------------------ the ΔP face

def test_delta_p_exact_floor_to_proven():
    before = [_g("g1", "UNVERIFIED", refs=())]
    after = [_g("g1", "PROVEN")]
    assert progress.delta_P(before, after) == pytest.approx(0.7)


def test_delta_p_zero_when_tree_unchanged():
    tree = [_g("g1", "PROVEN"), _g("g2", "UNVERIFIED", refs=())]
    assert progress.delta_P(tree, tree) == 0.0


def test_delta_p_birth_banks_nothing_at_the_floor():
    # the spawn-farm wall: a new subgoal enters AT the floor; spawning
    # subgoals without climbing them must not mint progress
    before = [_g("g1", "PROVEN")]
    after = [_g("g1", "PROVEN"),
             _g("g2", "UNVERIFIED", refs=())]
    assert progress.delta_P(before, after) == 0.0


def test_delta_p_birth_direct_to_verified_banks_only_the_climb():
    before = [_g("g1", "PROVEN")]
    after = [_g("g1", "PROVEN"), _g("g2", "VERIFIED")]
    assert progress.delta_P(before, after) == pytest.approx(0.7)


def test_delta_p_removal_claws_back():
    before = [_g("g1", "PROVEN"), _g("g2", "VERIFIED")]
    after = [_g("g1", "PROVEN")]
    assert progress.delta_P(before, after) == pytest.approx(-1.0)


def test_delta_p_refuted_move_is_zero_not_negative_progress():
    # REFUTED anchors 0.0 and UNVERIFIED anchors 0.3: the floor -> the
    # refuted status LOWERS P (the claim-terminal clawback), it never
    # mints progress
    before = [_g("g1", "UNVERIFIED", refs=())]
    after = [_g("g1", "REFUTED", refs=())]
    assert progress.delta_P(before, after) == pytest.approx(-0.3)


# --------------------------------------------------------- the reward face

def test_reward_is_delta_p_minus_lam_cost():
    before = [_g("g1", "UNVERIFIED", refs=())]
    after = [_g("g1", "PROVEN")]
    assert progress.reward(before, after, 2.0, lam=0.1) \
        == pytest.approx(0.7 - 0.2)


def test_reward_rejects_garbage_cost_and_lambda():
    before = [_g("g1", "UNVERIFIED", refs=())]
    after = [_g("g1", "PROVEN")]
    with pytest.raises(ValueError):
        progress.reward(before, after, -1.0, lam=0.1)
    with pytest.raises(ValueError):
        progress.reward(before, after, 1.0, lam=-0.1)
    with pytest.raises(ValueError):
        progress.reward(before, after, float("nan"), lam=0.1)


# ----------------------------------------------------------- the V wiring

def test_values_from_empty_history_is_none_cold_start():
    assert progress.values_from([]) is None


def test_values_from_flat_history_is_none_a_equals_r_pinned():
    # no g_i transitions -> V == 0 -> the advantage face's pinned
    # identity path: A == R EXACTLY (the expected early-training shape)
    returns = np.array([0.4, -0.2, 1.0])
    values = progress.values_from([0.3, 0.3, 0.3])
    assert values is None
    a = advantage.advantages(returns, values)
    assert np.array_equal(a, returns)


def test_values_from_moving_history_feeds_the_baseline():
    history = [0.3, 1.0, 1.3]
    values = progress.values_from(history)
    assert values is not None
    assert values.shape == (3,)
    returns = np.array([1.0, 1.0, 1.0])
    a = advantage.advantages(returns, values)
    assert a[0] == pytest.approx(0.7)
    assert a[1] == pytest.approx(0.0)


def test_values_from_rejects_non_finite_history():
    with pytest.raises(ValueError):
        progress.values_from([0.3, float("nan")])


# ------------------------------------------------- the evaluation document

def test_legal_evaluation_document_validates():
    doc = _legal_doc()
    assert evaluation.validate_evaluation(doc) is doc


def test_evaluation_missing_field_refused():
    doc = _legal_doc()
    del doc["redundancy"]
    with pytest.raises(evaluation.EvaluationError):
        evaluation.validate_evaluation(doc)


def test_evaluation_wrong_schema_refused():
    with pytest.raises(evaluation.EvaluationError):
        evaluation.validate_evaluation(_legal_doc(schema="episode/1"))


def test_evaluation_scores_must_be_unit_interval():
    for field in ("exploration_progress", "redundancy"):
        with pytest.raises(evaluation.EvaluationError):
            evaluation.validate_evaluation(_legal_doc(**{field: 1.5}))
        with pytest.raises(evaluation.EvaluationError):
            evaluation.validate_evaluation(_legal_doc(**{field: "high"}))


def test_evaluation_list_fields_must_be_string_lists():
    with pytest.raises(evaluation.EvaluationError):
        evaluation.validate_evaluation(
            _legal_doc(rejected_hypotheses=["H-01", 42]))


def test_proposal_into_cross_validated_requires_evidence_refs():
    # the #799 posture pinned at the proposal wall: an LLM-claimed
    # transition without the evidence class is REFUSED — it banks nothing
    doc = _legal_doc(proposals=[
        {"subgoal_id": "g1", "to_status": "PROVEN", "evidence_refs": []}])
    with pytest.raises(evaluation.EvaluationError):
        evaluation.validate_evaluation(doc)
    doc = _legal_doc(proposals=[
        {"subgoal_id": "g1", "to_status": "VERIFIED"}])
    with pytest.raises(evaluation.EvaluationError):
        evaluation.validate_evaluation(doc)


def test_proposal_to_unverified_reset_needs_no_refs():
    doc = _legal_doc(proposals=[
        {"subgoal_id": "g1", "to_status": "UNVERIFIED",
         "evidence_refs": []}])
    evaluation.validate_evaluation(doc)


def test_proposal_status_must_be_on_the_ladder():
    doc = _legal_doc(proposals=[
        {"subgoal_id": "g1", "to_status": "GOLD",
         "evidence_refs": [_REF]}])
    with pytest.raises(evaluation.EvaluationError):
        evaluation.validate_evaluation(doc)


def test_apply_proposals_moves_only_evidence_backed_entries():
    tree = (_g("g1", "UNVERIFIED", refs=()), _g("g2", "UNVERIFIED", refs=()))
    doc = _legal_doc(proposals=[
        {"subgoal_id": "g1", "to_status": "PROVEN",
         "evidence_refs": [_REF, "evidence/F002.md#L1"]},
    ])
    moved = evaluation.apply_proposals(tree, doc)
    assert moved[0].status == "PROVEN"
    assert "evidence/F002.md#L1" in moved[0].evidence_refs
    assert moved[1] == tree[1]                      # untouched subgoal
    assert tree[0].status == "UNVERIFIED"           # the INPUT is not mutated
    assert progress.delta_P(tree, moved) == pytest.approx(0.7)


def test_apply_proposals_absent_proposals_key_is_the_empty_path():
    """A scores-only document (the common no-proposals case) applies
    ZERO moves — the seam returns the tree unchanged, never a
    KeyError (the review's M1 pin)."""
    tree = (_g("g1", "UNVERIFIED", refs=()),)
    doc = _legal_doc()
    doc.pop("proposals", None)              # the scores-only shape
    moved = evaluation.apply_proposals(tree, doc)
    assert moved == tree                    # identical, no moves


def test_apply_proposals_unknown_subgoal_refused():
    tree = (_g("g1", "UNVERIFIED", refs=()),)
    doc = _legal_doc(proposals=[
        {"subgoal_id": "ghost", "to_status": "PROVEN",
         "evidence_refs": [_REF]}])
    with pytest.raises(evaluation.EvaluationError):
        evaluation.apply_proposals(tree, doc)


def test_apply_proposals_duplicate_target_refused():
    tree = (_g("g1", "UNVERIFIED", refs=()),)
    doc = _legal_doc(proposals=[
        {"subgoal_id": "g1", "to_status": "VERIFIED",
         "evidence_refs": [_REF]},
        {"subgoal_id": "g1", "to_status": "PROVEN",
         "evidence_refs": [_REF]}])
    with pytest.raises(evaluation.EvaluationError):
        evaluation.apply_proposals(tree, doc)


def test_single_authority_wall_scores_without_proposals_bank_zero():
    # the LLM's own progress/redundancy scores are TELEMETRY: a fully
    # scored evaluation with no evidence-backed proposals moves P by
    # exactly 0 (LLM proposes, the ladder disposes)
    tree = (_g("g1", "UNVERIFIED", refs=()),)
    doc = _legal_doc(exploration_progress=1.0, redundancy=0.0,
                     proposals=[])
    moved = evaluation.apply_proposals(tree, doc)
    assert progress.P(moved) == progress.P(tree)
    assert progress.delta_P(tree, moved) == 0.0


# ------------------------------------------------------- the stagnation face

def test_stagnation_fires_on_n_flat_segments():
    receipt = stagnation.stagnation_receipt([0.7, 0.0, 0.0],
                                            rollout_id="ro-1")
    assert receipt is not None
    assert receipt["schema"] == "stagnation-advice/1"
    assert receipt["rollout_id"] == "ro-1"
    assert receipt["flat_segments"] == 2
    assert receipt["advice"]["action"] == "replan"
    assert receipt["advice"]["down_weight_current_direction"] is True
    assert receipt["advice"]["widen_candidates"] is True
    assert receipt["terminates"] is False     # advisory ONLY — the
    # β terminator decides; this face never ends a rollout by itself


def test_stagnation_n_minus_one_boundary_does_not_fire():
    n = stagnation.STAGNATION_N
    assert stagnation.stagnation_receipt([0.0] * (n - 1),
                                         rollout_id="ro-1") is None


def test_stagnation_real_move_breaks_the_streak():
    n = stagnation.STAGNATION_N
    assert stagnation.stagnation_receipt(
        [0.0] * (n - 1) + [0.7], rollout_id="ro-1") is None
    assert stagnation.stagnation_receipt(
        [0.7] + [0.0] * n, rollout_id="ro-1") is not None


def test_stagnation_receipt_is_idempotent_and_clock_free():
    a = stagnation.stagnation_receipt([0.0, 0.0], rollout_id="ro-1")
    b = stagnation.stagnation_receipt([0.0, 0.0], rollout_id="ro-1")
    assert a == b                              # byte-identical: pure fn
    for receipt in (a, b):
        assert "ts" not in receipt             # never clock-derived


def test_stagnation_short_history_does_not_fire():
    assert stagnation.stagnation_receipt([], rollout_id="ro-1") is None


def test_stagnation_rejects_garbage_deltas():
    with pytest.raises(ValueError):
        stagnation.stagnation_receipt([0.0, float("nan")],
                                      rollout_id="ro-1")
    with pytest.raises(ValueError):
        stagnation.stagnation_receipt([0.0, True], rollout_id="ro-1")
    with pytest.raises(ValueError):
        stagnation.stagnation_receipt([0.0, "flat"], rollout_id="ro-1")
    with pytest.raises(ValueError):
        stagnation.stagnation_receipt([0.0], rollout_id="")


# --------------------------------------------------------- fail-closed pins

def test_garbage_status_refused():
    with pytest.raises(ValueError):
        _g("g1", "GOLD")
    with pytest.raises(ValueError):
        _g("g1", "proven")          # the closed vocab is EXACT uppercase
    with pytest.raises(ValueError):
        _g("g1", 3)


def test_cross_validated_status_without_evidence_refused():
    # the #799 wall at the record: claiming cross-validated strength
    # with zero byte-anchored evidence is structural garbage
    for status in ("PROVEN", "VERIFIED", "NEGATIVE"):
        with pytest.raises(ValueError):
            _g("g1", status, refs=())


def test_garbage_evidence_refs_refused():
    with pytest.raises(ValueError):
        _g("g1", "UNVERIFIED", refs="evidence/F001.md")   # bare string
    with pytest.raises(ValueError):
        _g("g1", "UNVERIFIED", refs=("",))
    with pytest.raises(ValueError):
        _g("g1", "UNVERIFIED", refs=(42,))


def test_garbage_confidence_refused():
    with pytest.raises(ValueError):
        _g("g1", "UNVERIFIED", conf=1.5)
    with pytest.raises(ValueError):
        _g("g1", "UNVERIFIED", conf=True)
    with pytest.raises(ValueError):
        _g("g1", "UNVERIFIED", conf=float("nan"))


def test_duplicate_subgoal_ids_refused():
    tree = [_g("g1", "PROVEN"), _g("g1", "VERIFIED")]
    with pytest.raises(ValueError):
        progress.P(tree)
    with pytest.raises(ValueError):
        progress.delta_P(tree, tree)


# --------------------------------------------------------- the ledger faces

def test_record_transition_appends_credit_free_state_row(tmp_path):
    ws = tmp_path / "ws"
    before = [_g("g1", "UNVERIFIED", refs=())]
    after = [_g("g1", "PROVEN")]
    out = progress.record_transition(ws, before=before, after=after,
                                     claim="C-001", dispatch_id="d-1")
    assert out["appended"] is True
    row = out["row"]
    assert row["schema"] == q_cells.OBS_SCHEMA
    assert row["source"] == "state"
    assert row["credit"] is None          # no credit column -> no
    # posterior mass: the state face is telemetry, never the fold's feed
    assert row["claim"] == "C-001"
    assert row["dispatch_id"] == "d-1"


def test_record_transition_signature_is_content_derived(tmp_path):
    ws = tmp_path / "ws"
    before = [_g("g1", "UNVERIFIED", refs=())]
    after = [_g("g1", "PROVEN")]
    row_a = progress.record_transition(ws, before=before, after=after)
    row_b = progress.record_transition(ws, before=before, after=after)
    assert row_a["row"]["signature_hash"] \
        == row_b["row"]["signature_hash"]      # #251: never clock-derived
    assert math.isfinite(float(
        row_a["row"]["fingerprint"].split("=")[1]))


def test_record_evaluation_appends_validated_credit_free_row(tmp_path):
    ws = tmp_path / "ws"
    out = evaluation.record_evaluation(ws, _legal_doc(), claim="C-001")
    assert out["appended"] is True
    row = out["row"]
    assert row["source"] == "state"
    assert row["credit"] is None
    with pytest.raises(evaluation.EvaluationError):
        evaluation.record_evaluation(ws, _legal_doc(schema="nope/1"))
