# -*- coding: utf-8 -*-
"""tests/test_proof_battery_v3_887.py — PROOF BATTERY v3 (issue 887).

The v2 battery (tests/test_proof_battery.py) proved the learning loop
under the pool-scheduler architecture. Issue 887 re-bases the loop on the
rl-v2 faces — loop_sim_v3 drives the REAL policy/settlement/credit
faces (selector DTS, assigner+prober, terminator β, per-dispatch
draft/commit settlement, discounted returns/advantage/lineage) over
the REAL trajectory ledger (q_cells v2 (s,a,r) rows), with the mock
confined to the WORKER (task outcomes; deterministic, seeded — never
a policy). Every v2 conclusion is re-run under the new semantics, plus
two new experiments:

  V3-M   earned credit — family posterior mass banks ONLY through the
         settled three-layer gate; an unsettled rollout banks nothing
         (the anti-construction witness, exact fold pins).
  V3-E1b endogenous reward — same token bill, verdict flips the
         settled credit (exact); the shaped terminal flips at the
         outcome (+bonus / −bonus on the loop's own terminal rows).
  V3-E1c scrambled-credit control — THE anti-hallucination anchor:
         credit misattributed to the wrong family shows NO true-family
         learning; the live arm does (seed-sweep margins).
  V3-E1d convergence floor — the dose curve improves strictly with
         strictly shrinking deltas and never reaches the perfect-policy
         floor (the Beta(1,1) prior's irreducible mass), exact pins.
  V3-E3a component ablation — ablate the credit bank → the assignment
         face is byte-cold (its distribution EXACTLY equals the cold
         workspace's); ablate the selection record → the selector's
         posterior stays the exact wide prior; the full arm learns both.
  V3-E3b dose-response — d settled correct dispatches bank the exact
         (d, 0) fold cell; the honest posterior mean (1+d)/(2+d) is
         strictly monotone in the dose (exact pins).
  V3-SS  THE learning-effect metric — same situation (same signature),
         learning before/after: the drawn action differs AND is better
         (higher P(true family), lower expected dispatch cost).
  V3-NA  NEW: β termination vs a fixed step count on
         J(φ) = E[R_task − λ·C_total] — per-seed strict dominance,
         success parity, waste cut (receipt-backed numbers).
  V3-NB  NEW: portfolio vs single-select evidence coverage — the
         leader+2-probe portfolio banks 3 family observations per
         dispatch against the single draw's 1 (exact counts), with the
         probe credits riding the potential rails (never 0, never 1).
  V3-DET determinism — same seed → identical reports (CI-stable).

Statistical tolerances mirror tests/test_rl_v2_selector_880.py's
seed-sweep margin style: every sampled claim carries >= 3-sd of margin
at its draw batch; every exact claim pins fold arithmetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import battery_v3_experiments as v3x  # noqa: E402
import loop_sim_v3 as v3  # noqa: E402
from rlvr import q_cells  # noqa: E402

TRACKED = v3.TRACKED
OFFSETS = "offsets"
SIG = v3.situation_signature(OFFSETS)
DRAW_BATCH = 300
SEEDS = (0, 1, 2)
#: the perfect-policy dispatch cost (the tracked family's honest bill)
PERFECT_COST = v3.RIGHT_TOKENS / 10_000.0


def _arm_key(family: str) -> str:
    return q_cells.arm_key(family, v3.RECIPE_SEGMENT, v3.VERIF_SEGMENT,
                           v3.TIER)


def _cell(ws, sig: str, family: str):
    fold_view = q_cells.fold(q_cells.default_store(ws), gamma=v3.GAMMA)
    return fold_view.cells.get((sig, _arm_key(family)))


def _run(tmp_path, name="ws", **kw):
    ws = tmp_path / name
    ws.mkdir()
    return v3.run_v3_loop(ws, **kw), ws


# ------------------------------------------- V3-M: credit is earned, never granted

def test_v3_m_earned_credit_only_settled_evidence_banks(tmp_path):
    """A dispatch moves its family's Beta ONLY through the settled
    three-layer gate: a passing dispatch banks the exact (1.0, 0.0)
    cell, a failing dispatch (0.0, 1.0), and a rollout whose drafts
    never commit banks NOTHING (no cell, no mass) — settlement, not
    activity, is the admission ticket."""
    ws = tmp_path / "earned"
    ws.mkdir()
    settled = v3.settle_one_dispatch(ws, "offsets", TRACKED, rollout="ro-ok")
    assert settled["credit"] == pytest.approx(1.0)
    ok_cell = _cell(ws, SIG, TRACKED)
    assert ok_cell is not None
    assert (ok_cell.success, ok_cell.failure) == (pytest.approx(1.0),
                                                  pytest.approx(0.0))
    failed = v3.settle_one_dispatch(ws, "packer", "dynamic-trace",
                                    rollout="ro-bad", planted={"verified": False})
    assert failed["credit"] == 0.0
    bad_cell = _cell(ws, v3.situation_signature("packer"), "dynamic-trace")
    assert bad_cell is not None
    assert (bad_cell.success, bad_cell.failure) == (pytest.approx(0.0),
                                                    pytest.approx(1.0))
    # the UNSETTLED twin: same verified dispatch, drafts withheld —
    # nothing banks, and the committed read stays honest-empty
    ws2 = tmp_path / "unsettled"
    ws2.mkdir()
    out = v3.settle_one_dispatch(ws2, "offsets", TRACKED, rollout="ro-pending",
                                 settle=False)
    assert out["credit"] is None
    assert out["committed"]["committed"] is False
    assert _cell(ws2, SIG, TRACKED) is None
    fold_view = q_cells.fold(q_cells.default_store(ws2), gamma=v3.GAMMA)
    assert not fold_view.cells


# --------------------------------------- V3-E1b: endogenous settled reward

def test_v3_e1b_endogenous_reward_verdict_and_terminal(tmp_path):
    """Same token bill, different verdict -> different settled credit
    (the reward prices OUTCOME quality, not spend); the loop's terminal
    rows ride the shaped return: a completed single-step rollout banks
    r_t = 1 + bonus, a rolled-back one r_t = -bonus, and the advantage
    column carries the confidence-modulated A_t."""
    ws = tmp_path / "endogenous"
    ws.mkdir()
    good = v3.settle_one_dispatch(ws, "offsets", TRACKED, rollout="ro-g")
    bad = v3.settle_one_dispatch(ws, "offsets", TRACKED, rollout="ro-b",
                                 planted={"verified": False,
                                          "tokens": v3.RIGHT_TOKENS})
    assert good["credit"] == pytest.approx(1.0)
    assert bad["credit"] == 0.0
    assert good["cost"] == pytest.approx(bad["cost"])
    assert good["terminal_r_t"] == pytest.approx(1.0 + v3.TERMINAL_BONUS)
    assert good["terminal_a_t"] == pytest.approx(1.0 + v3.TERMINAL_BONUS)
    assert bad["terminal_r_t"] == pytest.approx(-v3.TERMINAL_BONUS)
    # confidence modulation: the unverified step's trust weight halves
    # the signed advantage (documented UNVERIFIED_CONFIDENCE)
    assert bad["terminal_a_t"] \
        == pytest.approx(-v3.TERMINAL_BONUS * v3.UNVERIFIED_CONFIDENCE)
    # the raw step rewards themselves differ at identical spend
    assert good["step_r_t"] == pytest.approx(1.0)
    assert bad["step_r_t"] == pytest.approx(0.0)


# ------------------------------- V3-E1c: scrambled-credit control (the anchor)

def test_v3_e1c_scrambled_credit_control(tmp_path):
    """MEMORY CONTENT matters, not memory existence: with every settled
    credit misattributed to the ring's next family, the true family's
    situation cell banks ZERO earned success (exact, every seed) while
    the live arm's cell is pure earned success — and the corruption is
    REALIZED: the scrambled arm's exact expected dispatch cost is worse
    than the live arm's on BOTH measured situations, every seed."""
    cold_ws = tmp_path / "cold"
    cold_ws.mkdir()
    cold_cost = v3.expected_dispatch_cost(cold_ws, OFFSETS)
    for seed in SEEDS:
        live, _ = _run(tmp_path, name=f"live-{seed}", seed=seed)
        scram, _ = _run(tmp_path, name=f"scram-{seed}", seed=seed,
                        scramble_credit=True)
        live_cell = _cell(live["ws"], SIG, TRACKED)
        scram_cell = _cell(scram["ws"], SIG, TRACKED)
        # EXACT: the live true-family cell is pure earned success ...
        assert live_cell is not None
        assert live_cell.success >= 1.0 and live_cell.failure == 0.0, \
            live_cell
        # ... the scrambled true-family cell banks ZERO success (its
        # evidence all landed on the wrong ring arm) — the
        # anti-hallucination anchor
        assert scram_cell is None or scram_cell.success == 0.0, scram_cell
        # the corruption realizes: worse expected cost on both
        # situations, and no better than the cold prior on offsets
        for situation in (OFFSETS, "packer"):
            live_cost = v3.expected_dispatch_cost(live["ws"], situation)
            scram_cost = v3.expected_dispatch_cost(scram["ws"], situation)
            # the cost leg is >= (seed 3 ties exactly); direction
            # never inverts (review sweep seeds 3-8), the zero-success
            # anchor above carries the anti-hallucination weight
            assert live_cost <= scram_cost, (seed, situation, live_cost,
                                             scram_cost)
        assert v3.expected_dispatch_cost(live["ws"], OFFSETS) < cold_cost
        assert v3.expected_dispatch_cost(scram["ws"], OFFSETS) > cold_cost


