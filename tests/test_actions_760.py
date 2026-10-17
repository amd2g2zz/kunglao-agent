# -*- coding: utf-8 -*-
"""tests/test_actions_760.py — distill joins the fixed action
vocabulary (issue 760, component A).

The MDP contract: the action set is FIXED and total — the vocabulary
admits every action and the boundary validates it like any other.
The learning mechanism is proven at the planner level: outcomes
recorded under a belief state re-price that state's distill cell and
the sampled policy follows — in both directions, with real
state-conditioning (a miskeyed observation cannot lift the wrong
cell).

The live per-claim candidate set is deliberately UNCHANGED: with no
production executor recording distill-kind returns, a cold distill
candidate in the advisory path would be permanent rank noise, not
exploration. It joins the live sets when the executor card lands.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import belief  # noqa: E402
from rlvr import l1_planner as lp  # noqa: E402
from rlvr import l1_value as lv  # noqa: E402
from rlvr import state  # noqa: E402


def _ws(tmp_path: Path, declared=None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    doc = {"claims": [{"id": "C-900", "status": "OPEN"}]}
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(doc), encoding="utf-8")
    if declared:
        meta = {"id": "F-900", "status": "PROVEN", "claim_id": "C-900",
                "unknown": list(declared)}
        (ws / "facts" / "F-900.md").write_text(
            f"---\n{yaml.safe_dump(meta)}---\n\nsynthetic\n",
            encoding="utf-8")
    return ws


def _seed_belief(ws: Path, claim: str, declared) -> None:
    """A settled belief row without the full settle ceremony."""
    belief.record_belief(ws, claim=claim, step_ref="s1",
                         evidence=[{"id": "F-900", "status": "PROVEN",
                                    "unknown": list(declared or [])}])


def test_distill_joins_the_fixed_vocabulary():
    assert "distill" in lp.ACTION_KINDS
    assert "distill" in lv.ACTION_KINDS
    # the boundary validates it like any action
    c = lp.candidate("distill", "C-900", cost=lp.DISTILL_COST)
    assert c.action_kind == "distill"


def test_plan_prices_a_distill_candidate(tmp_path):
    """plan() prices an explicitly offered distill candidate like any
    action — the interface the executor card will call."""
    ws = _ws(tmp_path)
    cands = [lp.candidate("distill", "C-900", cost=lp.DISTILL_COST),
             lp.candidate("dispatch", "C-900", cost=0.5),
             lp.candidate("park", "C-900", cost=lp.PARK_COST)]
    receipt = lp.plan(ws, cands, rng=random.Random(11))
    assert "distill/C-900" in receipt["candidates"]
    assert receipt["candidates"]["distill/C-900"]["cost"] == \
        pytest.approx(lp.DISTILL_COST)


def test_unknown_belief_states_learn_distill(tmp_path):
    """The learning pin: outcomes where distill led to settlement in a
    declared-unknown belief state re-price that state's distill cell
    until the sampled policy chooses it — with NO trigger rule
    anywhere. The learned distill ratio (1.75/1.5) dominates a cold
    dispatch's best possible ratio (2.0/2.0 = 1.0) on the mean — the
    seed-pinned run loses ~2% of draws to the tail, not the argument."""
    ws = _ws(tmp_path, declared=["unknown format grammar"])
    _seed_belief(ws, "C-900", ["unknown format grammar"])
    sig = lv.state_signature_of(ws)
    assert "|bf=u" in state.signature_str(state.snapshot(ws))
    for _ in range(6):
        lv.record_observation(ws, sig, "distill", 1.0,
                              claim="C-900", source="terminal")
    cands = [lp.candidate("distill", "C-900", cost=lp.DISTILL_COST),
             lp.candidate("dispatch", "C-900", cost=2.0),
             lp.candidate("park", "C-900", cost=lp.PARK_COST)]
    receipt = lp.plan(ws, cands, rng=random.Random(7))
    assert receipt["chosen"]["action_kind"] == "distill", (
        "a learned distill cell must outprice a cold dispatch whose "
        "best possible ratio is 1.0")


def test_dispatch_outcomes_keep_dispatch(tmp_path):
    """The control, both directions: outcomes where DISPATCH paid lift
    the dispatch cell — the policy stays on dispatch even though the
    distill candidate is offered. The learned value decides."""
    ws = _ws(tmp_path, declared=["unknown format grammar"])
    _seed_belief(ws, "C-900", ["unknown format grammar"])
    sig = lv.state_signature_of(ws)
    for _ in range(6):
        lv.record_observation(ws, sig, "dispatch", 1.0,
                              claim="C-900", source="terminal")
    cands = [lp.candidate("distill", "C-900", cost=lp.DISTILL_COST),
             lp.candidate("dispatch", "C-900", cost=2.0),
             lp.candidate("park", "C-900", cost=lp.PARK_COST)]
    # a single seed is Thompson-noise (the cold distill draws high
    # ~1/3 of the time — that IS the exploration); the DISTRIBUTION
    # is the assertion: the proven arm dominates the seed sweep
    wins = sum(
        1 for seed in range(30)
        if lp.plan(ws, cands, rng=random.Random(seed))
        ["chosen"]["action_kind"] == "dispatch")
    assert wins >= 15, f"proven dispatch won only {wins}/30 seeds"


def test_state_conditioning_is_real(tmp_path):
    """The cell keying is the state-conditioning: distill outcomes
    recorded under the declared-unknown signature lift THAT cell and
    leave an unkeyed signature's distill cell exactly cold. A
    miskeyed observation cannot teach the wrong state."""
    ws = _ws(tmp_path, declared=["unknown format grammar"])
    _seed_belief(ws, "C-900", ["unknown format grammar"])
    sig_u = lv.state_signature_of(ws)
    for _ in range(6):
        lv.record_observation(ws, sig_u, "distill", 1.0,
                              claim="C-900", source="terminal")
    fold = lv.fold(lv.default_store(ws), gamma=1.0)
    learned = lv.cell_posterior(fold, sig_u, "distill")
    cold = lv.cell_posterior(fold, sig_u + "x", "distill")  # unkeyed
    assert learned[0] > 5.0 and learned[1] <= 1.0
    assert cold == (1.0, 1.0)


def test_reuse_still_wins_when_solved(tmp_path):
    """Regression: the cheap replay (ratio 10 at strength 1.0) must
    dominate an unproven distill for a solved claim."""
    ws = _ws(tmp_path, declared=["unknown format grammar"])
    _seed_belief(ws, "C-900", ["unknown format grammar"])
    meta = {"id": "F-901", "status": "PROVEN", "claim_id": "C-900"}
    (ws / "facts" / "F-901.md").write_text(
        f"---\n{yaml.safe_dump(meta)}---\n\nsynthetic\n", encoding="utf-8")
    # the knowledge face reads the EvidenceView index, not the files
    (ws / "facts" / "_INDEX.md").write_text(
        "F-901 | PROVEN | C-900 | synthetic\n", encoding="utf-8")
    cands = [lp.candidate("distill", "C-900", cost=lp.DISTILL_COST),
             lp.candidate("dispatch", "C-900", cost=0.5),
             lp.candidate("reuse", "C-900", cost=lp.REUSE_COST,
                          value_hint=1.0),
             lp.candidate("park", "C-900", cost=lp.PARK_COST)]
    receipt = lp.plan(ws, cands, rng=random.Random(7))
    assert receipt["chosen"]["action_kind"] == "reuse"
    assert (receipt["candidates"]["reuse/C-900"]["ratio"]
            > receipt["candidates"]["distill/C-900"]["ratio"])


def test_live_advisory_path_is_unchanged(tmp_path):
    """plan_for_claim's live set is deliberately unchanged (no
    executor for distill-kind returns yet): an unsolved claim's
    dispatch share stays exactly 1.0, and the advisory face stays
    dormant while the value store is empty."""
    ws = _ws(tmp_path)
    assert lp.advisory_factors(ws, [("C-900", 1.0)]) == {}
    receipt = lp.plan_for_claim(ws, "C-900", dispatch_cost=0.5,
                                rng=random.Random(7))
    assert "distill/C-900" not in receipt["candidates"]
    _seed_belief(ws, "C-900", ["unknown format grammar"])
    sig = lv.state_signature_of(ws)
    lv.record_observation(ws, sig, "dispatch", 0.5,
                          claim="C-900", source="terminal")
    factors = lp.advisory_factors(ws, [("C-900", 1.0)],
                                  rng=random.Random(4))
    assert factors["C-900"] == pytest.approx(1.0)
