# -*- coding: utf-8 -*-
"""tests/test_rl_v2_action_params_924.py — the parameterized action
space (issue 924).

Pins for the per-kind param spec + the explicit dispatch
width (written before the faces they pin — the TDD order):

  SPEC      ACTION_PARAM_SPECS covers ALL TEN ActionKinds; the table
            and every spec entry are frozen (immutability);
  WALLS     normalize_params, parse_action, and q_cells.append_action
            all enforce the ONE spec fail-closed: a missing required
            param is refused NAMING the param, an unknown param is
            refused (typo-proof, the CODES-registry pattern), a kind
            outside the closed space has no spec and is refused;
  SLOTS     spawn_candidate's slots is the orchestrator's EXPLICIT
            dispatch width: int 1..5, no default — 0 and 6 refuse,
            1 and 5 land;
  DEFAULTS  an optional param absent is recorded AT ITS DEFAULT in the
            row (auditability: the row shows effective values, never a
            silent absence); normalization never mutates the input;
  LOOP      end-to-end through the real loop: the spawn row records
            the loop's spawn_slots choice, the assign row records the
            effective method_family/tier, the terminal rows record
            rule/delta_p.

Mock worker only; deterministic seeds; no wall clock in any assertion.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop",
           ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop as loop913  # noqa: E402
from rlvr import action_params  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
from rlvr import q_cells  # noqa: E402
from core import ActionKind  # noqa: E402
import core.actions  # noqa: E402 — the action/1 boundary re-export

ActionParamError = action_params.ActionParamError
SPECS = action_params.ACTION_PARAM_SPECS


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """The suite's default seal posture (the 903/887/909 posture)."""
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


# ------------------------------------------------------------ the spec

def test_spec_covers_all_ten_kinds():
    # the DRIFT pin (both directions): the table's string keys must be
    # EXACTLY the closed vocabulary's canonical values — a kind added
    # to the enum without a spec refuses at the wall ("no param spec");
    # a spec key outside the enum refuses through ActionKind
    assert frozenset(SPECS) == frozenset(k.value for k in ActionKind)


def test_spec_table_is_frozen():
    with pytest.raises(TypeError):
        SPECS["probe"] = action_params.EMPTY_SPEC  # type: ignore
    entry = SPECS["assign_step"]
    with pytest.raises(TypeError):
        entry.required["method_family"] = None  # type: ignore
    with pytest.raises(TypeError):
        entry.optional["tier"] = (9, None)  # type: ignore


def test_slots_bounds_constants():
    assert action_params.SLOTS_MIN == 1
    assert action_params.SLOTS_MAX == 5


# ------------------------------------------------- the fail-closed wall

def test_missing_required_param_refused_and_named():
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params("assign_step", {})
    assert "method_family" in str(exc.value)
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params("spawn_candidate", {})
    assert "slots" in str(exc.value)


def test_unknown_param_refused_and_named():
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params(
            "assign_step", {"method_family": "m", "tierx": 1})
    assert "tierx" in str(exc.value)
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params("select_task", {"k": 5})
    assert "k" in str(exc.value)


def test_kind_outside_the_closed_space_has_no_spec():
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params("teleport", {})
    assert "teleport" in str(exc.value)


def test_validator_failure_named():
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params(
            "spawn_candidate", {"slots": True})
    assert "slots" in str(exc.value)


def test_params_must_be_a_mapping():
    with pytest.raises(ActionParamError):
        action_params.normalize_params("select_task", ["not", "a", "map"])


# ----------------------------------------------- the append/parse walls

def test_append_action_wall_refuses_spec_violations(tmp_path):
    ws = tmp_path / "ws"
    with pytest.raises(ValueError) as exc:
        q_cells.append_action(ws, kind="spawn_candidate",
                              rollout_id="ro-1", target="w-1",
                              params={}, ts="t0")
    assert "slots" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        q_cells.append_action(ws, kind="assign_step", rollout_id="ro-1",
                              target="f", params={"method_family": "m",
                                                  "tier": 1, "oops": 2},
                              ts="t0")
    assert "oops" in str(exc.value)
    assert q_cells.trajectory_rows(ws) == []


def test_append_action_wall_refuses_kind_outside_the_space(tmp_path):
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        q_cells.append_action(ws, kind="teleport", rollout_id="ro-1",
                              target="x", params={}, ts="t0")
    assert q_cells.trajectory_rows(ws) == []


def test_parse_action_wall_enforces_the_spec():
    from core import parse_action
    doc = {"schema": "action/1", "kind": "spawn_candidate",
           "target": "w-1", "params": {},
           "budget": {"wall_s": 1.0, "max_calls": None},
           "context": {"rollout_id": "ro-1", "step_id": None,
                       "policy_version": "v2"}}
    with pytest.raises(ValueError) as exc:
        parse_action(doc)
    assert "slots" in str(exc.value)
    doc["params"] = {"slots": 2, "unexpected": 1}
    with pytest.raises(ValueError) as exc:
        parse_action(doc)
    assert "unexpected" in str(exc.value)


# ------------------------------------------------- the slots boundary

@pytest.mark.parametrize("slots", [0, -1, 6, True, "3", 3.0, None])
def test_slots_out_of_range_refused(slots):
    with pytest.raises(ActionParamError):
        action_params.normalize_params("spawn_candidate",
                                       {"slots": slots})