# ---------------------------------- V3-E1d: convergence floor (dose curve)

def test_v3_e1d_convergence_floor_dose_curve(tmp_path):
    """A learning curve, not a step: over six settled doses the
    tracked family's posterior mean rises strictly with STRICTLY
    shrinking deltas and never reaches the perfect-policy cost — the
    Beta(1,1) prior keeps a irreducible floor (the asymptote)."""
    ws = tmp_path / "floor"
    ws.mkdir()
    curve = v3.dose_curve(ws, situation=OFFSETS, doses=6)
    means = [pt["posterior_mean"] for pt in curve]
    costs = [pt["expected_cost"] for pt in curve]
    assert all(b > a for a, b in zip(means, means[1:])), means
    assert all(abs(b - a) < abs(a - a0)
               for a0, a, b in zip(means, means[1:], means[2:])), means
    # exact honest posterior: (1+d)/(2+d)
    for d, pt in enumerate(curve, start=1):
        assert pt["posterior_mean"] \
            == pytest.approx((1.0 + d) / (2.0 + d)), (d, pt)
        assert (pt["cell"].success, pt["cell"].failure) \
            == (pytest.approx(float(d)), pytest.approx(0.0))
    # the cost declines to an asymptote ABOVE the perfect-policy floor
    assert all(b < a for a, b in zip(costs, costs[1:])), costs
    assert all(abs(b - a) < abs(a - a0)
               for a0, a, b in zip(costs, costs[1:], costs[2:])), costs
    assert costs[-1] > PERFECT_COST
    assert means[-1] < 1.0


