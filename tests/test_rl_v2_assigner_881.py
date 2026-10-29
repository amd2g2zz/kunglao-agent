# -*- coding: utf-8 -*-
"""tests/test_rl_v2_assigner_881.py — the method assigner (issue 881).

Pins-first tests for the two-stage method selection faces:

  1. assigner.assign_method — the LLM Planner ranking arrives as DATA
     (a caller-supplied {family: rank} mapping, never an authority);
     the sampling face is state-driven: per-candidate shrunk Beta
     posterior (q_cells.cell_posterior over the gamma-discounted fold)
     sampled Thompson-style, weight = P_planner x theta, one
     proportional draw. Receipt stamp "method-assign/1" carries the
     per-candidate {rank, p_llm, alpha, beta, theta, weight}, the
     chosen family and the implied assign_step action (core action/1).
  2. cold start explores: an empty ledger leaves the wide Beta(1,1)
     posterior, so the empirical distribution is ranking-dominated but
     non-degenerate (chi-square tolerance, mirroring the q-cells
     sampling-distribution test).
  3. sharpened posterior exploits: banked successes are sampled more;
     banked failures demote a family from most-chosen to least-chosen
     (the same-situation measurability acceptance pin).
  4. fail-closed boundary: closed candidate vocabulary (the registry
     set), garbage ranking values rejected, empty candidates rejected.
  5. prober.plan_portfolio — the receipt stamp "portfolio-plan/1"
     carries one leader (full Budget) plus exactly two probe arms at
     the documented budget fraction (a policy constant, not fitted).
  6. prober.record_probe — probe evidence lands IN the ledger (probe
     action row + result row + the credit observation the fold banks;
     potential-based comparison, never a fabricated absolute score)
     and the next assignment's posterior and distribution MOVE.
  7. determinism: same seed, same receipt; the Random(0)
     anchor-deterministic default; the seed state is ledger-content
     derived, never wall clock.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core import Budget, ActionKind, parse_action  # noqa: E402
from policy import assigner, prober  # noqa: E402
from rlvr import q_cells  # noqa: E402

# chi-square critical value, df=2, p=0.01 (mirrors the kernel test)
CHI2_DF2_P01 = 9.21
N_DRAWS = 9000

SIG = "a1b2c3d4e5f6"
FAM_A = "static-decompile"
FAM_B = "dynamic-trace"
FAM_C = "obfuscation-peeling"
CANDIDATES = [FAM_A, FAM_B, FAM_C]
RANKS = {FAM_A: 1.0, FAM_B: 2.0, FAM_C: 3.0}
EQUAL_RANKS = {FAM_A: 1.0, FAM_B: 1.0, FAM_C: 1.0}


def _ak(fam: str) -> str:
    """The fixture rows' deterministic 4-dim arm key."""
    return f"{fam}|facts_snapshot|none|0"


def _bank(ws, fam: str, credit: float, n: int = 12) -> None:
    """Bank n settled credit observations for one (signature, family)."""
    for _ in range(n):
        q_cells.append_observation(ws, SIG, fam, credit,
                                   source="settlement",
                                   arm_key_col=_ak(fam))


def _assign(ws, ranks, **over):
    return assigner.assign_method(
        ws, list(ranks), dict(ranks), signature_hash=SIG, tier=2, **over)


def _distribution(ws, ranks, n=N_DRAWS, seed=20260929):
    rng = random.Random(seed)
    counts = {f: 0 for f in ranks}
    for _ in range(n):
        counts[_assign(ws, ranks, rng=rng)["family"]] += 1
    return counts


def _mc_targets(ws, ranks, n=200_000, seed=424242):
    """The draw's TRUE law, Monte-Carlo integrated: per draw, sample
    every arm's theta from its folded posterior and select
    proportionally over p_planner x theta — the same P x Q selection
    the sampler runs, integrated over the posterior instead of
    linearized. 200k reference draws keep the target's own noise
    (~0.001) far under the sampler's."""
    fold_view = q_cells.fold(q_cells.default_store(ws))
    posts = {}
    for fam, rank in ranks.items():
        a, b = q_cells.cell_posterior(fold_view, SIG, fam)
        posts[fam] = (1.0 / rank, a, b)
    families = sorted(posts)
    rng = random.Random(seed)
    counts = {f: 0 for f in families}
    for _ in range(n):
        weights = {f: p * rng.betavariate(a, b)
                   for f, (p, a, b) in posts.items()}
        total = sum(weights[f] for f in families)
        u = rng.random() * total
        cum = 0.0
        chosen = families[-1]
        for f in families:
            cum += weights[f]
            if u <= cum:
                chosen = f
                break
        counts[chosen] += 1
    return {f: c / n for f, c in counts.items()}


