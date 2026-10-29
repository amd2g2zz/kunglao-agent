# -*- coding: utf-8 -*-
"""tests/test_rl_v2_core_types_878.py — the rl-v2 core types (issue 878).

RED-first pins for the trajectory-semantics foundation:

  1. the action/1 schema: the closed action-kind enum, fail-closed
     parse (reject pins per field class), the frozen Action value
     object, and the to_doc round-trip;
  2. the State / StepResult / RolloutResult / Transition value
     objects (type stubs the downstream cards consume);
  3. the core package-root facade — every public type importable from
     ``core`` in one import face;
  4. q_cells v2 rows: action rows (kind / rollout_id / step_id /
     target / params / budget) and result rows (r_t + the R_t / A_t
     credit columns) round-trip through the consolidated experience
     ledger, and the v2 trajectory read returns OLD q-cell-obs/1 rows
     unchanged (backward-compatible reads).
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import core  # noqa: E402
from core import (  # noqa: E402
    ActionError,
    ActionKind,
    Budget,
    Context,
    RolloutResult,
    State,
    StepResult,
    Transition,
    TransitionEvent,
    action_to_doc,
    parse_action,
)
from rlvr import q_cells  # noqa: E402

ACTION_KINDS = ("select_task", "decompose", "assign_step", "probe",
                "switch_method", "terminate_step", "terminate_rollout",
                "rollback", "spawn_candidate", "materialize")


def _action_doc(**over):
    doc = {
        "schema": "action/1",
        "kind": "assign_step",
        "target": "step-3",
        "params": {"method_family": "mod-crypto", "tier": 2},
        "budget": {"wall_s": 600.0, "max_calls": None},
        "context": {"rollout_id": "ro-1", "step_id": "s-3",
                    "policy_version": "v2"},
    }
    doc.update(over)
    return doc


# ------------------------------------------------------------- action/1

def test_action_kind_is_the_closed_enum():
    assert tuple(k.value for k in ActionKind) == ACTION_KINDS


def test_parse_action_accepts_and_builds_frozen_value():
    a = parse_action(_action_doc())
    assert a.kind is ActionKind.ASSIGN_STEP
    assert a.target == "step-3"
    assert a.params == {"method_family": "mod-crypto", "tier": 2}
    assert a.budget == Budget(wall_s=600.0, max_calls=None)
    assert a.context == Context(rollout_id="ro-1", step_id="s-3",
                                policy_version="v2")
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.kind = ActionKind.PROBE


def test_action_to_doc_round_trip():
    doc = _action_doc()
    assert action_to_doc(parse_action(doc)) == doc


@pytest.mark.parametrize("over", [
    {"schema": "action/2"},
    {"kind": "teleport"},
    {"kind": None},
    {"kind": 123},
    {"target": "  "},
    {"params": ["not", "a", "mapping"]},
    {"budget": {"wall_s": -1.0}},
    {"budget": {"wall_s": float("nan")}},
    {"budget": {"wall_s": float("inf")}},
    {"budget": {"wall_s": True}},
    {"budget": {"wall_s": 600.0, "max_calls": 0}},
    {"budget": "600s"},
    {"context": {"rollout_id": "", "policy_version": "v2"}},
    {"context": {"rollout_id": "ro-1"}},
])
def test_parse_action_reject_pins(over):
    with pytest.raises(ActionError):
        parse_action(_action_doc(**over))


# ------------------------------------------------- value-object stubs

def test_state_value_object():
    s = State(goal_tree={"goal": "recover the key",
                         "subgoals": ["derive K", "recover mode"]},
              fact_base=("F-001", "F-002"),
              memory={"pattern_cards": ()},
              resources=Budget(wall_s=1200.0))
    assert s.fact_base == ("F-001", "F-002")
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.fact_base = ()


def test_step_and_rollout_results():
    r = StepResult(step_id="s-1", verified=True,
                   evidence_refs=("facts/F001.md",),
                   summary="K-array recovered", cost=0.4, verdict="pass",
                   redteam=None, confidence=0.9)
    ro = RolloutResult(rollout_id="ro-1", completed=True, steps=(r,),
                       total_cost=0.4)
    assert ro.steps[0].verified is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.verified = False


def test_transition_event_carries_payload():
    ev = TransitionEvent(transition=Transition.STEP_COMPLETED,
                         rollout_id="ro-1", step_id="s-1",
                         action=None, reward=0.25,
                         payload={"verified": True})
    assert ev.transition is Transition.STEP_COMPLETED
    assert ev.reward == 0.25
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.reward = 0.9


def test_core_package_root_facade():
    for name in ("Action", "ActionError", "ActionKind", "Budget",
                 "Context", "RolloutResult", "State", "StepResult",
                 "Transition", "TransitionEvent", "action_to_doc",
                 "parse_action"):
        assert hasattr(core, name), name
    for name in core.__all__:
        assert getattr(core, name) is not None


# --------------------------------------------------- q_cells v2 rows

def _sig():
    return "a" * 12


def test_q_cells_v2_action_row_round_trip(tmp_path):
    ws = tmp_path / "ws"
    out = q_cells.append_action(ws, kind="select_task",
                                rollout_id="ro-1", step_id=None,
                                target="claim-C-001",
                                params={"k": 5},
                                budget={"wall_s": 600.0,
                                        "max_calls": None},
                                policy_version="v2")
    assert out["appended"] is True
    rows = q_cells.trajectory_rows(ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == "q-cell-action/1"
    assert row["kind"] == "select_task"
    assert row["rollout_id"] == "ro-1"
    assert row["step_id"] is None
    assert row["target"] == "claim-C-001"
    assert row["params"] == {"k": 5}
    assert row["budget"] == {"wall_s": 600.0, "max_calls": None}
    assert row["policy_version"] == "v2"


def test_q_cells_v2_result_row_carries_credit_columns(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                          r_t=0.25, verified=True, cost=0.4,
                          verdict="pass",
                          evidence_refs=("facts/F001.md",),
                          summary="K recovered", R_t=0.7, A_t=0.1)
    (row,) = q_cells.trajectory_rows(ws)
    assert row["schema"] == "q-cell-result/1"
    assert row["r_t"] == 0.25
    assert row["R_t"] == 0.7
    assert row["A_t"] == 0.1
    assert row["evidence_refs"] == ["facts/F001.md"]


def test_q_cells_v2_result_row_pending_and_additive_columns(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_result(ws, rollout_id="ro-1", step_id="s-2",
                          r_t=None, verified=False, cost=0.2,
                          verdict="fail")
    (row,) = q_cells.trajectory_rows(ws)
    assert row["r_t"] is None
    assert "R_t" not in row          # the additive-column discipline
    assert "A_t" not in row


def test_q_cells_v2_trajectory_read_is_backward_compatible(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_observation(ws, _sig(), "mod-crypto", None,
                               source="dispatch",
                               arm_key_col="mod-crypto|facts_snapshot"
                                          "|none|0")
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-1",
                          step_id="s-1", target="step-1")
    q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                          r_t=0.5, verified=True, cost=0.1,
                          verdict="pass")
    rows = q_cells.trajectory_rows(ws)
    assert [r["schema"] for r in rows] == [
        "q-cell-obs/1", "q-cell-action/1", "q-cell-result/1"]
    old = rows[0]
    assert old["source"] == "dispatch"
    assert old["method_family"] == "mod-crypto"
    # a v2-era file holding ONLY old rows still reads (old ws replay)
    ws_old = tmp_path / "ws-old"
    q_cells.append_observation(ws_old, _sig(), "arm-kdf", 1.0,
                               source="settlement",
                               arm_key_col="arm-kdf|facts_snapshot"
                                          "|none|0")
    assert [r["schema"] for r in q_cells.trajectory_rows(ws_old)] == [
        "q-cell-obs/1"]


def test_q_cells_v2_append_fails_closed_on_structural_garbage(tmp_path):
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        q_cells.append_action(ws, kind="select_task", rollout_id="",
                              target="x")
    with pytest.raises(ValueError):
        q_cells.append_action(ws, kind=123, rollout_id="ro-1", target="x")
    with pytest.raises(ValueError):
        q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                              r_t="high", verified=True)
    with pytest.raises(ValueError):
        q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                              r_t=float("inf"), verified=True)
    with pytest.raises(ValueError):
        q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                              r_t=True, verified=True)
    with pytest.raises(ValueError):
        q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                              r_t=0.5, verified="no")
    with pytest.raises(ValueError):
        q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                              r_t=0.5, verified=True, cost=-1.0)
    with pytest.raises(ValueError):
        q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                              r_t=0.5, verified=True, R_t="lots")
