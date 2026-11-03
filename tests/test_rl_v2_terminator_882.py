# -*- coding: utf-8 -*-
"""tests/test_rl_v2_terminator_882.py — the β termination policy (issue 882).

RED-first pins for the dynamic step-count face that replaces fixed N:

  1. rule 1 (question-covered): the scope-verifier's coverage input
     saying the claim's question is answered terminates the rollout
     with the efficiency-credit flag (a POSITIVE signal, never a
     failure) and precedence over the loss-cut;
  2. rule 2 (loss-cut): N consecutive unverified result rows of THIS
     rollout fire; N-1 does not (the boundary); a trailing verified
     row resets the streak and another rollout's rows never leak in;
  3. the watchdog: one-shot per-rollout deadline = family prior ×
     per-dispatch budget × slack — two families with different
     histories get different deadlines; a cold family gets the
     documented default prior (never zero); a rollout completing
     before the deadline early-cancels it (never fires);
  4. receipt schema stamps, determinism (same inputs → same receipt,
     seed derived from ledger state + round, never wall clock), and
     the fail-closed reject pins for structural garbage.
"""
from __future__ import annotations

import dataclasses
import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core import Budget  # noqa: E402
from policy import terminator  # noqa: E402
from rlvr import q_cells  # noqa: E402

CONTRACT_INIT = '''# -*- coding: utf-8 -*-
"""learning-loop ``policy`` — the rl-v2 policy faces (#880-#882).

One module per decision kind family; each face consumes the core
value objects and the q_cells v2 ledger, samples (never argmax), and
stays pure: (state, store, rng) -> receipt, side-effect-free.
"""
'''


def _sig() -> str:
    return "a" * 12


def _coverage(**over):
    doc = {"covered": False, "question": "recover the key schedule"}
    doc.update(over)
    return doc


def _results(ws, rollout_id, verifieds, start=0):
    """Append one result row per flag (append order = trajectory order)."""
    for i, verified in enumerate(verifieds, start=start):
        q_cells.append_result(ws, rollout_id=rollout_id,
                              step_id=f"s-{i}", verified=verified,
                              cost=0.1, verdict="pass" if verified else "fail")
    return q_cells.trajectory_rows(ws)


def _dispatches(ws, family, claim, n, start=0):
    for i in range(start, start + n):
        q_cells.append_observation(ws, _sig(), family, None,
                                   source="dispatch", claim=claim,
                                   dispatch_id=f"d-{i}")


# ------------------------------------------------------------ package face

def test_policy_package_docstring_contract():
    import policy
    assert policy.__doc__ == CONTRACT_INIT.split('"""')[1]


# ------------------------------------------------- rule 1 question-covered

def test_question_covered_terminates_with_efficiency_credit(tmp_path):
    ws = tmp_path / "ws"
    rows = _results(ws, "ro-1", [False])
    rec = terminator.check_termination("ro-1", _coverage(covered=True),
                                       rows)
    assert rec["schema"] == "terminator-check/1"
    assert rec["terminate"] is True
    assert rec["rule"] == "question_covered"
    assert rec["action_kind"] == "terminate_rollout"
    assert rec["efficiency_credit"] is True
    assert rec["rollout_id"] == "ro-1"
    assert rec["question"] == "recover the key schedule"


def test_question_covered_precedes_loss_cut(tmp_path):
    ws = tmp_path / "ws"
    rows = _results(ws, "ro-1", [True, False, False, False])
    rec = terminator.check_termination(
        "ro-1", _coverage(covered=True), rows, loss_cut_n=3)
    assert rec["rule"] == "question_covered"
    assert rec["efficiency_credit"] is True


def test_continue_receipt_when_no_rule_fires(tmp_path):
    ws = tmp_path / "ws"
    rows = _results(ws, "ro-1", [True])
    rec = terminator.check_termination("ro-1", _coverage(), rows)
    assert rec["terminate"] is False
    assert rec["rule"] is None
    assert rec["action_kind"] is None
    assert rec["efficiency_credit"] is False


# ---------------------------------------------------------- rule 2 loss-cut