# ------------------------------------------------------- 1. receipt shape

def test_assign_receipt_shape_and_implied_action(tmp_path):
    ws = tmp_path / "ws"
    receipt = _assign(ws, RANKS)
    assert receipt["schema"] == "method-assign/1"
    assert receipt["signature_hash"] == SIG
    assert receipt["family"] in CANDIDATES
    assert 0.0 < receipt["gamma"] <= 1.0
    assert set(receipt["candidates"]) == set(CANDIDATES)
    for fam, cand in receipt["candidates"].items():
        assert cand["rank"] == RANKS[fam]
        assert cand["p_llm"] == pytest.approx(1.0 / RANKS[fam])
        assert (cand["alpha"], cand["beta"]) == (1.0, 1.0)   # cold start
        assert 0.0 < cand["theta"] < 1.0
        assert cand["weight"] == pytest.approx(
            cand["p_llm"] * cand["theta"], abs=1e-6)
    action = receipt["action"]
    assert action["kind"] == ActionKind.ASSIGN_STEP.value
    assert action["target"] == receipt["family"]
    assert action["params"]["method_family"] == receipt["family"]
    assert action["params"]["tier"] == 2
    parsed = parse_action(action)          # the action/1 boundary holds
    assert parsed.kind is ActionKind.ASSIGN_STEP


def test_assign_gamma_passes_through(tmp_path):
    ws = tmp_path / "ws"
    assert _assign(ws, RANKS, gamma=1.0)["gamma"] == 1.0
    assert _assign(ws, RANKS, gamma=0.5)["gamma"] == 0.5


# ------------------------------------------------- 2. cold start explores

def test_cold_start_distribution_is_ranking_dominated_non_degenerate(
        tmp_path):
    """Cold start explores: the wide Beta(1,1) leaves a distribution
    the ranking dominates but no arm dies in. Chi-square runs against
    the Monte-Carlo law reference (the mean-ratio face linearizes a
    ratio of random variables and would mis-target wide thetas)."""
    ws = tmp_path / "ws"
    counts = _distribution(ws, RANKS, n=2000)
    targets = _mc_targets(ws, RANKS)
    freq = {f: c / 2000 for f, c in counts.items()}
    for fam, target in targets.items():
        assert abs(freq[fam] - target) <= 0.025, (fam, freq[fam], target)
        assert freq[fam] > 0.05          # non-degenerate: every arm lives
    assert freq[FAM_A] > freq[FAM_B] > freq[FAM_C]   # ranking-dominated
    assert freq[FAM_A] < 0.70            # explores: the lead is soft
    chi2 = sum((counts[f] - 2000 * t) ** 2 / (2000 * t)
               for f, t in targets.items())
    assert chi2 < CHI2_DF2_P01, (chi2, freq, targets)


# ------------------------------------------------ 3. sharpened exploits

def test_sharpened_posterior_exploits_banked_successes(tmp_path):
    ws = tmp_path / "ws"
    _bank(ws, FAM_A, 1.0)
    _bank(ws, FAM_B, 0.0)
    # exact-mass face: the constant gamma = 1 calibration fold (the
    # shipped default is the adaptive schedule — decayed masses would
    # not match the closed-form shrinkage arithmetic)
    receipt = _assign(ws, EQUAL_RANKS, gamma=1.0)
    # exact shrunk posteriors (leave-one-out anchor, SHRINK_CAP 8;
    # anchor mean m = (1+12)/(2+12) = 13/14):
    a, b = receipt["candidates"][FAM_A], receipt["candidates"][FAM_B]
    assert a["alpha"] == pytest.approx(1.0 + 8 * 13 / 14, abs=1e-9)
    assert a["beta"] == pytest.approx(1.0 + 8 * 1 / 14, abs=1e-9)
    assert b["alpha"] == pytest.approx(1.0 + 8 * 1 / 14, abs=1e-9)
    assert b["beta"] == pytest.approx(1.0 + 8 * 13 / 14, abs=1e-9)
    targets = _mc_targets(ws, EQUAL_RANKS)
    counts = _distribution(ws, EQUAL_RANKS, n=2000)
    freq = {f: c / 2000 for f, c in counts.items()}
    for fam, target in targets.items():
        assert abs(freq[fam] - target) <= 0.025, (fam, freq[fam], target)
    assert freq[FAM_A] > freq[FAM_C] > freq[FAM_B]
    chi2 = sum((counts[f] - 2000 * t) ** 2 / (2000 * t)
               for f, t in targets.items())
    assert chi2 < CHI2_DF2_P01, (chi2, freq, targets)