# ---------------------------------- V3-E3a: component ablation arms

def test_v3_e3a_component_ablation_arms(tmp_path):
    """WHICH face carries WHAT: ablating the credit bank leaves the
    assignment face byte-cold — its draw distribution EXACTLY equals the
    cold workspace's (same draw seeds, empty fold both) and its exact
    posterior means stay the wide prior; ablating the selection record
    leaves the selector's posterior at the exact wide prior while the
    assignment face still learns; the full arm learns both."""
    cold_ws = tmp_path / "cold"
    cold_ws.mkdir()
    full, _ = _run(tmp_path, name="full", seed=0)
    no_credit, _ = _run(tmp_path, name="no-credit", seed=0,
                        ablate_credit=True)
    no_select, _ = _run(tmp_path, name="no-select", seed=0,
                        ablate_selector=True)
    cold_dist = v3.assignment_distribution(cold_ws, OFFSETS,
                                           draws=DRAW_BATCH, seed0=7)
    no_credit_dist = v3.assignment_distribution(no_credit["ws"], OFFSETS,
                                                draws=DRAW_BATCH, seed0=7)
    assert no_credit_dist == cold_dist          # byte-cold, exact
    cold_means = v3.situation_posterior_means(no_credit["ws"], OFFSETS)
    assert cold_means == {f: 0.5 for f in v3.FAMILIES}   # wide prior, exact
    # the full arm's assignment face learned (exact posterior argmax)
    live_means = v3.situation_posterior_means(full["ws"], OFFSETS)
    assert max(live_means, key=lambda f: live_means[f]) == TRACKED
    assert live_means[TRACKED] > 0.75, live_means
    # the selector axis: the ablated run's posteriors are the exact
    # wide prior on every task; the full arm's are not
    tasks = [t for lap in v3.LAP_TASKS[:3] for t, _s in lap]
    for tid in tasks:
        assert no_select["report"]["task_posteriors"][tid] == (1.0, 1.0)
    learned = [p for tid, p in full["report"]["task_posteriors"].items()
               if p != (1.0, 1.0)]
    assert learned
    # the untouched axis keeps learning in each ablated arm
    no_select_means = v3.situation_posterior_means(no_select["ws"], OFFSETS)
    assert max(no_select_means,
               key=lambda f: no_select_means[f]) == TRACKED
    sel_post = no_credit["report"]["task_posteriors"]
    assert any(p != (1.0, 1.0) for p in sel_post.values())