def test_loss_cut_fires_at_n_and_not_at_n_minus_1(tmp_path):
    ws = tmp_path / "ws"
    rows = _results(ws, "ro-1", [True, False, False])
    rec = terminator.check_termination("ro-1", _coverage(), rows,
                                       loss_cut_n=3)
    assert rec["terminate"] is False              # the N-1 boundary
    assert rec["consecutive_unverified"] == 2
    rows = _results(ws, "ro-1", [False], start=3)
    rec = terminator.check_termination("ro-1", _coverage(), rows,
                                       loss_cut_n=3)
    assert rec["terminate"] is True
    assert rec["rule"] == "loss_cut"
    assert rec["action_kind"] == "terminate_rollout"
    assert rec["efficiency_credit"] is False      # never a credit here
    assert rec["consecutive_unverified"] == 3


def test_loss_cut_counts_only_this_rollout_and_resets_on_verified(tmp_path):
    ws = tmp_path / "ws"
    _results(ws, "ro-other", [False, False, False])
    rows = _results(ws, "ro-1", [True, False, False])
    rec = terminator.check_termination("ro-1", _coverage(), rows,
                                       loss_cut_n=3)
    assert rec["terminate"] is False   # other rollout's streak never leaks
    rows = _results(ws, "ro-1", [True, False, False], start=3)
    rec = terminator.check_termination("ro-1", _coverage(), rows,
                                       loss_cut_n=3)
    assert rec["terminate"] is False   # the mid-trajectory verified reset
    assert rec["consecutive_unverified"] == 2


# --------------------------------------------------------- family priors

def test_family_dispatch_priors_from_real_ledger_rows(tmp_path):
    ws = tmp_path / "ws"
    _dispatches(ws, "fam-a", "C-1", 2)
    _dispatches(ws, "fam-a", "C-2", 4, start=10)
    _dispatches(ws, "fam-b", "C-3", 1, start=20)
    # settlement rows and family-less dispatch rows are honest gaps
    q_cells.append_observation(ws, _sig(), "fam-a", 0.5,
                               source="settlement")
    q_cells.append_observation(ws, _sig(), "", None, source="dispatch",
                               claim="C-9")
    priors = terminator.family_dispatch_priors(q_cells.trajectory_rows(ws))
    assert priors["fam-a"] == pytest.approx(3.0)   # mean(2, 4)
    assert priors["fam-b"] == pytest.approx(1.0)
    assert "fam-c" not in priors                   # cold = absent, not 0


def test_family_priors_count_assign_step_action_rows(tmp_path):
    from rlvr import consolidated_ledger as cl
    from rlvr import learning_seal as seal
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-a",
                          step_id="s-1", target="step-1",
                          params={"method_family": "mod-crypto"})
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-a",
                          step_id="s-2", target="step-2",
                          params={"method_family": "mod-crypto"})
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-b",
                          step_id="s-1", target="step-1",
                          params={"method_family": "arm-kdf"})
    # a PRE-issue-924 ledger row (params-free assign_step) — the wall no
    # longer WRITES one, but the read face must still tolerate the
    # old-shape row: family-less, counted nowhere, never a bucket
    pre924 = seal.sign_row({
        "schema": q_cells.SCHEMA_ACTION_V2,
        "ts": "2026-01-01T00:00:00Z",
        "kind": "assign_step", "rollout_id": "ro-c",
        "step_id": "s-1", "target": "step-1", "params": {}})
    cl.append(ws, "experience", pre924)
    priors = terminator.family_dispatch_priors(q_cells.trajectory_rows(ws))
    assert priors["mod-crypto"] == pytest.approx(2.0)
    assert priors["arm-kdf"] == pytest.approx(1.0)
    assert "ro-c" not in priors        # a family-less action row: no bucket


# --------------------------------------------------------------- watchdog