def test_same_situation_banked_failures_move_the_sampled_method(tmp_path):
    """The measurability acceptance pin: the SAME situation (same
    ranking data) sampled over an empty ledger vs a ledger where one
    family has banked failures — the sampled method CHANGES,
    statistically, under the ledger-content-derived seed. The top-ranked
    family is dethroned: banked failures cost it the lead."""
    empty = tmp_path / "ws-empty"
    banked = tmp_path / "ws-banked"
    _bank(banked, FAM_A, 0.0)
    before = _distribution(empty, RANKS)
    after = _distribution(banked, RANKS)
    assert max(before, key=before.get) == FAM_A
    assert max(after, key=after.get) == FAM_B      # rank 2 takes the lead
    drop = before[FAM_A] / N_DRAWS - after[FAM_A] / N_DRAWS
    assert drop > 0.15, (before, after)


# ------------------------------------------------- 4. fail-closed boundary

@pytest.mark.parametrize("candidates", [
    [],                                     # empty: nothing to assign
    "static-decompile",                     # not a sequence of tokens
    [FAM_A, FAM_A, FAM_B],                  # duplicate candidate
    ["static-decompile "],                  # whitespace is not a token
    ["Not-A-Registered-Family"],            # outside the closed grammar
])
def test_assign_rejects_bad_candidate_sets(tmp_path, candidates):
    with pytest.raises(ValueError):
        assigner.assign_method(tmp_path / "ws", candidates, RANKS,
                               signature_hash=SIG, tier=2)


def test_assign_rejects_garbage_ranking_values(tmp_path):
    ws = tmp_path / "ws"
    bad_values = ["1", True, None, float("nan"), float("inf"),
                  float("-inf"), 0.0, -1.0, 0.5]
    for bad in bad_values:
        ranks = {FAM_A: 1.0, FAM_B: 2.0, FAM_C: bad}
        with pytest.raises(ValueError):
            _assign(ws, ranks)
    with pytest.raises(ValueError):        # a candidate went unranked
        assigner.assign_method(ws, CANDIDATES, {FAM_A: 1.0, FAM_B: 2.0},
                               signature_hash=SIG, tier=2)
    with pytest.raises(ValueError):        # a rank outside the candidates
        _assign(ws, {FAM_A: 1.0, FAM_B: 2.0, FAM_C: 3.0,
                     "not-a-candidate": 1.0})
    with pytest.raises(ValueError):        # the ranking is not a mapping
        assigner.assign_method(ws, CANDIDATES, [1.0, 2.0, 3.0],
                               signature_hash=SIG, tier=2)


def test_assign_rejects_bad_signature_or_tier(tmp_path):
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        assigner.assign_method(ws, CANDIDATES, RANKS,
                               signature_hash="nothex", tier=2)
    with pytest.raises(ValueError):
        assigner.assign_method(ws, CANDIDATES, RANKS,
                               signature_hash=SIG, tier="high")


# -------------------------------------------------------- 5. the portfolio

def test_plan_portfolio_is_leader_plus_exactly_two_probes(tmp_path):
    ws = tmp_path / "ws"
    budget = Budget(wall_s=600.0, max_calls=8)
    plan = prober.plan_portfolio(ws, FAM_A, [FAM_B, FAM_C],
                                 signature_hash=SIG, budget=budget)
    assert plan["schema"] == "portfolio-plan/1"
    assert plan["signature_hash"] == SIG
    assert plan["leader"]["family"] == FAM_A
    assert plan["leader"]["budget"] == {"wall_s": 600.0, "max_calls": 8}
    assert [p["family"] for p in plan["probes"]] == [FAM_B, FAM_C]
    for probe in plan["probes"]:
        assert probe["budget"]["wall_s"] == pytest.approx(
            600.0 * prober.PROBE_WALL_FRACTION)
        assert probe["budget"]["max_calls"] == max(
            1, int(8 * prober.PROBE_WALL_FRACTION))
    assert plan["probe_wall_fraction"] == prober.PROBE_WALL_FRACTION
    # a documented policy constant, not a fitted one
    assert 0.0 < prober.PROBE_WALL_FRACTION < 1.0
    assert prober.PROBE_ARMS == 2


