# -*- coding: utf-8 -*-
"""tests/test_pool_scheduler.py — the two-level scheduler (issue 863, P5).

Every pin asserts observable behavior (output values / ordering), never
call shapes:

  info bonus    a new family's FIRST task wins the argmax over an
                old-family task with a higher direct value; the second
                in-family task carries exactly zero bonus (decay^n with
                the documented decay constant);
  expected cost the memory face showing a mastered family method drops
                the expected cost (value auto-rises for the same task);
  hysteresis    a challenger within delta does NOT displace the head
                (== delta included), beyond delta it does; no head ->
                plain argmax;
  select_batch  slot cap fills in one round; a task whose unmet deps are
                non-empty is skipped (a dependency is never inverted);
                max ONE in-flight per scarce tool (batch-internal and
                pre-loaded alike); a T3 in the batch blocks further T3
                but never T1;
  reprice       post-settlement re-pricing covers the affected subtree
                (same family) only — never a global reshuffle;
  retire        the three outlets (learned / recall-covered /
                premise-expired) each name their reason, a clean task
                stays (None), learned wins the precedence race;
  inflow        a failure row derives its follow-up analysis task;
  wiring        _select_task_dirs is pool-ordered when the pool's
                derived view has data, byte-identical when it has none.
"""
from __future__ import annotations

import pytest

import eval_loop_runner as lr
import rlvr.pool_indexer as pool_indexer
import rlvr.pool_scheduler as ps


# ------------------------------------------------------------ task builders

def _task(tid, family, direct=0.0, base_cost=0.0, tools=(), tier=1,
          deps=(), premises=()):
    return {"task_id": tid, "family": family, "direct_value": direct,
            "base_cost": base_cost, "tools": list(tools), "tier": tier,
            "deps": list(deps), "premises": list(premises)}


def _state(tasks=(), head=None, memory=None, family_counts=None,
           recall_covered=(), stale_premises=()):
    return {"tasks": list(tasks), "head": head, "memory": dict(memory or {}),
            "family_counts": dict(family_counts or {}),
            "recall_covered": list(recall_covered),
            "stale_premises": list(stale_premises)}


# ------------------------------------------------------------- info bonus

def test_info_bonus_first_of_family_wins_argmax():
    # the new family's first task carries the calibration bonus and beats
    # an old-family task with a strictly higher direct value
    old = _task("old", "fam-old", direct=1.4)
    new = _task("new", "fam-new", direct=0.5)
    state = _state(tasks=[old, new], family_counts={"fam-old": 3})
    assert ps.task_value(new, state) > ps.task_value(old, state)
    assert ps.pick_next(state, delta=0.0)["task_id"] == "new"


def test_info_bonus_second_of_family_is_exactly_zero():
    t = _task("t", "fam-x", direct=1.0)
    fresh = _state(tasks=[t], family_counts={})
    second = _state(tasks=[t], family_counts={"fam-x": 1})
    # decay^n: the first-of-family keeps the full bonus, the repeat keeps
    # exactly none of it
    assert ps.task_value(t, fresh) - ps.task_value(t, second) \
        == pytest.approx(ps.INFO_BONUS)
    assert ps.INFO_DECAY ** 1 == 0.0


def test_mastered_family_drops_expected_cost():
    t = _task("t", "fam-x", direct=1.0, base_cost=1.0)
    plain = _state(tasks=[t])
    mastered = _state(tasks=[t], memory={"fam-x": {"mastered": True}})
    # same task, same direct value: the learned method makes it worth MORE
    assert ps.task_value(t, mastered) > ps.task_value(t, plain)
    assert ps.task_value(t, mastered) - ps.task_value(t, plain) \
        == pytest.approx(t["base_cost"] * (1.0 - ps.MASTERY_COST_FACTOR))


# -------------------------------------------------------------- hysteresis

def _two_task_state(head_v, ch_v):
    head = _task("head", "fam-a", direct=head_v)
    ch = _task("chall", "fam-b", direct=ch_v)
    # both families already calibrated once -> the bonus is zero for both,
    # so V == direct_value and the arithmetic below stays exact
    return _state(tasks=[head, ch], head="head",
                  family_counts={"fam-a": 1, "fam-b": 1})


def test_hysteresis_within_delta_keeps_incumbent():
    assert ps.pick_next(_two_task_state(1.0, 1.05), delta=0.2)["task_id"] \
        == "head"


def test_hysteresis_at_exactly_delta_keeps_incumbent():
    # a challenger must beat the head by MORE than delta
    assert ps.pick_next(_two_task_state(1.0, 1.2), delta=0.2)["task_id"] \
        == "head"


def test_hysteresis_beyond_delta_displaces():
    assert ps.pick_next(_two_task_state(1.0, 1.5), delta=0.2)["task_id"] \
        == "chall"


def test_no_head_is_plain_argmax():
    a = _task("a", "fam-a", direct=0.3)
    b = _task("b", "fam-b", direct=2.0)
    state = _state(tasks=[a, b], head=None,
                   family_counts={"fam-a": 1, "fam-b": 1})
    assert ps.pick_next(state, delta=0.5)["task_id"] == "b"


def test_pick_next_empty_pool_is_none():
    assert ps.pick_next(_state(), delta=0.0) is None


# ------------------------------------------------------------ select_batch

