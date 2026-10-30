# -*- coding: utf-8 -*-
"""tests/test_rl_v2_credit_883.py — the credit assignment face (883).

RED-first pins for the learning loop's credit faces:

  1. discounted returns — the sparse/delayed scenario from the issue
     (r_1..r_5 = 0, r_6 = large): the γ-discounted advantage reaches
     every earlier step at the exact discount factor;
  2. terminal shaping — completion adds the bonus, a ROLLBACK's
     negative terminal flips the whole trajectory's advantage;
  3. advantage — cold start (V = 0, values absent) leaves A = raw
     returns EXACTLY (the expected pinned case); with a baseline the
     subtraction is exact;
  4. confidence modulation (EMxPG-style) — confident-correct earns
     strictly more than uncertain-correct; zero confidence banks zero;
  5. lineage flowback — a spawned chain flows the child's credited
     return back through the parent at the lineage γ; a cycle raises;
  6. the ledger read face — rollout rewards in append order, pending
     steps (r_t=None) skipped;
  7. fail-closed reject pins.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from credit import advantage, lineage, returns  # noqa: E402
from rlvr import q_cells  # noqa: E402

GAMMA = 0.9


# ------------------------------------------------------ returns face

def test_sparse_delayed_advantage_distributed_by_gamma():
    r = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 10.0])
    R = returns.discounted_returns(r, GAMMA)
    assert R[5] == pytest.approx(10.0)
    assert R[4] == pytest.approx(GAMMA * 10.0)
    assert R[0] == pytest.approx(GAMMA ** 5 * 10.0)


def test_terminal_shaping_completion_and_rollback():
    r = np.array([0.1, 0.1, 0.1])
    done = returns.terminal_shaped(r, GAMMA, terminal="completed",
                                   terminal_bonus=2.0)
    assert done[-1] == pytest.approx(0.1 + 2.0)
    back = returns.terminal_shaped(r, GAMMA, terminal="rolled_back",
                                   terminal_bonus=2.0)
    assert back[-1] == pytest.approx(0.1 - 2.0)
    A = advantage.advantages(
        returns.discounted_returns(back, GAMMA), None)
    assert (A < 0).all()          # the whole trajectory is negative


def test_terminal_status_is_closed_vocab():
    with pytest.raises(ValueError):
        returns.terminal_shaped(np.array([1.0]), GAMMA, terminal="meh",
                                terminal_bonus=1.0)


# ---------------------------------------------------- advantage face

def test_cold_start_advantage_is_raw_returns():
    R = np.array([0.5, 1.2, 0.3])
    A = advantage.advantages(R, None)
    assert np.array_equal(A, R)   # V = 0 exactly, the pinned case


def test_advantage_with_baseline_subtracts_exactly():
    R = np.array([0.5, 1.2, 0.3])
    V = np.array([0.2, 0.9, 0.4])
    A = advantage.advantages(R, V)
    assert np.allclose(A, R - V)


def test_confidence_modulation_orders_confident_over_uncertain():
    A = np.array([1.0, 1.0])
    conf = np.array([0.9, 0.4])
    weighted = advantage.modulate(A, conf)
    assert weighted[0] > weighted[1]
    zero = advantage.modulate(np.array([1.0]), np.array([0.0]))
    assert zero[0] == 0.0
    with pytest.raises(ValueError):
        advantage.modulate(np.array([1.0]), np.array([1.5]))


# ------------------------------------------------------ lineage face

def test_lineage_credit_flows_through_spawn_chain():
    ret = {"ro-A": 1.0, "ro-B": 0.4, "ro-C": 2.0}
    parent = {"ro-A": None, "ro-B": "ro-A", "ro-C": "ro-B"}
    out = lineage.flowback(ret, parent, gamma_lineage=0.5)
    assert out["ro-C"] == pytest.approx(2.0)
    assert out["ro-B"] == pytest.approx(0.4 + 0.5 * 2.0)
    assert out["ro-A"] == pytest.approx(1.0 + 0.5 * (0.4 + 0.5 * 2.0))


def test_lineage_cycle_raises():
    with pytest.raises(ValueError):
        lineage.flowback({"a": 1.0, "b": 1.0},
                         {"a": "b", "b": "a"}, gamma_lineage=0.5)
    with pytest.raises(ValueError):
        lineage.flowback({"a": 1.0}, {"a": "a"}, gamma_lineage=0.5)


def test_lineage_child_without_parent_entry_is_orphan_root():
    out = lineage.flowback({"ro-X": 3.0, "ro-Y": 1.0},
                           {"ro-Y": "ro-X"}, gamma_lineage=0.5)
    assert out["ro-Y"] == pytest.approx(1.0)
    assert out["ro-X"] == pytest.approx(3.0 + 0.5 * 1.0)


# --------------------------------------------------- ledger read face

def test_rollout_rewards_from_the_ledger(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="select_task", rollout_id="ro-1",
                          target="C-1")
    for i, r in enumerate([0.1, None, 0.3]):
        q_cells.append_result(ws, rollout_id="ro-1", step_id=f"s-{i}",
                              r_t=r, verified=bool(r))
    q_cells.append_result(ws, rollout_id="ro-OTHER", step_id="s-0",
                          r_t=9.9, verified=True)
    rewards = returns.rollout_rewards(ws, "ro-1")
    assert isinstance(rewards, np.ndarray)
    assert rewards.tolist() == [0.1, 0.3]     # append order; pending skipped


# ------------------------------------------------------- reject pins

def test_reject_pins():
    with pytest.raises(ValueError):
        returns.discounted_returns(np.array([0.0, float("nan")]), GAMMA)
    with pytest.raises(ValueError):
        returns.discounted_returns(np.array([1.0]), 0.0)
    with pytest.raises(ValueError):
        returns.discounted_returns(np.array([1.0]), 1.0)
    with pytest.raises(ValueError):
        lineage.flowback({"a": float("inf")}, {"a": None},
                         gamma_lineage=0.5)
