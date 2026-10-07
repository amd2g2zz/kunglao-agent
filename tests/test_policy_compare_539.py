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
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "runs").mkdir(exist_ok=True)
    audit = ws / "runs" / "logs" / "e2e-audit.jsonl"
    trans = ws / "runs" / "transitions.jsonl"
    with audit.open("w", encoding="utf-8") as fa, \
            trans.open("w", encoding="utf-8") as ft:
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
            ft.write(json.dumps({
                "dispatch_id": d["claim"], "a": d["family"],
                "r_incr": d["reward"], "r_settle": 0.0}) + "\n")
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
    assert rep["decisions"] == 5

    mixed = _ws(tmp_path / "b", [
        {"claim": f"C-{i:03d}", "family": "alpha-arm", "weights": W2,
         "propensity": 0.8, "reward": 1.0} for i in range(45)] + [
        {"claim": "C-999", "family": "beta-arm", "weights": W2,
         "propensity": None, "reward": 1.0}])
    rep2 = pc.compare(mixed, bootstrap=0)
    assert rep2["decisions"] == 45
    assert rep2["skipped_no_propensity"] == 1
    assert rep2["verdict"]["best"] in pc.POLICIES