def test_plan_portfolio_reject_pins(tmp_path):
    ws = tmp_path / "ws"
    budget = Budget(wall_s=600.0, max_calls=8)
    with pytest.raises(ValueError):        # one probe is not a portfolio
        prober.plan_portfolio(ws, FAM_A, [FAM_B], signature_hash=SIG,
                              budget=budget)
    with pytest.raises(ValueError):        # three probes is not either
        prober.plan_portfolio(ws, FAM_A, [FAM_B, FAM_C,
                                          "crypto-core-identification"],
                              signature_hash=SIG, budget=budget)
    with pytest.raises(ValueError):        # a probe of the leader's arm
        prober.plan_portfolio(ws, FAM_A, [FAM_A, FAM_B],
                              signature_hash=SIG, budget=budget)
    with pytest.raises(ValueError):        # duplicate probe arms
        prober.plan_portfolio(ws, FAM_A, [FAM_B, FAM_B],
                              signature_hash=SIG, budget=budget)
    with pytest.raises(ValueError):        # unregistered token
        prober.plan_portfolio(ws, FAM_A, [FAM_B, "not-in-the-registry"],
                              signature_hash=SIG, budget=budget)
    with pytest.raises(ValueError):        # budget is not a Budget
        prober.plan_portfolio(ws, FAM_A, [FAM_B, FAM_C],
                              signature_hash=SIG, budget={"wall_s": 600.0})
    with pytest.raises(ValueError):        # negative budget
        prober.plan_portfolio(ws, FAM_A, [FAM_B, FAM_C],
                              signature_hash=SIG,
                              budget=Budget(wall_s=-1.0))
    with pytest.raises(ValueError):        # bad signature hash
        prober.plan_portfolio(ws, FAM_A, [FAM_B, FAM_C],
                              signature_hash="nothex", budget=budget)


# --------------------------------------------- 6. probe evidence -> ledger

def _record(plan_ws, plan, n=12):
    for i in range(n):          # n DISTINCT probe runs (unique ids)
        prober.record_probe(plan_ws, plan, FAM_B,
                            rollout_id=f"ro-probe-{i:02d}",
                            step_id=f"probe-b-{i:02d}", rank=1,
                            verified=True, verdict="probe-win")


def test_probe_evidence_lands_in_the_ledger(tmp_path):
    ws = tmp_path / "ws"
    plan = prober.plan_portfolio(ws, FAM_A, [FAM_B, FAM_C],
                                 signature_hash=SIG,
                                 budget=Budget(wall_s=600.0, max_calls=8))
    _record(ws, plan)
    rows = q_cells.trajectory_rows(ws)
    actions = [r for r in rows if r["schema"] == "q-cell-action/1"]
    results = [r for r in rows if r["schema"] == "q-cell-result/1"]
    observations = [r for r in rows if r["schema"] == "q-cell-obs/1"]
    assert len(actions) == len(results) == len(observations) == 12
    assert all(r["kind"] == "probe" for r in actions)
    assert all(r["target"] == FAM_B for r in actions)
    params = actions[0]["params"]
    assert params["rank"] == 1
    assert params["potential_based"] is True
    assert params["leader"] == FAM_A
    assert actions[0]["budget"]["wall_s"] == pytest.approx(
        600.0 * prober.PROBE_WALL_FRACTION)
    first = results[0]
    assert first["r_t"] is None            # never a fabricated score
    assert "rank=1/3" in first["summary"]
    assert first["verified"] is True
    # the posterior-admitting row: the fold banks the probe credit
    obs = observations[0]
    assert obs["source"] == "probe"
    assert obs["method_family"] == FAM_B
    assert obs["arm_key"] == _ak(FAM_B)
    assert obs["credit"] == pytest.approx(prober.PROBE_CREDIT_CEIL)


def test_probe_relanding_is_refused_not_double_banked(tmp_path):
    ws = tmp_path / "ws"
    plan = prober.plan_portfolio(ws, FAM_A, [FAM_B, FAM_C],
                                 signature_hash=SIG,
                                 budget=Budget(wall_s=600.0, max_calls=8))
    _record(ws, plan, n=3)
    retry = prober.record_probe(ws, plan, FAM_B,
                                rollout_id="ro-probe-00",
                                step_id="probe-b-00", rank=1,
                                verified=True, verdict="probe-win")
    assert retry["reason"] == "already-landed"
    assert retry["appended"] == {"action": False, "result": False,
                                 "observation": False}
    rows = q_cells.trajectory_rows(ws)
    assert sum(1 for r in rows if r["schema"] == "q-cell-obs/1") == 3