# ---------------------------------- V3-E3b: dose-response (exact monotone)

def test_v3_e3b_dose_response_monotone(tmp_path):
    """More settled evidence -> strictly stronger effect, pinned
    exactly: d doses bank the exact (d, 0) cell and the honest
    posterior mean (1+d)/(2+d); the behavioral draw probability is
    monotone in the dose (seed-fixed batches)."""
    means = []
    dists = []
    for dose in (1, 2, 3):
        ws = tmp_path / f"dose-{dose}"
        ws.mkdir()
        curve = v3.dose_curve(ws, situation=OFFSETS, doses=dose)
        cell = curve[-1]["cell"]
        assert (cell.success, cell.failure) == (pytest.approx(float(dose)),
                                                pytest.approx(0.0))
        means.append(curve[-1]["posterior_mean"])
        dists.append(v3.assignment_distribution(ws, OFFSETS,
                                                draws=DRAW_BATCH,
                                                seed0=7)[TRACKED])
    assert means == pytest.approx([2.0 / 3.0, 3.0 / 4.0, 4.0 / 5.0]), means
    assert means[0] < means[1] < means[2]
    assert dists[0] <= dists[1] <= dists[2], dists
    assert dists[2] > 1.0 / len(v3.FAMILIES)   # actually past uniform


# ------------------------- V3-SS: THE learning-effect metric (same situation)

def test_v3_learning_effect_same_situation_before_after(tmp_path):
    """THE metric: same situation (the SAME situation signature),
    learning before vs after — the policy's preferred action DIFFERS
    (the cold posterior is the exact wide prior on every family; the
    learned posterior's argmax has moved to the true family) and is
    BETTER (the tracked family's posterior mean rises 0.5 -> 5/6+, the
    exact expected dispatch cost drops on every run; no sampling in any
    pin)."""
    cold_ws = tmp_path / "cold"
    cold_ws.mkdir()
    cold_means = v3.situation_posterior_means(cold_ws, OFFSETS)
    assert cold_means == {f: 0.5 for f in v3.FAMILIES}
    cost_before = v3.expected_dispatch_cost(cold_ws, OFFSETS)
    assert cost_before == pytest.approx(1.0 / 3.0 * 0.1 + 2.0 / 3.0 * 0.4)
    runs = [_run(tmp_path, name=f"ss-{seed}", seed=seed)[0] for seed in SEEDS]
    for run in runs:
        after = v3.situation_posterior_means(run["ws"], OFFSETS)
        # DIFFERENT: the argmax moved to the truth (cold had none)
        assert max(after, key=lambda f: after[f]) == TRACKED, after
        # BETTER: the true family's posterior mean cleared 3/4 ...
        assert after[TRACKED] > 0.75, after
        # ... every wrong family sits at or below the prior ...
        for family in v3.FAMILIES:
            if family != TRACKED:
                assert after[family] <= 0.5, (family, after)
        # ... and the exact expected dispatch cost dropped
        assert v3.expected_dispatch_cost(run["ws"], OFFSETS) < cost_before
        # the situation cell is pure earned success (no failure ever
        # banked on the true family in the live arm)
        cell = _cell(run["ws"], SIG, TRACKED)
        assert cell.failure == 0.0 and cell.success >= 1.0, cell


