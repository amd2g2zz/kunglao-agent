# -*- coding: utf-8 -*-
"""tests/test_optimizer_bandit_833.py — #833 机制开关 β-Bernoulli 通道。"""
from __future__ import annotations


def test_posterior_ordering():
    from optimizer_bandit import BetaPosterior
    bp = BetaPosterior()
    for _ in range(9):
        bp.update("mechA", True)
    bp.update("mechA", False)
    for _ in (0, 1):
        bp.update("mechB", True)
    for _ in range(8):
        bp.update("mechB", False)
    assert bp.posterior("mechA") > bp.posterior("mechB")
    # Beta(1,1) 先验计入：9胜1负 → (10,2) → 0.8333
    assert round(bp.posterior("mechA"), 4) == 0.8333


def pytest_approx(v):
    return round(v, 6)


def test_attribution_from_ledger_rows():
    from optimizer_bandit import BetaPosterior, attribute_rows
    bp = BetaPosterior()
    rows = [
        {"arm": "infeasible|android", "z": 1},
        {"arm": "infeasible|android", "z": 0},
        {"arm": "infeasible|android", "z": 1},
        {"arm": None, "z": 1},  # 无归因行跳过
    ]
    n = attribute_rows(bp, rows)
    assert n == 3
    # 2胜1负 + Beta(1,1) 先验 → (3,2) → 0.6
    assert round(bp.posterior("infeasible|android"), 4) == 0.6


def test_demotion_queue():
    from optimizer_bandit import BetaPosterior, demotion_queue
    bp = BetaPosterior()
    for _ in range(10):
        bp.update("bad|web", False)
    for _ in range(10):
        bp.update("good|web", True)
    q = demotion_queue(bp, floor=0.5, min_pulls=8)
    assert q == ["bad|web"]
    # min_pulls 未到不出队
    bp2 = BetaPosterior()
    bp2.update("tiny|web", False)
    assert demotion_queue(bp2, floor=0.5, min_pulls=8) == []


def test_persistence_roundtrip():
    from optimizer_bandit import BetaPosterior
    bp = BetaPosterior()
    bp.update("a|x", True)
    bp.update("a|x", False)
    d = bp.to_dict()
    bp2 = BetaPosterior.from_dict(d)
    assert bp2.posterior("a|x") == bp.posterior("a|x")
