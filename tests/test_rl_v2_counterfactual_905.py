# -*- coding: utf-8 -*-
"""tests/test_rl_v2_counterfactual_905.py — the counterfactual
analysis harness's MECHANICS (issue 905).

Pinned here: pair construction (the dead arm rolls back, the live
sibling completes), the ledger-only ΔP reconstruction (step alignment,
start-of-rollout snapshot semantics, agreement with the real fold
face), matched-prefix alignment (hand-pinned lengths and contrasts,
empty-prefix exclusion counted), the statistic (hand-pinned Cohen's d,
degenerate-sample refusal) and the pre-registered decision rule
(synthetic aggregates on both sides of every threshold).

NEVER pinned here: the go/no-go OUTCOME of the real analysis — that is
data the harness emits with its numbers, not a structural property.
Every conclusion the report carries is labeled the mock-ledger tier.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop",
           ROOT / "experiments" / "learning-loop" / "sim"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import counterfactual_analysis as cf  # noqa: E402
import loop_sim  # noqa: E402
from rlvr import q_cells  # noqa: E402

ONE_SEED = (0,)
ONE_PAIR = (("dead-1", "offsets"),)


def _run_small(root, *, reps: int = 1) -> dict:
    return cf.run_analysis(root, seeds=ONE_SEED, pairs=ONE_PAIR,
                           reps=reps)


# ------------------------------------------------ pair construction

def test_pair_construction_arms_land_on_their_outcomes(tmp_path):
    report = _run_small(tmp_path / "pairs")
    assert report["n_pairs_generated"] == 1
    pair = report["per_pair"][0]
    assert pair["failed_terminal"] == "rolled_back"
    assert pair["success_terminal"] == "completed"


def test_failed_arm_has_only_unverified_steps(tmp_path):
    ws = tmp_path / "steps"
    cf.generate_pairs(ws, seeds=ONE_SEED, pairs=ONE_PAIR, reps=1)
    records = cf.reconstruct_rollouts(ws / "cf-seed-0")
    failed = next(r for r in records.values()
                  if r.rollout_id.endswith("-dead"))
    assert failed.terminal == "rollback"
    assert failed.steps
    assert all(not st.verified and st.r_t == 0.0
               for st in failed.steps)
    live = next(r for r in records.values()
                if r.rollout_id.endswith("-live"))
    assert live.terminal == "terminate_rollout"
    assert any(st.verified and st.r_t == 1.0 for st in live.steps)


# -------------------------------------------- ledger-only replay

def test_replayed_mass_matches_the_real_fold_face(tmp_path):
    ws = tmp_path / "fold"
    cf.generate_pairs(ws, seeds=ONE_SEED, pairs=ONE_PAIR, reps=1)
    # the γ=1.0 accumulation, run to the stream's end, must equal the
    # real fold face exactly (every situation the ledger touched)
    replayed = cf.settled_mass_by_signature(ws / "cf-seed-0")
    view = q_cells.fold(q_cells.default_store(ws / "cf-seed-0"),
                        gamma=cf.GAMMA)
    real: dict[str, dict[str, tuple[float, float]]] = {}
    for (sig, key), cell in view.cells.items():
        real.setdefault(sig, {})[q_cells.family_of_action(key)] = \
            (cell.success, cell.failure)
    assert set(replayed) == set(real)
    for sig, fams in replayed.items():
        for fam, (s, f) in fams.items():
            assert (round(real[sig][fam][0], 9),
                    round(real[sig][fam][1], 9)) \
                == (round(s, 9), round(f, 9))


def test_snapshot_is_start_of_rollout_not_final_state(tmp_path):
    ws = tmp_path / "snap"
    manifest = cf.generate_pairs(ws, seeds=ONE_SEED, pairs=ONE_PAIR,
                                 reps=2)
    records = cf.reconstruct_rollouts(ws / "cf-seed-0")
    first_dead = records[manifest[0]["pairs"][0]["failed_rollout_id"]]
    second_dead = records[manifest[0]["pairs"][1]["failed_rollout_id"]]
    # the dead situation is cold: the FIRST dead rollout decided under
    # an empty snapshot; the SECOND decided under the first's banked
    # failures — one (0, 1) mass per draw the first rollout spent
    assert first_dead.snapshot == {}
    assert first_dead.profile == pytest.approx(
        tuple(0.5 for _ in first_dead.steps))
    assert second_dead.snapshot
    drawn = [st.family for st in first_dead.steps]
    assert set(second_dead.snapshot) == set(drawn)
    for fam, mass in second_dead.snapshot.items():
        assert mass == (0.0, float(drawn.count(fam)))
    for st, dp in zip(second_dead.steps, second_dead.profile):
        # a family the first rollout never drew prices at the wide
        # prior (the replay's (0, 0) fallback) — exactly 0.5
        assert dp == pytest.approx(
            cf.posterior_mean(
                second_dead.snapshot.get(st.family, (0.0, 0.0))),
            abs=1e-6)
    assert all(dp <= 0.5 for dp in second_dead.profile)


def test_profile_is_step_aligned(tmp_path):
    ws = tmp_path / "align"
    cf.generate_pairs(ws, seeds=ONE_SEED, pairs=ONE_PAIR, reps=1)
    records = cf.reconstruct_rollouts(ws / "cf-seed-0")
    for rec in records.values():
        assert len(rec.profile) == len(rec.steps)
        for dp in rec.profile:
            assert 0.0 < dp <= 1.0


def test_step_no_parser_shapes():
    assert cf._step_no_of("ro-x-s03") == 3
    assert cf._step_no_of("ro-x-terminal") is None
    assert cf._step_no_of("ro-x-s00") == 0


# ------------------------------------------- matched-prefix alignment

def _rec(rid, terminal, families, verified_flags, profile):
    steps = tuple(cf.StepRecord(
        step_no=i + 1, family=fam, r_t=0.0 if not ver else 1.0,
        verified=ver)
        for i, (fam, ver) in enumerate(zip(families, verified_flags)))
    return cf.RolloutRecord(rollout_id=rid, signature="sig",
                            terminal=terminal, steps=steps,
                            snapshot={}, profile=tuple(profile))


def test_matched_prefix_length_and_contrast_hand_pinned():
    failed = _rec("f", "rollback", ["a", "b", "c"],
                  [False, False, False], [0.4, 0.4, 0.4])
    success = _rec("s", "terminate_rollout", ["a", "b"],
                   [False, True], [0.6, 0.9])
    contrast = cf.matched_prefix_contrast(failed, success)
    assert contrast.usable
    # the success arm's pre-divergence prefix is exactly its step 1
    assert contrast.prefix_len == 1
    assert contrast.contrast == pytest.approx(0.6 - 0.4)
    assert contrast.prefix_r_t_failed == (0.0,)
    assert contrast.prefix_r_t_success == (0.0,)


def test_prefix_capped_by_the_shorter_arm():
    failed = _rec("f", "rollback", ["a"], [False], [0.3])
    success = _rec("s", "terminate_rollout", ["b", "a"],
                   [False, True], [0.7, 0.9])
    contrast = cf.matched_prefix_contrast(failed, success)
    assert contrast.usable
    assert contrast.prefix_len == 1
    assert contrast.contrast == pytest.approx(0.7 - 0.3)


def test_empty_prefix_pair_is_unusable_and_counted():
    failed = _rec("f", "rollback", ["a", "b", "c"],
                  [False, False, False], [0.4, 0.4, 0.4])
    success = _rec("s", "terminate_rollout", ["a"],
                   [True], [0.9])
    contrast = cf.matched_prefix_contrast(failed, success)
    assert not contrast.usable
    assert contrast.reason == "empty matched prefix"


def test_structural_mismatch_is_unusable():
    failed = _rec("f", "terminate_rollout", ["a"], [False], [0.4])
    success = _rec("s", "terminate_rollout", ["a", "b"],
                   [False, True], [0.6, 0.9])
    contrast = cf.matched_prefix_contrast(failed, success)
    assert not contrast.usable
    assert contrast.reason == "failed arm did not roll back"


# --------------------------------------------------- the statistic

def test_cohen_d_hand_pinned():
    assert cf.cohen_d([0.2, 0.4, 0.6]) == pytest.approx(2.0)
    assert cf.cohen_d([0.5]) is None
    assert cf.cohen_d([0.3, 0.3, 0.3]) is None  # zero variance
    assert cf.cohen_d([]) is None


def test_decision_rule_thresholds_synthetic():
    go = cf.decide(0.8, [1, 1, 1, 1, 1], 20)
    assert go["outcome"] == "GO"
    small_effect = cf.decide(0.3, [1, 1, 1, 1, 1], 20)
    assert small_effect["outcome"] == "NO-GO"
    weak_consensus = cf.decide(0.8, [1, 1, 1, -1, -1], 20)
    assert weak_consensus["outcome"] == "NO-GO"
    tiny_sample = cf.decide(0.8, [1, 1, 1, 1, 1], 5)
    assert tiny_sample["outcome"] == "NO-GO"
    degenerate = cf.decide(None, [1, 1, 1, 1, 1], 20)
    assert degenerate["outcome"] == "NO-GO"
    assert all(r["reasons"] for r in
               (go, small_effect, weak_consensus, tiny_sample,
                degenerate))


def test_decision_rule_records_its_thresholds():
    rule = cf.decide(0.8, [1, 1, 1, 1, 1], 20)["rule"]
    assert rule["min_usable_pairs"] == cf.MIN_USABLE_PAIRS
    assert rule["effect_size_floor"] == cf.EFFECT_SIZE_FLOOR
    assert rule["min_seed_sign_consensus"] \
        == cf.MIN_SEED_SIGN_CONSENSUS


# --------------------------------------------- the full report shape

def test_report_determinism_same_seed(tmp_path):
    a = _run_small(tmp_path / "a")
    b = _run_small(tmp_path / "b")
    assert a == b


def test_report_carries_tier_label_question_and_design(tmp_path):
    report = _run_small(tmp_path / "shape")
    assert report["tier"] == cf.MOCK_TIER_LABEL
    assert report["question"] == cf.QUESTION
    assert report["design"]["situation_pairs"] == [
        {"dead": "dead-1", "live": "offsets"}]
    assert report["verdict"]["outcome"] in ("GO", "NO-GO")
    assert report["verdict"]["reasons"]
    for pair in report["per_pair"]:
        assert isinstance(pair["usable"], bool)


def test_flat_worker_prefix_streams_are_unverified(tmp_path):
    report = _run_small(tmp_path / "flat", reps=2)
    for pair in report["per_pair"]:
        if not pair["usable"]:
            continue
        assert pair["prefix_r_t_failed"] == [0.0] * pair["prefix_len"]
        assert pair["prefix_r_t_success"] == [0.0] * pair["prefix_len"]


def test_workspace_bootstrap_idempotent_for_replay(tmp_path):
    ws = tmp_path / "boot"
    cf.generate_pairs(ws, seeds=ONE_SEED, pairs=ONE_PAIR, reps=1)
    rows_first = len(q_cells.trajectory_rows(ws / "cf-seed-0"))
    loop_sim._bootstrap(ws / "cf-seed-0")
    assert len(q_cells.trajectory_rows(ws / "cf-seed-0")) == rows_first