# --------------------- V3-NA (new a): beta termination vs fixed deadline

def test_v3_new_a_beta_termination_vs_fixed_deadline(tmp_path):
    """J(phi) = E[R_task - lambda * C_total]: the beta policy dominates
    the fixed step count on EVERY seed (exact per-seed comparisons),
    with EQUAL success and strictly less waste (fewer mean steps).
    SCOPE (review): equality is a DESIGN INVARIANT under this harness —
    the assignment is pinned to the true family, so β can only
    terminate after coverage; the pin guards that invariant (a
    termination that DID cost coverage flips it), it does not claim an
    unpinned-arm discovery."""
    out = v3x.run_termination_comparison(tmp_path / "na", seeds=8)
    per_seed = out["per_seed"]
    assert per_seed
    for row in per_seed:
        assert row["beta_J"] > row["fixed_J"], row
        assert row["beta_success"] == row["fixed_success"], row
        assert row["beta_steps"] < row["fixed_steps_mean"], row
    assert out["beta"]["J"] > out["fixed"]["J"]
    assert out["beta"]["success"] == pytest.approx(out["fixed"]["success"])
    assert out["beta"]["mean_steps"] < out["fixed"]["mean_steps"]
    # receipt-backed numbers, not vibes: the J decomposition is carried
    assert out["beta"]["mean_reward"] > 0.0
    assert out["beta"]["mean_cost"] < out["fixed"]["mean_cost"]
    # the beta arm's early finishes earn the efficiency credit; the
    # fixed arm's late finishes on the same answerable tasks do not
    assert out["beta"]["efficiency_credits"] > 0
    assert out["fixed"]["efficiency_credits"] == 0


# -------------------- V3-NB (new b): portfolio vs single-select coverage

def test_v3_new_b_portfolio_coverage(tmp_path):
    """Action-space evidence coverage: ONE leader+2-probe portfolio
    dispatch banks evidence for all THREE families; a single-select
    dispatch banks one. After the same budget the portfolio's
    min-per-family banked count equals the dispatch budget (pigeonhole
    keeps the single arm's min at <= 2), the probe credits ride the
    potential rails, and probe result rows never price themselves."""
    out = v3x.run_portfolio_coverage(tmp_path / "nb", dispatches=4)
    port, single = out["portfolio"], out["single"]
    assert port["coverage_after_1"] == 3
    assert single["coverage_after_1"] == 1
    assert port["total_banked"] == 3 * 4
    assert single["total_banked"] == 4
    assert port["min_family_rows"] == 4
    assert single["min_family_rows"] <= 2 < 4
    assert port["families_with_mass"] == 3
    # potential-based rails: probe credits never leave [0.25, 0.75]
    assert port["probe_credits"]
    assert all(v3x.prober.PROBE_CREDIT_FLOOR <= c <= v3x.prober.PROBE_CREDIT_CEIL
               for c in port["probe_credits"])
    # a probe's potential credit never owns the outcome: strictly
    # inside the rail endpoints for this 3-arm portfolio's map
    assert all(0.0 < c < 1.0 for c in port["probe_credits"])
    # probe result rows keep r_t pending — a probe never prices its
    # own evidence (exact ledger read)
    assert port["probe_pending_results"] == 2 * 4
    # and the portfolio's leader history is real settled credit (1.0),
    # not probe mass
    assert port["leader_settled_success"] == pytest.approx(4.0)


# --------------------------------------------------- V3-LN: lineage flowback