@pytest.mark.parametrize("slots", [1, 5])
def test_slots_boundary_accepted_and_landed(tmp_path, slots):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="spawn_candidate", rollout_id="ro-1",
                          target="w-1", params={"slots": slots}, ts="t0")
    (row,) = q_cells.trajectory_rows(ws)
    assert row["params"]["slots"] == slots


# -------------------------------------- explicit defaults in the row

def test_optional_absent_records_the_default_in_the_row(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-1",
                          step_id="s-1", target="fam",
                          params={"method_family": "m"}, ts="t0")
    (row,) = q_cells.trajectory_rows(ws)
    assert row["params"] == {"method_family": "m", "tier": 1,
                             "phase": "", "intent": None,
                             "distribution": None}


def test_distribution_rides_select_and_assign(tmp_path):
    """#925 reconciliation: the decision-time ranking distribution is
    optional-at-None on both kinds — present when the loop persists it,
    explicitly None otherwise (never a silent absence)."""
    ws = tmp_path / "ws"
    dist = {"static-scan": {"alpha": 3, "beta": 1}}
    q_cells.append_action(ws, kind="select_task", rollout_id="ro-1",
                          step_id="s-1", target="t-1",
                          params={"distribution": dist}, ts="t0")
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-1",
                          step_id="s-2", target="fam",
                          params={"method_family": "static-scan",
                                  "distribution": dist}, ts="t1")
    q_cells.append_action(ws, kind="select_task", rollout_id="ro-2",
                          step_id="s-3", target="t-2", ts="t2")
    rows = q_cells.trajectory_rows(ws)
    assert rows[0]["params"]["distribution"] == dist
    assert rows[1]["params"]["distribution"] == dist
    assert rows[2]["params"] == {"distribution": None}


def test_spawn_row_records_effective_params(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="spawn_candidate", rollout_id="ro-1",
                          target="w-1", params={"slots": 2}, ts="t0")
    (row,) = q_cells.trajectory_rows(ws)
    assert row["params"] == {"slots": 2, "spawn_id": None, "goal": "",
                             "snapshot_excerpt": None, "cards": None,
                             "phase": ""}


def test_terminate_rows_record_effective_rule_and_delta(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="terminate_rollout", rollout_id="ro-1",
                          target="task", params={"rule": "loss_cut"},
                          ts="t0")
    (row,) = q_cells.trajectory_rows(ws)
    assert row["params"] == {"rule": "loss_cut", "delta_p": None}


def test_normalize_never_mutates_the_input():
    params = {"method_family": "m"}
    action_params.normalize_params("assign_step", params)
    assert params == {"method_family": "m"}


def test_validators_pass_through_normalized_values():
    out = action_params.normalize_params(
        "assign_step", {"method_family": " m ", "tier": 3,
                        "phase": "triage", "intent": {"k": "v"}})
    assert out["tier"] == 3
    assert out["phase"] == "triage"
    assert out["intent"] == {"k": "v"}


# ------------------------------------------- the core.actions re-export

def test_core_actions_reexports_the_single_source():
    assert core.actions.ACTION_PARAM_SPECS is SPECS
    assert core.actions.ActionParamError is ActionParamError


# ------------------------------------------------------- the loop e2e

def _rows_of(ws, kind: str) -> list[dict]:
    return [r for r in q_cells.trajectory_rows(ws)
            if r.get("schema") == q_cells.SCHEMA_ACTION_V2
            and r.get("kind") == kind]


def test_loop_records_effective_params_including_slots(tmp_path):
    ws = tmp_path / "ws"
    run, ws2 = loop913.run_loop(ws, laps=1, seed=7, spawn_slots=3)
    assert ws2 == ws
    spawn_rows = _rows_of(ws, "spawn_candidate")
    assert spawn_rows, "the loop landed no spawn row"
    for row in spawn_rows:
        assert row["params"]["slots"] == 3
    assign_rows = _rows_of(ws, "assign_step")
    assert assign_rows
    for row in assign_rows:
        assert isinstance(row["params"]["method_family"], str)
        assert row["params"]["method_family"]
        assert row["params"]["tier"] == 1
        assert "phase" in row["params"]
    terminal = [r for r in _rows_of(ws, "terminate_rollout")
                + _rows_of(ws, "rollback")]
    assert terminal
    for row in terminal:
        assert "rule" in row["params"] and "delta_p" in row["params"]


def test_loop_run_is_rejected_without_explicit_slots_type(tmp_path):
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        loop913.run_loop(ws, laps=1, seed=7, spawn_slots=6)


# ------------------------------------------------ the spawner write face

def test_record_spawn_carries_explicit_slots(tmp_path):
    from workers import spawner
    from core import Budget
    ws = tmp_path / "ws"
    receipt = spawner.prepare_spawn(
        "recover the key", {"task": "t"}, (), Budget(wall_s=600.0),
        worker_id="w-924")
    spawner.record_spawn(ws, receipt, rollout_id="ro-1", slots=2,
                         policy_version="v2")
    (row,) = [r for r in q_cells.trajectory_rows(ws)
              if r.get("schema") == q_cells.SCHEMA_ACTION_V2]
    assert row["kind"] == "spawn_candidate"
    assert row["params"]["slots"] == 2
    assert row["params"]["spawn_id"] == receipt["spawn_id"]
    with pytest.raises(TypeError):
        spawner.record_spawn(ws, receipt, rollout_id="ro-2",
                             policy_version="v2")
