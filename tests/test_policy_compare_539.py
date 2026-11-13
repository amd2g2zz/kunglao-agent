# -*- coding: utf-8 -*-
"""Issue #539 PR-2 — the offline policy comparison (ε-greedy as control).

Pins:
  1. SNIPS arithmetic on a hand-computable decision set;
  2. π shapes (uniform 1/K, ε-greedy greedy+ε/K, thompson weight/total);
  3. the underpowered gate (below MIN_DECISIONS: no ranking);
  4. rows without propensity are skipped and counted, never imputed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RLVR = ROOT / "scripts"
if str(RLVR) not in sys.path:
    sys.path.insert(0, str(RLVR))

from rlvr import policy_compare as pc  # noqa: E402


def _ws(tmp_path, decisions: list[dict]) -> Path:
    """decisions: [{claim, family, weights, propensity, reward}]"""
    from rlvr import consolidated_ledger as _cl
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "runs").mkdir(exist_ok=True)
    audit = ws / "runs" / "logs" / "e2e-audit.jsonl"
    with audit.open("w", encoding="utf-8") as fa:
        for i, d in enumerate(decisions):
            fa.write(json.dumps({
                "event": "method_family_recorded", "claim": d["claim"],
                "detail": {"method_family": d["family"],
                           "envelope": {
                               "family": d["family"],
                               "propensity": d["propensity"],
                               "candidates": {
                                   k: {"weight": w}
                                   for k, w in d["weights"].items()}}}}) + "\n")
            _cl.append(ws, "experience", {
                "schema": "transition/1", "dispatch_id": d["claim"],
                "a": d["family"], "r_incr": d["reward"], "r_settle": 0.0})
    return ws


W2 = {"alpha-arm": 0.8, "beta-arm": 0.2}


def test_pi_shapes():
    assert pc._pi("uniform", "alpha-arm", W2) == 0.5
    assert pc._pi("eps-greedy", "alpha-arm", W2) == \
        0.9 * 1.0 + 0.1 / 2
    assert pc._pi("eps-greedy", "beta-arm", W2) == 0.1 / 2
    assert abs(pc._pi("thompson", "alpha-arm", W2) - 0.8) < 1e-9
    assert abs(pc._pi("thompson", "beta-arm", W2) - 0.2) < 1e-9


def test_snips_hand_computed():
    # two decisions, both chose alpha-arm under p=0.8, rewards 1.0/0.0
    ds = [{"family": "alpha-arm", "weights": W2, "propensity": 0.8,
           "reward": 1.0},
          {"family": "alpha-arm", "weights": W2, "propensity": 0.8,
           "reward": 0.0}]
    # thompson: w = 0.8/0.8 = 1 each -> V = 0.5
    est = pc.snips(ds, "thompson")
    assert abs(est["value"] - 0.5) < 1e-9
    # uniform: w = 0.5/0.8 = 0.625 each -> same V (only scale changes)
    assert abs(pc.snips(ds, "uniform")["value"] - 0.5) < 1e-9
    # eps-greedy: w = 0.95/0.8 = 1.1875 -> V still 0.5
    assert abs(pc.snips(ds, "eps-greedy")["value"] - 0.5) < 1e-9


def test_snips_separates_when_choice_diverges():
    # the behavior chose the LOW-weight arm once: uniform upweights that
    # decision (w = 0.5/0.2 > 1), thompson downweights it (0.2/0.2)
    ds = [{"family": "alpha-arm", "weights": W2, "propensity": 0.8,
           "reward": 0.0},
          {"family": "beta-arm", "weights": W2, "propensity": 0.2,
           "reward": 1.0}]
    # thompson: V = (1*0 + 1*1)/2 = 0.5
    assert abs(pc.snips(ds, "thompson")["value"] - 0.5) < 1e-9
    # uniform: w1 = .625, w2 = 2.5 -> V = 2.5/(3.125) = 0.8
    assert abs(pc.snips(ds, "uniform")["value"] - 0.8) < 1e-9


def test_underpowered_gate_and_propensity_skip(tmp_path):
    small = _ws(tmp_path, [
        {"claim": "C-004", "family": "alpha-arm", "weights": W2,
         "propensity": 0.8, "reward": 1.0}] * 5)
    rep = pc.compare(small, bootstrap=0)
    assert rep["verdict"] == "underpowered"
    assert rep["decisions"] == 0
    assert rep["skipped_ambiguous_dispatch"] == 5

    mixed = _ws(tmp_path / "b", [
        {"claim": f"C-{i:03d}", "family": "alpha-arm", "weights": W2,
         "propensity": 0.8, "reward": 1.0} for i in range(45)] + [
        {"claim": "C-999", "family": "beta-arm", "weights": W2,
         "propensity": None, "reward": 1.0}])
    rep2 = pc.compare(mixed, bootstrap=0)
    assert rep2["decisions"] == 0
    assert rep2["skipped_no_propensity"] == 1
    assert rep2["skipped_unknown_probability"] == 45
    assert rep2["verdict"] == "underpowered"


def test_snips_keeps_reward_aligned_when_target_weight_is_zero():
    decisions = [
        {"family": "alpha-arm", "weights": {"alpha-arm": 0.0, "beta-arm": 1.0},
         "propensity": 1.0, "reward": 0.0},
        {"family": "beta-arm", "weights": {"alpha-arm": 0.0, "beta-arm": 1.0},
         "propensity": 1.0, "reward": 1.0},
    ]
    for rows in (decisions, list(reversed(decisions))):
        result = pc.snips(rows, "thompson")
        assert result == {"value": 1.0, "ess": 1.0}


def test_snips_skips_invalid_contributions_without_misaligning_rewards():
    valid = {"family": "beta-arm", "weights": {"alpha-arm": 0.0, "beta-arm": 1.0},
             "propensity": 0.5, "reward": 1.0}
    bad = [
        {**valid, "propensity": None, "reward": 0.0},
        {**valid, "propensity": 0.0, "reward": 0.0},
        {**valid, "propensity": float("nan"), "reward": 0.0},
        {**valid, "propensity": float("inf"), "reward": 0.0},
        {**valid, "propensity": 1.1, "reward": 0.0},
        {**valid, "weights": {"beta-arm": float("inf")}, "reward": 0.0},
        {**valid, "reward": float("nan")},
    ]
    assert pc.snips(bad + [valid], "thompson") == {"value": 1.0, "ess": 1.0}
    assert pc.snips(bad, "thompson") == {"value": None, "ess": 0.0}


def test_snips_bootstrap_does_not_shift_rewards_after_zero_weights():
    rows = [
        {"family": "alpha-arm", "weights": {"alpha-arm": 0.0, "beta-arm": 1.0},
         "propensity": 1.0, "reward": 0.0},
        {"family": "beta-arm", "weights": {"alpha-arm": 0.0, "beta-arm": 1.0},
         "propensity": 1.0, "reward": 1.0},
    ]
    assert pc._bootstrap_ci(rows, "thompson", 100, seed=7) == [1.0, 1.0]


def test_snips_finite_extreme_rewards_keep_finite_mean_and_bootstrap():
    rows = [{"family": "a", "weights": {"a": 1.0},
             "propensity": 1.0, "reward": 1e308}] * 2
    assert pc.snips(rows, "thompson") == {"value": 1e308, "ess": 2.0}
    assert pc._bootstrap_ci(rows, "thompson", 50, seed=7) == [1e308, 1e308]


def test_snips_finite_extreme_candidate_weights_preserve_distribution():
    weights = {"a": 1e308, "b": 1e308}
    rows = [{"family": "a", "weights": weights,
             "propensity": 0.5, "reward": 1.0},
            {"family": "b", "weights": weights,
             "propensity": 0.5, "reward": 0.0}]
    assert pc._pi("thompson", "a", weights) == 0.5
    assert pc.snips(rows, "thompson") == {"value": 0.5, "ess": 2.0}


def test_bootstrap_with_no_valid_replicate_is_unavailable():
    valid = {"family": "a", "weights": {"a": 1.0},
             "propensity": 1.0, "reward": 1.0}
    invalid = {**valid, "propensity": 0.0, "reward": 0.0}
    decisions = [valid] + [invalid] * 99
    assert pc.snips(decisions, "thompson") == {"value": 1.0, "ess": 1.0}
    assert pc._bootstrap_ci(decisions, "thompson", 1, seed=7) is None


def test_compare_does_not_rank_unverified_legacy_bootstrap_data(tmp_path):
    rows = [{"claim": "C-000", "family": "a", "weights": {"a": 1.0},
             "propensity": 1.0, "reward": 1.0}]
    rows += [{"claim": f"C-{i:03}", "family": "a", "weights": {"a": 1.0},
              "propensity": 0.0, "reward": 0.0} for i in range(1, 100)]
    result = pc.compare(_ws(tmp_path, rows), bootstrap=1)
    assert result["decisions"] == 0
    assert result["skipped_unknown_probability"] == 1
    assert result["skipped_invalid_probability"] == 99
    assert result["verdict"] == "underpowered"