def test_probe_evidence_moves_the_next_assignment(tmp_path):
    empty = tmp_path / "ws-empty"
    probed = tmp_path / "ws-probed"
    plan = prober.plan_portfolio(probed, FAM_A, [FAM_B, FAM_C],
                                 signature_hash=SIG,
                                 budget=Budget(wall_s=600.0, max_calls=8))
    _record(probed, plan)
    # posterior level (deterministic): the probe's family sharpened UP
    # (exact masses at the constant gamma = 1 calibration fold)
    fold_view = q_cells.fold(q_cells.default_store(probed), gamma=1.0)
    a, b = q_cells.cell_posterior(fold_view, SIG, FAM_B)
    assert a == pytest.approx(1.0 + 8 * 10 / 14, abs=1e-9)
    assert b == pytest.approx(1.0 + 8 * 4 / 14, abs=1e-9)
    assert a / (a + b) > 0.6
    # assignment level: same ranking data, the probed family is sampled
    # MORE after its banked probe evidence (seed-controlled draws)
    before = _distribution(empty, RANKS)
    after = _distribution(probed, RANKS)
    gain = after[FAM_B] / N_DRAWS - before[FAM_B] / N_DRAWS
    assert gain > 0.03, (before, after)


def test_record_probe_reject_pins(tmp_path):
    ws = tmp_path / "ws"
    plan = prober.plan_portfolio(ws, FAM_A, [FAM_B, FAM_C],
                                 signature_hash=SIG,
                                 budget=Budget(wall_s=600.0))
    with pytest.raises(ValueError):        # the leader is not a probe arm
        prober.record_probe(ws, plan, FAM_A, rollout_id="ro-1",
                            step_id="s-1", rank=1, verified=True)
    with pytest.raises(ValueError):        # an arm outside this portfolio
        prober.record_probe(ws, plan, "crypto-core-identification",
                            rollout_id="ro-1", step_id="s-1", rank=1,
                            verified=True)
    for bad_rank in (0, 4, -1, "1", True, None, float("nan")):
        with pytest.raises(ValueError):
            prober.record_probe(ws, plan, FAM_B, rollout_id="ro-1",
                                step_id="s-1", rank=bad_rank,
                                verified=True)
    with pytest.raises(ValueError):        # not a portfolio-plan receipt
        prober.record_probe(ws, {"schema": "other/1"}, FAM_B,
                            rollout_id="ro-1", step_id="s-1", rank=1,
                            verified=True)
    assert q_cells.trajectory_rows(ws) == []


# ------------------------------------------------------- 7. determinism

def test_assign_deterministic_given_seed_and_random_zero_default(tmp_path):
    ws = tmp_path / "ws"
    r1 = _assign(ws, RANKS, rng=random.Random(0))
    r2 = _assign(ws, RANKS, rng=random.Random(0))
    assert r1 == r2
    r3 = _assign(ws, RANKS)                # the anchor-deterministic default
    assert r3 == r1
    r4 = _assign(ws, RANKS, rng=random.Random(1))
    assert r4 != r1


def test_seed_state_is_ledger_content_never_wall_clock(tmp_path):
    """Two workspaces banked with the same content (appended at
    different real times) derive the SAME seed; one more banked failure
    moves it (the contract the assigner's live callers thread)."""
    ws1 = tmp_path / "ws1"
    ws2 = tmp_path / "ws2"
    ws3 = tmp_path / "ws3"
    _bank(ws1, FAM_A, 0.0)
    _bank(ws2, FAM_A, 0.0)
    _bank(ws3, FAM_A, 0.0)
    _bank(ws3, FAM_B, 0.0)
    s1 = q_cells.q_cells_seed_state(ws1)[0].getrandbits(64)
    s2 = q_cells.q_cells_seed_state(ws2)[0].getrandbits(64)
    s3 = q_cells.q_cells_seed_state(ws3)[0].getrandbits(64)
    assert s1 == s2
    assert s1 != s3


def test_assign_under_threaded_seed_state_moves_with_evidence(tmp_path):
    """The live-caller posture: rng threaded from q_cells_seed_state.
    Same receipt for the same ledger (replay-stable); the banked
    failure moves the sampled family's posterior mass in the receipt."""
    empty = tmp_path / "ws-empty"
    banked = tmp_path / "ws-banked"
    _bank(banked, FAM_A, 0.0)
    r_empty = assigner.assign_method(
        empty, CANDIDATES, RANKS, signature_hash=SIG, tier=2,
        gamma=1.0, rng=q_cells.q_cells_seed_state(empty)[0])
    r_banked = assigner.assign_method(
        banked, CANDIDATES, RANKS, signature_hash=SIG, tier=2,
        gamma=1.0, rng=q_cells.q_cells_seed_state(banked)[0])
    assert r_empty["candidates"][FAM_A]["alpha"] == 1.0
    assert r_banked["candidates"][FAM_A]["beta"] == pytest.approx(
        1.0 + 8 * 13 / 14, abs=1e-9)
    assert math.isfinite(r_banked["candidates"][FAM_A]["theta"])