def test_watchdog_deadline_is_prior_times_budget_times_slack(tmp_path):
    ws = tmp_path / "ws"
    _dispatches(ws, "fam-a", "C-1", 2)
    _dispatches(ws, "fam-a", "C-2", 4, start=10)
    _dispatches(ws, "fam-b", "C-3", 1, start=20)
    rows = q_cells.trajectory_rows(ws)
    budget = Budget(wall_s=600.0)
    a = terminator.watchdog_deadline("fam-a", rows, budget)
    b = terminator.watchdog_deadline("fam-b", rows, budget)
    assert a["schema"] == "watchdog-deadline/1"
    assert a["prior"] == pytest.approx(3.0)
    assert a["deadline_s"] == pytest.approx(3.0 * 600.0 * 2.0)
    assert b["deadline_s"] == pytest.approx(1.0 * 600.0 * 2.0)
    assert a["deadline_s"] > b["deadline_s"]       # the histories adapt it
    assert a["one_shot"] is True
    assert a["early_cancel_on_complete"] is True
    assert a["cold"] is False and b["cold"] is False
    assert a["history_rollouts"] == 2


def test_cold_family_gets_the_documented_default_prior(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="select_task", rollout_id="ro-1",
                          target="C-1")
    rows = q_cells.trajectory_rows(ws)
    rec = terminator.watchdog_deadline("fam-cold", rows,
                                       Budget(wall_s=100.0), slack=1.5)
    assert rec["cold"] is True
    assert rec["prior"] == pytest.approx(terminator.COLD_FAMILY_PRIOR)
    assert rec["prior"] > 0                        # never zero
    assert rec["deadline_s"] == pytest.approx(
        terminator.COLD_FAMILY_PRIOR * 100.0 * 1.5)


def test_watchdog_check_fires_at_deadline_and_early_cancels(tmp_path):
    deadline = {"schema": terminator.WATCHDOG_SCHEMA, "family": "fam-a",
                "deadline_s": 3600.0}
    fired = terminator.watchdog_check(deadline, elapsed_s=3600.0,
                                      rollout_completed=False)
    assert fired["schema"] == "watchdog-check/1"
    assert fired["fired"] is True
    assert fired["early_cancel"] is False
    within = terminator.watchdog_check(deadline, elapsed_s=3599.0,
                                       rollout_completed=False)
    assert within["fired"] is False
    early = terminator.watchdog_check(deadline, elapsed_s=3599.0,
                                      rollout_completed=True)
    assert early["efficiency_credit"] is True  # done UNDER the line
    assert early["reason"] == "rollout_completed_early"
    late = terminator.watchdog_check(deadline, elapsed_s=99_999.0,
                                     rollout_completed=True)
    assert late["fired"] is False
    assert late["early_cancel"] is True
    assert late["efficiency_credit"] is False  # slow earns NOTHING
    assert late["reason"] == "rollout_completed_late"


# ------------------------------------------------ determinism and the seed

def test_determinism_same_inputs_same_receipt(tmp_path):
    ws = tmp_path / "ws"
    _dispatches(ws, "fam-a", "C-1", 2)
    rows = _results(ws, "ro-1", [True, False, False])
    kw = {"loss_cut_n": 3}
    assert (terminator.check_termination("ro-1", _coverage(), rows, **kw)
            == terminator.check_termination("ro-1", _coverage(), rows, **kw))
    budget = Budget(wall_s=600.0)
    assert (terminator.watchdog_deadline("fam-a", rows, budget)
            == terminator.watchdog_deadline("fam-a", rows, budget))
    rng = random.Random(7)
    assert (terminator.check_termination("ro-1", _coverage(), rows, rng=rng,
                                         **kw)
            == terminator.check_termination("ro-1", _coverage(), rows,
                                            **kw))


def test_seed_is_ledger_and_round_derived_never_wall_clock(tmp_path):
    ws = tmp_path / "ws"
    rows = _results(ws, "ro-1", [False])
    s1 = terminator.terminator_seed(rows, "ro-1")
    s2 = terminator.terminator_seed(rows, "ro-1")
    assert s1 == s2
    assert terminator.terminator_seed(rows, "ro-1", round_no=1) != s1
    assert terminator.terminator_seed(rows, "ro-2") != s1
    ws2 = tmp_path / "ws2"
    rows2 = _results(ws2, "ro-1", [True])          # evidence moved
    assert terminator.terminator_seed(rows2, "ro-1") != s1


