# -*- coding: utf-8 -*-
"""tests/test_learning_loop_harness.py — the DECLARATION GATE (card P7
of the learning-loop live-wire program).

A closed-loop mock harness over synthetic fixture workspaces (no real
sessions): the simulator in rlvr/loop_sim drives the REAL faces —
step/1 records (validate_step), rolling step settlement (step_reward),
the deviation window (segment_view), the timeout triage
(classify_timeout), terminal settlement (settle_mission), the derived
value table (pool_indexer.value_table), and the two-level scheduler
(task_value / pick_next / reprice_scope / retire_reasons /
inflow_from_failure / order_task_dirs) — across three laps:

    lap 1  cold start, mixed families, one planted wrong-tool failure
    lap 2  the failed family retried on the corrected path (the learned
           leg, riding the recall sensor) + an oversized task whose
           window times out (granularity fault)
    lap 3  mastery consolidation (in-family repeat: info bonus 0, cost
           discounted, retirement candidates) + new-family inflow

The eight assertions (each one test) plus the owner's learning-argument
summary: the lap-over-lap delta table proves the learning is
attributable to the pool's memory face — the ablation arm (same
history, memory faces absent at the scheduler boundary) is flat.
"""
from __future__ import annotations

import pytest

import rlvr.pool_scheduler as ps
from rlvr import loop_sim
from rlvr import timeout_triage as tt

DELTA = loop_sim.DELTA
BASE_A = loop_sim.FAM_A_BASE_COST
INPUT_ORDER = list(loop_sim.FAMILIES)


def _run(tmp_path, name="ws", *, ablated=False):
    ws = tmp_path / name
    ws.mkdir()
    report = loop_sim.run_learning_loop(ws, delta=DELTA,
                                        ablate_pool_memory=ablated)
    return report, ws


def _state_from(report, tasks):
    final = report["final"]
    return {"tasks": list(tasks), "head": None,
            "memory": final["memory"],
            "family_counts": final["counts"],
            "value_table": final["value_table"],
            "recall_covered": [], "stale_premises": []}


def _task(tid, family, direct, base_cost):
    return {"task_id": tid, "family": family, "direct_value": direct,
            "base_cost": base_cost, "tools": [], "tier": 1, "deps": [],
            "premises": []}


def _expected(report, family, base_cost):
    """The scheduler's memory-derived expected cost for a neutral probe
    of ``family`` against the run's final refreshed table (the probe's
    info bonus is dead: every sim family has settled >= 1 episode)."""
    probe = _task("probe-" + family, family, 0.0, base_cost)
    return -ps.task_value(probe, _state_from(report, [probe]))


# ------------------------------------------------ assertion 1: tool learning

def test_tool_learning_expected_cost_declines_across_laps(tmp_path):
    """TOOL LEARNING: fam-a's memory-derived expected cost declines
    strictly across the three laps — the empirical value-table cost
    engages at lap 2 and the mastered-method discount compounds it."""
    report, _ws = _run(tmp_path)
    trace = report["expected_cost_trace"]
    assert len(trace) == 3
    assert trace[0] > trace[1] > trace[2], trace
    # cold start pays the base estimate; lap 2 pays the single C-A1
    # cell under the mastery discount; lap 3 adds the cheaper C-A2
    # cell (each mission folds its cumulative raw ledger rows — identity
    # + settlement amendment — so the cells weight later missions)
    assert trace[0] == pytest.approx(BASE_A)
    assert trace[1] == pytest.approx(BASE_A * ps.MASTERY_COST_FACTOR)
    assert trace[2] == pytest.approx(
        (2 * BASE_A + 6 * 0.4) / 8 * ps.MASTERY_COST_FACTOR)
    # the lap-end series declines too (the refreshed table, lap by lap)
    ends = [lap["expected_cost_fam_a"] for lap in report["laps"]]
    assert ends[0] > ends[1] > ends[2], ends


# ------------------------------------------- assertion 2: attribution (P3)

@pytest.mark.skip(reason="P3 attribution bridge not built")
def test_attribution_lands_on_method_memory():
    """PENDING(P3): the plug-in point is the METHOD-MEMORY WRITE FACE —
    P3's scripts/rlvr/review_windows.py attribution bridge feeding P4's
    memory_bridge.differential_write. The harness already captures the
    real deviation window (loop_sim: anchor 0, deviation 1 — the planted
    wrong-tool step takes vm-trace where static-scan is the family
    method, and its conclusion flips H3). When P3/P4 land, this asserts
    that window lands a method-memory row keyed
    (family='fam-a', wrong_tool='vm-trace', right_tool='static-scan')
    carrying the deviation step's settled phi reward — success-path
    steps carrying their attribution too."""
    raise AssertionError("lights up when the P3 attribution bridge lands")


