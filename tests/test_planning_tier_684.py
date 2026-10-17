# -*- coding: utf-8 -*-
"""tests/test_planning_tier_684.py — the planning tier: claim-economy
changes are settleable actions, not mechanical side effects.

The action registry carried exactly two planning-adjacent verbs and
neither managed the candidate set: mint / split / supersede / park /
rewire were mechanisms fired by detectors, never chosen by the policy
and never credited. This module pins the tier (registry + settleability
+ the escrow/revoke attribution discipline).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import action_space as aspace  # noqa: E402
import planning_actions as pa  # noqa: E402

EXPECTED_POLICY = {"mint_arm", "split_claim", "supersede", "park",
                   "rewire_deps", "replan"}


def _bare(level: str) -> set[str]:
    return {s.name.split(".", 1)[1] for s in aspace.actions_of(level)}


# ---------- registry: the policy tier ----------

def test_policy_tier_is_registered_and_complete():
    assert hasattr(aspace, "POLICY")
    assert _bare(aspace.POLICY) == EXPECTED_POLICY
    # replan moved here from orchestration — one replan, at the tier
    # that owns candidate-set changes
    assert "orchestration.replan" not in aspace.ACTIONS
    assert "policy.replan" in aspace.ACTIONS


def test_policy_actions_are_settleable():
    """Every planning-tier action is settleable: it escrows with its
    producing step and can be revoked against it (the evidence-credit
    discipline applied to candidate-set changes)."""
    for name in sorted(EXPECTED_POLICY):
        spec = aspace.ACTIONS[f"policy.{name}"]
        assert spec.level == aspace.POLICY
        assert spec.settleable is True, name
        assert spec.delta_estimator.implemented is False


def test_plan_segment_is_a_worker_domain_verb():
    """plan_segment is demoted out of planning: it organizes the
    worker's own plan steps (the plan-first contract makes planning the
    worker's first act), never the claim economy's candidate set."""
    spec = aspace.ACTIONS["operator.plan_segment"]
    assert spec.consumer.startswith("worker")
    assert spec.settleable is False


def test_mint_arm_is_a_settleable_action_with_propensity():
    """mint / split / supersede are policy actions with propensity: the
    record face logs the sampling propensity beside the producing step,
    and refuses actions outside the settleable tier."""
    import tempfile
    # outside the tier: a worker verb changes no candidate set
    with tempfile.TemporaryDirectory() as td:
        assert pa.record(td, "operator.observe", step_ref="call-1") is None
        assert pa.read_actions(td) == []  # the refusal wrote nothing
    # inside the tier: the row carries the propensity + producing step
    with tempfile.TemporaryDirectory() as td:
        row = pa.record(td, "policy.mint_arm", step_ref="call-42",
                        claim_ref="C-7", propensity=0.3)
        assert row["action"] == "policy.mint_arm"
        assert row["step_ref"] == "call-42"
        assert row["claim_ref"] == "C-7"
        assert row["propensity"] == 0.3
        rows = pa.read_actions(td)
        assert [r["id"] for r in rows] == [row["id"]]
    # split and supersede share the discipline
    with tempfile.TemporaryDirectory() as td:
        for action in ("policy.split_claim", "policy.supersede"):
            r = pa.record(td, action, step_ref="call-9", propensity=0.5)
            assert r["action"] == action and r["propensity"] == 0.5
    # a bad propensity is refused at the boundary, fail-open (None + warn)
    with tempfile.TemporaryDirectory() as td:
        assert pa.record(td, "policy.mint_arm", step_ref="c",
                         propensity=1.5) is None
        assert pa.record(td, "policy.mint_arm", step_ref="c",
                         propensity=-0.1) is None
        assert pa.read_actions(td) == []  # refusals wrote nothing
    # empty step_ref: a planning action must name its producing step
    with tempfile.TemporaryDirectory() as td:
        assert pa.record(td, "policy.mint_arm", step_ref="   ") is None
        assert pa.read_actions(td) == []  # nothing recorded, nothing lost


def test_supersede_is_revocable_against_producing_step():
    """A planning action that later refutes is revocable against the
    step that proposed it — the revoke row names the producing step,
    never a verifier or consumer step (the evidence-credit rule)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        row = pa.record(td, "policy.supersede", step_ref="call-7",
                        claim_ref="C-3", propensity=0.5)
        rev = pa.revoke(td, row["id"], reason="the successor refuted")
        assert rev is not None
        assert rev["action"] == "revoke"
        assert rev["action_id"] == row["id"]
        assert rev["step_ref"] == "call-7"  # the producing step
        assert rev["reason"] == "the successor refuted"
        # one revocation per action — a second is refused (None + warn)
        assert pa.revoke(td, row["id"]) is None
        # an unknown id is refused, never invented
        assert pa.revoke(td, "no-such-id") is None