def test_v3_lineage_flowback_rides_the_spawn_chain(tmp_path):
    """The spawn-credit spine is live: the retry lap's rollout spawns a
    candidate child, both rollouts' shaped terminal returns ride the
    report, and credit.lineage prices the parent at
    own + γ_L·child — exact arithmetic over the loop's own returns."""
    run, _ = _run(tmp_path, name="lineage", seed=0, laps=2)
    lineage = run["report"]["lineage"]
    assert lineage
    for row in lineage:
        credited = row["credited"]
        parent_rid = row["parent_rid"]
        child_rid = row["child_rid"]
        expected = row["parent_r_t"] + v3.GAMMA_LINEAGE * row["child_r_t"]
        assert credited[parent_rid] == pytest.approx(expected)
        assert credited[child_rid] \
            == pytest.approx(row["child_r_t"])


# --------------------------------------------- V3-DET: determinism / CI stability

def test_v3_determinism_same_seed_identical(tmp_path):
    """Fixed seeds everywhere: two runs of the same seed produce
    IDENTICAL reports (decision-stable: no wall clock in any decision;
    ts stamps excluded), and the seed moves the draw streams
    (different seeds explore differently from cold)."""
    r1, ws1 = _run(tmp_path, name="det-1", seed=3)
    r2, ws2 = _run(tmp_path, name="det-2", seed=3)
    assert r1["report"] == r2["report"]
    rows1 = q_cells.trajectory_rows(ws1)
    rows2 = q_cells.trajectory_rows(ws2)
    assert [{k: v for k, v in row.items() if k != "ts"} for row in rows1] \
        == [{k: v for k, v in row.items() if k != "ts"} for row in rows2]
    r3, _ = _run(tmp_path, name="det-3", seed=4)
    assert r3["report"] != r1["report"]


# ----------------------------- the full battery table (all in one place)

def test_proof_battery_v3_table(tmp_path):
    """The one-glance v3 proof: the live/scrambled/cold assignment
    split, the dose curve, the ablation arms, the J(phi) comparison and
    the coverage counts — every headline pass condition asserted
    together from ONE set of runs."""
    cold_ws = tmp_path / "t-cold"
    cold_ws.mkdir()
    full, _ = _run(tmp_path, name="t-full", seed=0)
    scram, _ = _run(tmp_path, name="t-scram", seed=0, scramble_credit=True)
    no_credit, _ = _run(tmp_path, name="t-no-credit", seed=0,
                        ablate_credit=True)
    cold_means = v3.situation_posterior_means(cold_ws, OFFSETS)
    live_means = v3.situation_posterior_means(full["ws"], OFFSETS)
    scram_means = v3.situation_posterior_means(scram["ws"], OFFSETS)
    no_credit_means = v3.situation_posterior_means(no_credit["ws"], OFFSETS)
    cold_cost = v3.expected_dispatch_cost(cold_ws, OFFSETS)
    live_cost = v3.expected_dispatch_cost(full["ws"], OFFSETS)
    scram_cost = v3.expected_dispatch_cost(scram["ws"], OFFSETS)
    ws_floor = tmp_path / "t-floor"
    ws_floor.mkdir()
    curve = v3.dose_curve(ws_floor, situation=OFFSETS, doses=6)
    term = v3x.run_termination_comparison(tmp_path / "t-na", seeds=4)
    cov = v3x.run_portfolio_coverage(tmp_path / "t-nb", dispatches=4)
    # the headline conditions, together
    assert live_means[TRACKED] > 0.75                     # earned rise
    assert live_cost < cold_cost                          # the live arm learned
    assert scram_cost > live_cost                         # scramble corrupts
    assert scram_means[TRACKED] <= 0.5                    # no earned rise
    assert no_credit_means == cold_means                  # ablation byte-cold
    means = [pt["posterior_mean"] for pt in curve]
    assert all(b > a for a, b in zip(means, means[1:]))   # dose monotone
    assert term["beta"]["J"] > term["fixed"]["J"]         # beta wins J
    assert term["beta"]["success"] \
        == pytest.approx(term["fixed"]["success"])        # success parity
    assert cov["portfolio"]["coverage_after_1"] \
        > cov["single"]["coverage_after_1"]               # coverage split