# ------------------------------------- assertion 3: mastered zero-write

def test_mastered_family_retires_with_zero_new_writes(tmp_path):
    """NO REPEAT LEARNING: the mastered family's leftover tasks retire
    through retire_reasons' learned face and demand ZERO new pool
    writes — no rollout, no mission, no episode; a re-settle over the
    terminal workspace writes nothing."""
    report, ws = _run(tmp_path)
    retired = {r["task_id"]: r["reason"] for r in report["laps"][2]["retired"]}
    assert retired.get("a5") == "learned", retired
    assert retired.get("b3") == "learned", retired
    picks = [p for lap in report["laps"] for p in lap["picks"]]
    assert "a5" not in picks and "b3" not in picks
    episodes = sorted((ws / "runs" / "episodes").glob("episode-*.md"))
    assert len(episodes) == 6, episodes
    assert report["settle_idempotent_second_pass"] is True


# ----------------------------------------- assertion 4: expectation switch

def test_lane_change_only_beyond_delta(tmp_path):
    """EXPECTATION LANE-CHANGE: after the laps' settlement the refreshed
    value table reprices the affected subtree (reprice_scope) and the
    previously-deprioritized fam-a overtakes the fam-b head ONLY when
    the hysteresis delta is exceeded (== delta keeps the head)."""
    report, _ws = _run(tmp_path)
    exp_a = _expected(report, "fam-a", BASE_A)
    exp_b = _expected(report, "fam-b", 0.1)
    head_b = _task("head-b", "fam-b", exp_b + 0.2, 0.1)
    # challengers self-calibrate: V(challenger) = V(head) + gap; below
    # the delta the deprioritized family's challenger holds the lane for
    # the head, beyond it overtakes (the == inclusion is pinned exactly
    # in test_pool_scheduler; derived floats keep off the boundary here)
    gaps = (("within", DELTA / 2, "head-b"),
            ("beyond", 2 * DELTA, "chal-beyond"))
    for name, gap, expect_head in gaps:
        chal = _task(f"chal-{name}", "fam-a", exp_a + 0.2 + gap, BASE_A)
        state = _state_from(report, [head_b, chal])
        state["head"] = "head-b"
        assert ps.pick_next(state, DELTA)["task_id"] == expect_head
    # the re-pricing scope is the affected subtree only — the same-family
    # task, never the fam-b head (no global reshuffle)
    fellow = _task("fellow-a", "fam-a", 0.0, BASE_A)
    scope = ps.reprice_scope({"task_id": "a4", "family": "fam-a"},
                             {"tasks": [head_b, fellow]})
    assert [t["task_id"] for t in scope] == ["fellow-a"]


# ------------------------------------------------ assertion 5: ablation

def test_pool_ablation_gain_vanishes(tmp_path):
    """ABLATION: the same three laps with the pool's memory faces ABSENT
    at the scheduler boundary (empty value table -> order_task_dirs
    byte-identical passthrough; empty memory -> no mastery discount)
    show FLAT ordering and FLAT cost — the live arm's learning delta is
    attributable to the pool, not chance."""
    live, _ws = _run(tmp_path)
    ablated, _ws2 = _run(tmp_path, name="ablated-ws", ablated=True)
    # live: the ordering moves over the laps; ablated: input passthrough
    assert live["laps"][0]["ordering"] == ["fam-b", "fam-c", "fam-a"]
    assert live["laps"][2]["ordering"] == ["fam-c", "fam-b", "fam-a"]
    for lap in ablated["laps"]:
        assert lap["ordering"] == INPUT_ORDER
    # live: the cost declines; ablated: flat at the base estimate
    assert live["expected_cost_trace"][0] > live["expected_cost_trace"][-1]
    assert ablated["expected_cost_trace"] == \
        [pytest.approx(BASE_A)] * 3
    assert [lap["expected_cost_fam_a"] for lap in ablated["laps"]] == \
        [pytest.approx(BASE_A)] * 3
    # the arms ran the same SCENARIO (same tasks, same rollouts, same
    # budget); without the pool's memory the scheduler's picks differ —
    # that IS the demonstration: the advantage rides the memory face
    live_trace = live["expected_cost_trace"]
    assert live_trace[-1] < ablated["expected_cost_trace"][-1]


# --------------------------------------- assertion 6: timeout triage

