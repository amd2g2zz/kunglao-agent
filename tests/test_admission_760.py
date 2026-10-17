# -*- coding: utf-8 -*-
"""tests/test_admission_760.py — the sampled policy's output cardinality
(issue 760, component π).

The policy's output is one-or-more actions, never a fixed count and
never unbounded: with a budget, plan() admits candidates greedily in
sampled-ratio order while the budget lasts; without a budget, plan()
keeps today's single-winner shape byte-for-byte. Park is the
always-fits floor; an all-negative decision set falls to it.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import sys
from pathlib import Path


import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import l1_planner as lp  # noqa: E402


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    return ws


def _hinted(claim: str, hint: float, cost: float) -> object:
    """A value-hinted candidate: deterministic ratio = hint / cost —
    no Thompson draw (the hint is graded known value)."""
    return lp.candidate("reuse", claim, cost=cost, value_hint=hint)


def test_budget_admits_in_ratio_order(tmp_path):
    ws = _ws(tmp_path)
    cands = [_hinted("C-A", 1.0, 0.10),    # ratio 10
             _hinted("C-B", 0.5, 0.25),    # ratio 2
             _hinted("C-C", 0.4, 1.00)]    # ratio 0.4
    receipt = lp.plan(ws, cands, budget=1.35, rng=None)
    assert receipt["admitted"] == ["reuse/C-A", "reuse/C-B",
                                   "reuse/C-C"]


def test_budget_exhaustion_stops_admission(tmp_path):
    ws = _ws(tmp_path)
    cands = [_hinted("C-A", 1.0, 0.10),    # ratio 10, cost 0.10
             _hinted("C-B", 0.5, 0.25)]    # ratio 2,  cost 0.25
    receipt = lp.plan(ws, cands, budget=0.10 + 0.25 - 0.001, rng=None)
    assert receipt["admitted"] == ["reuse/C-A"]
    assert receipt["chosen"]["action_kind"] == "reuse"


def test_greedy_skips_a_non_fitting_leader(tmp_path):
    """Greedy by ratio, skip-if-no-fit: a leader too big for the rest
    of the budget is skipped and the next ratio still lands."""
    ws = _ws(tmp_path)
    cands = [_hinted("C-big", 1.0, 0.90),   # ratio 10, cost 0.90
             _hinted("C-small", 0.5, 0.10)]  # ratio 5,  cost 0.10
    receipt = lp.plan(ws, cands, budget=0.15, rng=None)
    assert receipt["admitted"] == ["reuse/C-small"]


def test_zero_budget_admits_park_only(tmp_path):
    ws = _ws(tmp_path)
    cands = [_hinted("C-A", 1.0, 0.10),
             lp.candidate("park", "C-A", cost=lp.PARK_COST)]
    receipt = lp.plan(ws, cands, budget=0.0, rng=None)
    assert receipt["admitted"] == ["park/C-A"]
    assert receipt["chosen"]["action_kind"] == "park"


def test_all_negative_falls_to_park(tmp_path):
    ws = _ws(tmp_path)
    cands = [_hinted("C-A", -0.5, 0.10),   # negative known value
             lp.candidate("park", "C-A", cost=lp.PARK_COST)]
    receipt = lp.plan(ws, cands, budget=10.0, rng=None)
    assert receipt["chosen"]["action_kind"] == "park"
    assert receipt["admitted"] == ["park/C-A"]


def test_no_budget_is_the_legacy_single_winner(tmp_path):
    """Without a budget, today's shape: exactly one admitted action —
    the best ratio — byte-compatible with every existing consumer."""
    ws = _ws(tmp_path)
    cands = [_hinted("C-A", 1.0, 0.10), _hinted("C-B", 0.5, 0.25)]
    receipt = lp.plan(ws, cands, rng=None)
    assert receipt["admitted"] == [receipt["chosen"]["key"]]


def test_plan_for_claim_carries_the_admitted_set(tmp_path):
    ws = _ws(tmp_path)
    receipt = lp.plan_for_claim(ws, "C-900", dispatch_cost=0.5,
                                rng=None)
    assert receipt["admitted"] == [receipt["chosen"]["key"]]


def test_no_park_nothing_fits_returns_the_best_ranked(tmp_path):
    """The honest edge, disclosed in _admit's docstring: no park
    offered and nothing fitting -> the fallback returns the
    best-ranked action over budget (the caller's own offering
    decides; never a fabricated park)."""
    ws = _ws(tmp_path)
    cands = [_hinted("C-A", 1.0, 0.90)]   # ratio 10, cost 0.90
    receipt = lp.plan(ws, cands, budget=0.0, rng=None)
    assert receipt["admitted"] == ["reuse/C-A"]
    assert receipt["chosen"]["key"] == "reuse/C-A"


def test_budget_boundary_rejects_nan_and_bool(tmp_path):
    ws = _ws(tmp_path)
    cands = [_hinted("C-A", 1.0, 0.10)]
    for bad in (float("nan"), True, float("inf"), -1.0):
        with pytest.raises(ValueError):
            lp.plan(ws, cands, budget=bad, rng=None)


def test_park_never_steals_the_head(tmp_path):
    """Park (ratio 0 by ruling) never outranks a positive action in
    the admission order — it enters only as the floor."""
    ws = _ws(tmp_path)
    cands = [_hinted("C-A", 0.2, 0.10),    # ratio 2
             lp.candidate("park", "C-A", cost=lp.PARK_COST)]
    receipt = lp.plan(ws, cands, budget=1.0, rng=None)
    assert receipt["admitted"][0] == "reuse/C-A"
    assert receipt["admitted"][-1] == "park/C-A"