# -------------------------------------------------------- fail-closed wall

@pytest.mark.parametrize("coverage", [
    "covered",
    None,
    {},
    {"covered": "yes"},
    {"covered": 1},
    {"covered": None},
])
def test_check_rejects_garbage_coverage(tmp_path, coverage):
    ws = tmp_path / "ws"
    rows = _results(ws, "ro-1", [True])
    with pytest.raises(ValueError):
        terminator.check_termination("ro-1", coverage, rows)


@pytest.mark.parametrize("kwargs", [
    {"rollout_id": ""},
    {"rollout_id": "  "},
    {"loss_cut_n": 0},
    {"loss_cut_n": -1},
    {"loss_cut_n": True},
    {"loss_cut_n": "3"},
])
def test_check_rejects_garbage_scalars(tmp_path, kwargs):
    ws = tmp_path / "ws"
    rows = _results(ws, "ro-1", [True])
    call = dict(kwargs)
    rid = call.pop("rollout_id", "ro-1")
    with pytest.raises(ValueError):
        terminator.check_termination(rid, _coverage(), rows, **call)


@pytest.mark.parametrize("rows", [
    None,
    "rows",
    [42],
    [None],
    [{"schema": "unrelated/9"}],
    [{"schema": "q-cell-result/1", "rollout_id": "ro-1",
      "step_id": "s-1", "verified": "yes"}],
])
def test_check_rejects_garbage_rows(rows):
    with pytest.raises(ValueError):
        terminator.check_termination("ro-1", _coverage(), rows)


@pytest.mark.parametrize("kwargs", [
    {"family": ""},
    {"family": "  "},
    {"budget": None},
    {"budget": {"wall_s": 600.0}},
    {"budget": Budget(wall_s=-1.0)},
    {"budget": Budget(wall_s=float("nan"))},
    {"budget": Budget(wall_s=float("inf"))},
    {"slack": 0.0},
    {"slack": -2.0},
    {"slack": float("inf")},
    {"slack": True},
    {"round_no": True},
    {"round_no": -1},
])
def test_watchdog_deadline_reject_pins(kwargs):
    ws_rows: list = []
    call = dict(kwargs)
    family = call.pop("family", "fam-a")
    budget = call.pop("budget", Budget(wall_s=600.0))
    with pytest.raises(ValueError):
        terminator.watchdog_deadline(family, ws_rows, budget, **call)


@pytest.mark.parametrize("kwargs", [
    {"deadline": {"schema": "watchdog-deadline/2", "deadline_s": 1.0}},
    {"deadline": {"deadline_s": 1.0}},
    {"deadline": "deadline"},
    {"deadline": {"schema": terminator.WATCHDOG_SCHEMA,
                  "deadline_s": float("nan")}},
    {"elapsed_s": -1.0},
    {"elapsed_s": float("nan")},
    {"elapsed_s": "soon"},
    {"rollout_completed": "yes"},
])
def test_watchdog_check_reject_pins(kwargs):
    call = dict(kwargs)
    deadline = call.pop("deadline", {"schema": terminator.WATCHDOG_SCHEMA,
                                     "deadline_s": 1.0})
    call.setdefault("elapsed_s", 0.0)
    call.setdefault("rollout_completed", False)
    with pytest.raises(ValueError):
        terminator.watchdog_check(deadline, **call)


@pytest.mark.parametrize("rows", [
    None,
    [42],
    [{"schema": "mystery/1"}],
    [{"schema": None}],
])
def test_priors_reject_pins(rows):
    with pytest.raises(ValueError):
        terminator.family_dispatch_priors(rows)


def test_seed_reject_pins():
    with pytest.raises(ValueError):
        terminator.terminator_seed(42, "ro-1")
    with pytest.raises(ValueError):
        terminator.terminator_seed([], "")
    with pytest.raises(ValueError):
        terminator.terminator_seed([{"schema": "x/1"}], "ro-1", round_no=-1)


def test_budget_value_object_stays_frozen():
    b = Budget(wall_s=600.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.wall_s = 1.0
    assert math.isfinite(b.wall_s)