def test_timeout_three_verdicts_no_misfire(tmp_path):
    """TIMEOUT TRIAGE: the sim's oversized task rides the REAL triage —
    zero artifacts -> granularity_fault landing a sizing record, NEVER
    method memory; a closed-checkpoint envelope event lands pricing
    only; artifacts-but-failed is the ONLY method-memory negative."""
    report, _ws = _run(tmp_path)
    gran = report["timeout"]
    assert gran["verdict"] == "granularity_fault"
    assert gran["memory_landing"] == "sizing_record"
    assert gran["method_memory_negative"] is False
    tight = tt.classify_timeout([{"id": "ck", "status": "closed"}],
                                {"kind": "timeout"},
                                ["evidence/trace.log"])
    assert tight["verdict"] == "envelope_too_tight"
    assert tight["memory_landing"] == "pricing_update"
    assert tight["method_memory_negative"] is False
    fail = tt.classify_timeout([{"id": "ck", "status": "open"}],
                               {"timeout": True}, ["facts/F001.md"])
    assert fail["verdict"] == "method_fail"
    assert fail["memory_landing"] == "method_memory"
    assert fail["method_memory_negative"] is True
    # no misfire: exactly one verdict touches method memory
    assert len({gran["memory_landing"], tight["memory_landing"],
                fail["memory_landing"]}) == 3


# ------------------------------------ assertion 7: recall pollution (P4)

@pytest.mark.skip(reason="P4 recall sensors not built")
def test_recall_pollution_gate_rises():
    """PENDING(P4): the plug-in point is memory_bridge's RECALL SENSOR
    face (the gate bandit over recalled keys + the refutation fold).
    The harness already feeds the sensor input: the lap-2 learned-leg
    steps stamp used_recalled=True through real step/1 records. When P4
    lands, this asserts that a key recalled-and-ignored repeatedly has
    its gate RAISED, and a refuted fragment's reusable_when narrows
    through memory_bridge's differential write."""
    raise AssertionError("lights up when the P4 recall sensors land")


# ------------------------------------------ assertion 8: election+hysteresis

def test_info_bonus_election_and_hysteresis(tmp_path):
    """INFO-BONUS ELECTION + HYSTERESIS: the new family's FIRST task
    wins the argmax over a HIGHER-direct-value incumbent task (the
    calibration bonus), and a challenger within delta does NOT displace
    the elected head."""
    report, _ws = _run(tmp_path)
    election = report["election"]
    assert election["picked"] == "c1"
    assert election["picked_direct"] < election["incumbent_direct_max"]
    # post-settlement, the elected head holds against a challenger that
    # is strictly better but within delta; beyond delta it displaces
    # (probe directs self-calibrate against the live refreshed table)
    exp_a = _expected(report, "fam-a", BASE_A)
    head_c1 = _task("c1", "fam-c", 0.2, 0.1)
    head_v = ps.task_value(head_c1, _state_from(report, [head_c1]))
    for name, gap, expect_head in (("within", DELTA / 2, "c1"),
                                   ("beyond", 2 * DELTA, "chal-beyond")):
        chal = _task(f"chal-{name}", "fam-a", exp_a + head_v + gap, BASE_A)
        state = _state_from(report, [head_c1, chal])
        state["head"] = "c1"
        assert ps.pick_next(state, DELTA)["task_id"] == expect_head


# ------------------------- the learning argument (the owner's demand)

def test_learning_delta_table_lap_over_lap(tmp_path):
    """THE LEARNING ARGUMENT: the lap-over-lap delta table — fam-a's
    expected cost declines monotonically; every head change respected
    the hysteresis delta; the ablation arm is flat on both axes, so the
    delta is the memory face's work and nothing else."""
    live, _ws = _run(tmp_path)
    ablated, _ws2 = _run(tmp_path, name="ablated-ws", ablated=True)
    trace = live["expected_cost_trace"]
    assert trace[0] > trace[1] > trace[2], trace
    assert [len(lap["picks"]) for lap in live["laps"]] == [2, 2, 2]
    for lap in live["laps"]:
        for tr in lap["transitions"]:
            if tr["head_before"] is not None \
                    and tr["picked"] != tr["head_before"]:
                assert tr["picked_v"] - tr["head_v"] > live["delta"], tr
    assert ablated["expected_cost_trace"] == [pytest.approx(BASE_A)] * 3
    assert all(lap["ordering"] == INPUT_ORDER for lap in ablated["laps"])
    assert live["laps"][0]["ordering"] != live["laps"][2]["ordering"]
    assert live["expected_cost_trace"][-1] \
        < ablated["expected_cost_trace"][-1]