def test_select_batch_fills_slots_in_one_round():
    ranked = [_task(f"t{i}", f"f{i}") for i in range(3)]
    batch = ps.select_batch(ranked, 2, deps={}, tiers={f"t{i}": 1
                                                       for i in range(3)},
                            tool_load={})
    assert [t["task_id"] for t in batch] == ["t0", "t1"]


def test_select_batch_never_inverts_a_dependency():
    a = _task("a", "fam-a")
    b = _task("b", "fam-b", deps=["a"])
    tiers = {"a": 1, "b": 1}
    # b ranks first but its dep is unmet -> skipped, a goes alone
    batch = ps.select_batch([b, a], 2, deps={"b": ["a"]}, tiers=tiers,
                            tool_load={})
    assert [t["task_id"] for t in batch] == ["a"]


def test_select_batch_no_two_inflight_on_same_tool():
    t1 = _task("t1", "fam-a", tools=["vm"])
    t2 = _task("t2", "fam-b", tools=["vm"])
    tiers = {"t1": 1, "t2": 1}
    batch = ps.select_batch([t1, t2], 2, deps={}, tiers=tiers,
                            tool_load={})
    assert [t["task_id"] for t in batch] == ["t1"]  # the second waits
    # the tool already in-flight from a previous round: nobody new gets it
    batch = ps.select_batch([t1, t2], 2, deps={}, tiers=tiers,
                            tool_load={"vm": 1})
    assert batch == []


def test_select_batch_t3_serial_t1_parallel():
    ranked = [_task("t3a", "fa", tier=3), _task("t1a", "fb", tier=1),
              _task("t3b", "fc", tier=3), _task("t1b", "fd", tier=1)]
    tiers = {"t3a": 3, "t1a": 1, "t3b": 3, "t1b": 1}
    batch = ps.select_batch(ranked, 4, deps={}, tiers=tiers, tool_load={})
    assert [t["task_id"] for t in batch] == ["t3a", "t1a", "t1b"]


# ---------------------------------------------------------------- reprice

def test_reprice_scope_is_subtree_only():
    settled = _task("s", "fam-x")
    same1 = _task("p1", "fam-x")
    same2 = _task("p2", "fam-x")
    other = _task("q", "fam-y")
    scope = ps.reprice_scope(settled, _state(tasks=[same1, other, same2,
                                                    settled]))
    assert [t["task_id"] for t in scope] == ["p1", "p2"]


# ------------------------------------------------------------ retire faces

def test_retire_learned():
    t = _task("t", "fam-x")
    state = _state(tasks=[t], memory={"fam-x": {"mastered": True}})
    assert ps.retire_reasons(t, state) == "learned"


def test_retire_recall_covered():
    t = _task("t", "fam-x")
    state = _state(tasks=[t], recall_covered=["t"])
    assert ps.retire_reasons(t, state) == "recall-covered"


def test_retire_premise_expired():
    t = _task("t", "fam-x", premises=["premise-7"])
    state = _state(tasks=[t], stale_premises=["premise-7"])
    assert ps.retire_reasons(t, state) == "premise-expired"


def test_retire_clean_task_stays():
    t = _task("t", "fam-x", premises=["premise-7"])
    state = _state(tasks=[t], recall_covered=["other"],
                   stale_premises=["premise-8"])
    assert ps.retire_reasons(t, state) is None


def test_retire_learned_wins_precedence():
    t = _task("t", "fam-x")
    state = _state(tasks=[t], memory={"fam-x": {"mastered": True}},
                   recall_covered=["t"], stale_premises=["p"])
    assert ps.retire_reasons(t, state) == "learned"


# ------------------------------------------------------------------ inflow

def test_inflow_from_failure_derives_followup():
    row = {"claim": "c-9", "family": "fam-x",
           "attribution": "wrong tool path", "direct_value": 0.4}
    derived = ps.inflow_from_failure(row)
    assert derived["family"] == "fam-x"
    assert "c-9" in derived["task_id"]
    assert derived["origin"] == "failure-analysis"
    assert derived["direct_value"] == pytest.approx(0.4)
    assert derived["tier"] >= 1


def test_inflow_defaults_direct_value():
    derived = ps.inflow_from_failure({"claim": "c-1", "family": "f",
                                      "attribution": "attr"})
    assert derived["direct_value"] == pytest.approx(
        ps.FAILURE_ANALYSIS_VALUE)


# ------------------------------------------------------------------ wiring

def _wiring_dirs(tmp_path):
    dirs = []
    for name in ("unit-alpha", "unit-beta", "unit-gamma"):
        d = tmp_path / name
        d.mkdir()
        (d / "task.yaml").write_text("id: x\n", encoding="utf-8")
        dirs.append(d)
    return dirs


def test_wiring_pool_ordered_when_pool_has_data(tmp_path, monkeypatch):
    dirs = _wiring_dirs(tmp_path)
    table = {(("unit-gamma",), "commit"):
             {"n": 1, "mean_reward": 2.0, "mean_cost": 0.0}}
    monkeypatch.setattr(pool_indexer, "value_table", lambda ws: table)
    ordered = lr._select_task_dirs([str(d) for d in dirs], tier="smoke")
    assert ordered == [dirs[2], dirs[0], dirs[1]]


def test_wiring_default_order_without_pool_data(tmp_path, monkeypatch):
    dirs = _wiring_dirs(tmp_path)
    monkeypatch.setattr(pool_indexer, "value_table", lambda ws: {})
    ordered = lr._select_task_dirs([str(d) for d in dirs], tier="smoke")
    assert ordered == dirs
