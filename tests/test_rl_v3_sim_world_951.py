# -*- coding: utf-8 -*-
"""tests/test_rl_v3_sim_world_951.py — the dual-objective sim world
(#951): pure assertions over the world, its metrics, and the five-config
battery's fixed-seed verdicts.

The card is the EVIDENCE GATE for the rl-v3 direction layer: the P8
round-1 sample (a forged PASS with every mechanical face green while
the direction was wrong — the co-located grader) is reproduced
in-silico, then the proposed mechanisms are measured against it:

  the WORLD  three direction arms (true-solve / leak-proxy /
             dead-plausible); the reward faces are the REAL production
             faces (step_credit's #712 table, per_dispatch's #932
             measured potential, the q_cells ledger + fold) driven
             unmodified; the environment is the only mock.
  config 1   baseline DTS + measured potential — the collapse onto the
             leak arm REPRODUCES (pinned; if it ever stops reproducing,
             the diagnosis is falsified and this test SHOULD fail).
  config 2   the 0.3 flat floor control — the gradient dies (pinned:
             worse on surrender, completion below every mechanism).
  configs
  3 / 4 / 5  the pre-registered pass criteria: leak-collapse
             significantly below baseline AND premature-surrender not
             raised. 3 and 5 PASS; 4 (racing alone) is
             NOT-for-production — its posterior-collapse elimination
             can never unmask an arm whose unanchored signal is
             genuinely positive (the recorded finding).

Statistical discipline mirrors tests/test_proof_battery_v3_887.py:
fixed seeds end to end, per-batch strict ordering, pooled 3-sd margins,
exact pins wherever the arithmetic is exact. Determinism: no wall clock
in any decision (counter-clock timestamps), no shared mutable RNG.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop",
           ROOT / "experiments" / "learning-loop" / "sim"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop_sim  # noqa: E402 — the shared workspace bootstrap
import dual_objective_battery as batt  # noqa: E402
import dual_objective_world as W  # noqa: E402
from rlvr.step_credit import CREDIT_BY_CLASS, CROSS_VALIDATED, UNVERIFIED  # noqa: E402
from settlement import per_dispatch  # noqa: E402

BASE, FLOOR, PRM, RACE, BOTH = (
    "1-baseline", "2-dense-floor", "3-direction-prm", "4-racing-elim",
    "5-prm-racing")


# ------------------------------------------- the reward faces (exact pins)

def test_reward_faces_price_through_the_real_tables():
    """The world's credit faces ARE the production faces: the #932
    measured base on a passing gate, the #884 conjunctive gate derived
    from step_credit's real classifier, and the #712 flat floor
    imported (never mirrored). A full 8-rung climb telescopes to EXACTLY
    PASS_CREDIT (the shaping pin)."""
    advance = {"arm": W.PRIMARY, "status": "VERIFIED",
               "verify_status": "passes", "delta_primary": W.RUNG_MASS,
               "delta_own": W.RUNG_MASS, "rung": 0,
               "cost": W.COST_TRUE, "gate_pass": W.gate_pass(
                   {"status": "VERIFIED", "verify_status": "passes"})}
    setback = dict(advance, status="REFUTED", verify_status="fails",
                   delta_primary=-W.RUNG_MASS, delta_own=-W.RUNG_MASS,
                   rung=1)
    leak = dict(advance, arm=W.LEAK, delta_primary=0.0,
                delta_own=W.LEAK_CLAIM_DELTA, cost=W.COST_LEAK)
    dead = dict(advance, arm=W.DEAD, status="INFERRED",
                verify_status="", delta_primary=0.0, delta_own=0.0,
                rung=None, cost=W.COST_DEAD)
    neutral = dict(advance, status=W.OPEN, verify_status="",
                   delta_primary=0.0, delta_own=0.0, rung=None)
    # LADDER_SPAN derives from step_credit's table (one authority)
    assert per_dispatch.LADDER_SPAN \
        == pytest.approx(CREDIT_BY_CLASS[CROSS_VALIDATED]
                         - CREDIT_BY_CLASS[UNVERIFIED])
    base = W.Mechanisms()
    # one rung banks 1/8th of PASS_CREDIT; a full climb telescopes exact
    assert W.step_credit_value(advance, base) \
        == pytest.approx(per_dispatch.PASS_CREDIT / W.LADDER_RUNGS)
    climb = sum(W.step_credit_value(advance, base)
                for _ in range(W.LADDER_RUNGS))
    assert climb == pytest.approx(per_dispatch.PASS_CREDIT)
    # setbacks and no-progress faces bank 0 (the measured no-progress
    # face — the conjunctive gate is untouched)
    assert W.step_credit_value(setback, base) == 0.0
    assert W.step_credit_value(neutral, base) == 0.0
    assert W.step_credit_value(dead, base) == 0.0
    # the readable grader: a complete per-step claim ladder prices FULL
    # credit every step, and never moves the primary ladder
    assert W.step_credit_value(leak, base) \
        == pytest.approx(per_dispatch.PASS_CREDIT)
    assert leak["delta_primary"] == 0.0
    # the flat floor pays the unverified anchor regardless of face
    floor = W.Mechanisms(dense_floor=True)
    for event in (advance, setback, leak, dead, neutral):
        assert W.step_credit_value(event, floor) \
            == CREDIT_BY_CLASS[UNVERIFIED] == W.FLAT_FLOOR
    # the PRM judge scales by primary advance: the leak arm's credit is
    # exactly zeroed; the true arm's advance keeps its measured price
    prm = W.Mechanisms(direction_prm=True)
    assert W.step_credit_value(leak, prm) == 0.0
    assert W.step_credit_value(dead, prm) == 0.0
    assert W.step_credit_value(advance, prm) \
        == pytest.approx(W.step_credit_value(advance, base))
    assert W.step_credit_value(setback, prm) == 0.0


def test_gate_pass_is_the_real_conjunctive_classifier():
    """The verdict gate is derived mechanically from
    rlvr.step_credit.classify_verification — refuted faces fail
    mechanical, only a green gate over terminal strength passes the
    scope layer."""
    assert W.gate_pass({"status": "VERIFIED", "verify_status": "passes"})
    assert not W.gate_pass({"status": "REFUTED",
                            "verify_status": "fails"})
    assert not W.gate_pass({"status": "OPEN", "verify_status": ""})
    assert not W.gate_pass({"status": "INFERRED", "verify_status": ""})


# ------------------------------------------------- the racing rule (exact)

def test_racing_collapse_rule_exact_bounds():
    """The abandon rule's arithmetic, pinned: an arm whose every step
    banked zero collapses after one stretch (Beta(1,7) lower bound
    0.125 - sqrt(7/576) < the threshold); an arm banking measured
    advance credit does not; select_direction's elimination set removes
    collapsed arms from the draw on every seeded draw."""
    dead_post = W.DirectionPosterior()
    for _ in range(W.STRETCH):
        dead_post.bank(W.DEAD, 0.0)
    alpha, beta = 1.0, 1.0 + W.STRETCH
    expected_lower = (alpha / (alpha + beta)
                      - (alpha * beta / ((alpha + beta) ** 2
                                         * (alpha + beta + 1.0))) ** 0.5)
    assert dead_post.lower_bound(W.DEAD) == pytest.approx(expected_lower)
    assert expected_lower < W.ABANDON_THRESHOLD
    assert dead_post.collapsed(W.DEAD)
    live_post = W.DirectionPosterior()
    for _ in range(W.STRETCH):
        live_post.bank(W.PRIMARY,
                       per_dispatch.PASS_CREDIT / W.LADDER_RUNGS)
    assert not live_post.collapsed(W.PRIMARY)
    # an eliminated arm never wins an eliminated-set draw
    for seed in range(40):
        arm, _draws = W.select_direction(
            dead_post, random.Random(f"elim/{seed}"),
            exclude=W.collapsed_arms(dead_post))
        assert arm != W.DEAD
    # with nothing collapsed the draw spans all arms
    seen = set()
    for seed in range(200):
        arm, _ = W.select_direction(W.DirectionPosterior(),
                                    random.Random(f"cold/{seed}"))
        seen.add(arm)
    assert seen == set(W.ARMS)          # every arm reachable cold


# --------------------------------------------------------- world mechanics

def test_world_determinism_same_seed_identical(tmp_path):
    """Fixed seeds end to end: two runs of the same seed produce
    IDENTICAL receipts (counter-clock ts included — no wall clock
    anywhere), and a moved seed moves the rollouts."""
    a = W.run_config(tmp_path / "a", name="det", mech=W.Mechanisms(),
                     rollouts=3, seed=7)
    b = W.run_config(tmp_path / "b", name="det", mech=W.Mechanisms(),
                     rollouts=3, seed=7)
    c = W.run_config(tmp_path / "c", name="det", mech=W.Mechanisms(),
                     rollouts=3, seed=8)
    assert a["receipts"] == b["receipts"]
    assert a["receipts"] != c["receipts"]


def test_forced_arms_reach_structural_outcomes(tmp_path):
    """Arm reachability, forced (the settle_one_dispatch precedent —
    the unit driver pins the environment's face): true-solve completes
    the primary objective; leak-proxy NEVER does and banks full credit
    every cheap step (the forged-economics shape); dead-plausible never
    completes and banks nothing."""
    forced = {}
    for arm in W.ARMS:
        # run one forced rollout directly on a bootstrapped workspace
        ws = tmp_path / arm / "forced-direct"
        ws.mkdir(parents=True)
        loop_sim._bootstrap(ws)
        ctx = {"posterior": W.DirectionPosterior(),
               "clock": W._Clock()}
        rec = W.run_rollout(ws, ctx, rid="ro-forced", seed="forced/1",
                            mech=W.Mechanisms(), force_arm=arm)
        ctx["posterior"].reconcile(ws)
        forced[arm] = rec
    win = forced[W.PRIMARY]
    assert win["terminal"] == "completed"
    assert win["primary_rungs"] == W.LADDER_RUNGS
    leak = forced[W.LEAK]
    assert leak["terminal"] == "budget_exhausted"
    assert leak["primary_rungs"] == 0
    assert leak["steps_by_arm"][W.LEAK] == W.HORIZON
    assert leak["credit_by_arm"][W.LEAK] \
        == pytest.approx(W.HORIZON * per_dispatch.PASS_CREDIT)
    assert leak["cost_total"] == pytest.approx(W.HORIZON * W.COST_LEAK)
    dead = forced[W.DEAD]
    assert dead["terminal"] == "budget_exhausted"
    assert dead["credit_total"] == 0.0
    for rec in forced.values():
        assert sum(rec["steps_by_arm"].values()) == rec["steps_total"]
        assert rec["steps_total"] <= W.HORIZON


def test_each_config_runs_and_reconciles_the_real_fold(tmp_path):
    """All five configs run end to end at smoke scale, every receipt
    carries the full shape, and the posterior cache never drifts from
    the REAL fold (reconcile is fail-loud inside run_config)."""
    for name, mech in batt.CONFIGS:
        out = W.run_config(tmp_path / "cfgs", name=name, mech=mech,
                           rollouts=2, seed=11)
        assert out["name"] == name
        assert len(out["receipts"]) == 2
        for rec in out["receipts"]:
            assert rec["terminal"] in ("completed", "budget_exhausted")
            assert {"rollout_id", "seed", "terminal", "steps_total",
                    "steps_by_arm", "credit_by_arm", "credit_total",
                    "cost_total", "primary_rungs", "premature_abandons",
                    "stretch_trace"} <= set(rec)


def test_posterior_drift_is_detected_fail_loud(tmp_path):
    """The cache is a cache, not an authority: a corrupted mass raises
    at the reconcile (the decisions must never ride a fiction), and the
    honest cache passes."""
    ws = tmp_path / "ws"
    ws.mkdir()
    loop_sim._bootstrap(ws)
    post = W.DirectionPosterior()
    ctx = {"posterior": post, "clock": W._Clock()}
    W.run_rollout(ws, ctx, rid="ro-drift", seed="drift/1",
                  mech=W.Mechanisms(), force_arm=W.LEAK)
    ctx["posterior"].reconcile(ws)          # honest cache passes
    ctx["posterior"].bank(W.LEAK, 0.5)      # a phantom row
    with pytest.raises(AssertionError):
        ctx["posterior"].reconcile(ws)


# ------------------------------------------------------------- the metrics

def _receipt(*, leak_steps: int, true_steps: int = 0,
             dead_steps: int = 0, terminal: str = "budget_exhausted",
             trace: list | None = None, abandons: list | None = None):
    total = leak_steps + true_steps + dead_steps
    return {"rollout_id": "r", "seed": "s", "terminal": terminal,
            "steps_total": total,
            "steps_by_arm": {W.LEAK: leak_steps, W.PRIMARY: true_steps,
                             W.DEAD: dead_steps},
            "credit_by_arm": {W.LEAK: 0.0, W.PRIMARY: 0.0, W.DEAD: 0.0},
            "credit_total": 0.0, "cost_total": 0.0,
            "primary_rungs": W.LADDER_RUNGS
            if terminal == "completed" else 0,
            "premature_abandons": abandons or [],
            "stretch_trace": trace or []}


def test_metrics_arithmetic_exact():
    """The metrics' arithmetic, exact on synthetic receipts: majority
    means STRICT majority, surrender keys on the direction of record
    dying (churn-that-returns is not surrender), completion counts
    terminals."""
    m = batt.config_metrics([
        _receipt(leak_steps=13, true_steps=11),
        _receipt(leak_steps=12, true_steps=12),   # exact tie: not majority
        _receipt(leak_steps=2, true_steps=22, terminal="completed"),
    ])
    assert m["n"] == 3
    assert m["leak_collapse"] == pytest.approx(1 / 3)
    assert m["completion"] == pytest.approx(1 / 3)
    assert m["premature_surrender"] == 0.0
    # surrender: a premature drop with no true-solve stretch after it
    surrendered = _receipt(
        leak_steps=18, true_steps=6,
        trace=[{"boundary": 0, "arm": W.PRIMARY},
               {"boundary": 1, "arm": W.LEAK},
               {"boundary": 2, "arm": W.LEAK}],
        abandons=[{"boundary": 1, "switched_to": W.LEAK}])
    assert batt.premature_surrender(surrendered)
    # churn: the drop at boundary 1 is followed by a true-solve stretch
    # at boundary 2 — exploration, not surrender
    churned = _receipt(
        leak_steps=6, true_steps=18,
        trace=[{"boundary": 0, "arm": W.PRIMARY},
               {"boundary": 1, "arm": W.LEAK},
               {"boundary": 2, "arm": W.PRIMARY},
               {"boundary": 3, "arm": W.PRIMARY}],
        abandons=[{"boundary": 1, "switched_to": W.LEAK}])
    assert not batt.premature_surrender(churned)
    # a second drop AFTER the last true-solve stretch surrenders
    late_surrender = _receipt(
        leak_steps=12, true_steps=12,
        trace=[{"boundary": 0, "arm": W.PRIMARY},
               {"boundary": 1, "arm": W.LEAK},
               {"boundary": 2, "arm": W.PRIMARY},
               {"boundary": 3, "arm": W.LEAK}],
        abandons=[{"boundary": 1, "switched_to": W.LEAK},
                  {"boundary": 3, "switched_to": W.LEAK}])
    assert batt.premature_surrender(late_surrender)
    # an abandoned-before-visit rollout never surrenders (nothing to
    # abandon: the arm never ran)
    never_true = _receipt(
        leak_steps=24,
        trace=[{"boundary": b, "arm": W.LEAK} for b in range(4)])
    assert not batt.premature_surrender(never_true)


def test_margin3_is_the_pooled_3sd_separation():
    """The significance margin is 3 sd of the two-rate difference."""
    assert batt._margin3(0.5, 0.5, 100, 100) \
        == pytest.approx(3.0 * (0.25 / 100 + 0.25 / 100) ** 0.5)
    assert batt._margin3(0.0, 0.0, 50, 50) == 0.0


# ----------------------------------------------- the five-config battery

def test_battery_verdicts_at_fixed_seeds(tmp_path):
    """THE CARD'S VERDICT SET, at fixed seeds (the battery's own
    conclusion format):

    - config 1 reproduces the P8 collapse (leak-collapse well above
      coin-flip; completion near-dead) — if this ever stops holding,
      the diagnosis is falsified and the test SHOULD fail.
    - config 2 (the 0.3 flat floor control) destroys the gradient:
      worse than baseline on surrender, completion below every
      mechanism.
    - configs 3 and 5 PASS both pre-registered criteria (leak-collapse
      significantly below baseline — it goes to ZERO — and premature
      surrender not raised; the combined config is strictly best on
      completion).
    - config 4 (racing alone) is NOT-for-production: its elimination
      can never unmask an arm whose unanchored signal is genuinely
      positive, so the leak-collapse criterion fails even though the
      surrender criterion passes (criterion 2, criterion 1 no).
    """
    out = batt.run_five_configs(tmp_path / "battery", batches=3,
                                rollouts=25, seed0=951)
    cfgs = out["configs"]
    conc = batt.conclusions(out)

    c1 = cfgs[BASE]["pooled"]
    assert conc["config1_collapse_reproduced"]["verdict"] is True
    assert c1["leak_collapse"] >= 0.4
    assert c1["completion"] <= 0.05

    c2 = cfgs[FLOOR]["pooled"]
    assert conc["config2_negative_control"][
        "verdict_worse_on_surrender"] is True
    assert conc["config2_negative_control"][
        "verdict_completion_below_every_mechanism"] is True

    for name in (PRM, BOTH):
        row = conc[name]
        assert row["verdict"] == batt.VERDICT_PASS, row
        assert row["criterion1_leak_drop_significant"] is True
        assert row["criterion2_surrender_not_raised"] is True
        assert cfgs[name]["pooled"]["leak_collapse"] == 0.0
    # the combined config is the strictly-best completion arm
    c5 = cfgs[BOTH]["pooled"]
    for name in (BASE, FLOOR, PRM, RACE):
        assert c5["completion"] > cfgs[name]["pooled"]["completion"]
    # racing alone: structurally zero surrender, dead leak-collapse drop
    c4 = conc[RACE]
    assert c4["verdict"] == batt.VERDICT_NOT_FOR_PRODUCTION
    assert c4["criterion1_leak_drop_significant"] is False
    assert c4["criterion2_surrender_not_raised"] is True
    assert cfgs[RACE]["pooled"]["premature_surrender"] == 0.0
    assert cfgs[RACE]["pooled"]["completion"] > c1["completion"]
    # the batch discipline: every PASSING mechanism's batch orderings
    # never invert against baseline on the collapse metric
    for name in (PRM, BOTH):
        assert batt._every_batch_lower(out, name, BASE, "leak_collapse")

    table = batt.render_table(out)
    for token in (BASE, FLOOR, PRM, RACE, BOTH,
                  batt.VERDICT_PASS, batt.VERDICT_NOT_FOR_PRODUCTION,
                  "collapse reproduced"):
        assert token in table
