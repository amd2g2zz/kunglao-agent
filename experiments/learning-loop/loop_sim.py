# -*- coding: utf-8 -*-
"""rlvr/loop_sim.py — the closed-loop mock harness driver (card P7 of
the learning-loop live-wire program).

The simulator behind tests/test_learning_loop_harness.py: a synthetic,
deterministic workspace (no real sessions) over which the FULL loop
runs for three laps with mock workers:

    pick (pool argmax, hysteresis delta) -> goal-backward plan ->
    steps (real step/1 records, validated) -> rolling step settlement
    (real step_reward) -> planted-failure deviation window (real
    segment_view) -> timeout triage (real classify_timeout) ->
    terminal settle (real settle_mission) -> family-memory stamp ->
    retire / inflow -> next lap.

THIN BY CONTRACT: every learning decision rides a REAL face —
step_record (validate_step / segment_view / backward_plan / tree_view),
reward_signal.step_reward, timeout_triage.classify_timeout,
episode_settle (settle_mission / derived_views), pool_indexer
.value_table, pool_scheduler (task_value / pick_next / reprice_scope /
retire_reasons / inflow_from_failure / order_task_dirs), and
ledger.record. This module owns
only the mock worker's choices (which tool, how many tokens) and ONE
named stand-in for a face a later card owes:

  _stamp_family_memory — THE P4 PLUG-IN POINT (memory_bridge's
    differential write-through). It stamps the landed episode's family
    context feature, an HONEST cost block (settle_mission's built
    episode carries tokens=0/seconds=0, so the value table's cost
    dimension is blind to the mission's actual spend — reported to the
    settle card, not patched there), the A1 reward re-stamp, and the
    family's ``mastered`` memory row.

run_learning_loop(ws, *, delta, ablate_pool_memory) -> report dict.
``ablate_pool_memory=True`` replays the IDENTICAL lap history with the
pool's memory faces absent at the scheduler boundary (value_table {}
-> order_task_dirs passthrough; memory {} -> no mastery discount):
whatever learning delta disappears under ablation is attributable to
the pool, nothing else.
"""
from __future__ import annotations

import json
from pathlib import Path

# the lazy `from rlvr import ...` faces need scripts/ on sys.path after the relocation
import sys
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

DELTA = 0.1
FAMILIES = ("fam-a", "fam-b", "fam-c")
#: the tracked family's base cost (the probe's expected-cost anchor)
FAM_A_BASE_COST = 0.9
#: the timeout window's wasted token bill (saturates the cost term)
TIMEOUT_TOKENS = 16000


# ------------------------------------------------------------ mock worker

def _task(tid, family, direct, base_cost, tools):
    return {"task_id": tid, "family": family, "direct_value": direct,
            "base_cost": base_cost, "tools": list(tools), "tier": 1,
            "deps": [], "premises": []}


def _hyp(hid, claim):
    return {"id": hid, "claim": claim,
            "kill_test": f"an experiment that flips {hid}"}


def _step(task, hypotheses, action, conclusion, *, used_recalled, tokens,
          checkpoint_closed):
    """One mock-worker step: a real step/1 record, reward-settled by the
    REAL rolling step settlement (reward_signal.step_reward) over the
    step's own hypothesis set, then validated fail-closed."""
    from rlvr import reward_signal
    from rlvr import step_record
    doc = {
        "schema": step_record.SCHEMA,
        "task": task,
        "environment": {"type": "synthetic-static", "auth_state": "local"},
        "observation": f"{task}: ran {action} over the fixture binary",
        "hypotheses": hypotheses,
        "action": action,
        "result": f"{action} produced observable output",
        "conclusion": conclusion,
        "confidence": 0.9,
        "reusable_when": [f"the target is a {task} fixture binary"],
        "used_recalled": used_recalled,
    }
    doc["reward"] = {
        "value": reward_signal.step_reward(
            hypotheses, conclusion, True, checkpoint_closed, tokens, 0.0),
        "source": "phi_gain",
    }
    return step_record.validate_step(doc)


def _rollout_a1():
    """Lap 1, fam-a: cold start with the PLANTED wrong-tool deviation —
    step 2 takes vm-trace (the wrong path), its conclusion flips H3, the
    segment view captures the window, step 3 recovers on static-scan."""
    steps = [
        _step("offset recovery",
              [_hyp("H1", "the checksum family is md5"),
               _hyp("H2", "the constants are plain sha256")],
              "static-scan",
              "H1 survives: the digest width matches md5, not sha256",
              used_recalled=False, tokens=2000, checkpoint_closed=True),
        _step("key schedule",
              [_hyp("H3", "the key schedule lives in .data")],
              "vm-trace",
              "H3 is refuted: the vm-trace artifacts contradict the "
              ".data key schedule hypothesis",
              used_recalled=False, tokens=4000, checkpoint_closed=False),
        _step("key schedule",
              [_hyp("H4", "the key schedule is derived at runtime")],
              "static-scan",
              "H3 dies; H4 survives: the movz chain in .text derives "
              "the schedule, nothing is stored",
              used_recalled=False, tokens=3000, checkpoint_closed=True),
    ]
    return steps, {"claim": "C-A1", "status": "PROVEN",
                   "title": "fam-a offsets", "family": "fam-a",
                   "tokens": 9000}


def _rollout_b1():
    steps = [_step("packer id", [_hyp("H5", "the packer is UPX")], "vm",
                   "H5 survives: the UPX signature holds",
                   used_recalled=False, tokens=1000, checkpoint_closed=True)]
    return steps, {"claim": "C-B1", "status": "PROVEN",
                   "title": "fam-b packer", "family": "fam-b",
                   "tokens": 1000}


def _rollout_a2():
    """Lap 2, fam-a: the failed family RETRIED with the corrected path —
    the learned leg (step 1 rides the recall sensor)."""
    steps = [
        _step("key schedule",
              [_hyp("H9", "the movz chain derives the schedule")],
              "static-scan",
              "H9 survives: the recalled movz chain reproduces the digest",
              used_recalled=True, tokens=1500, checkpoint_closed=True),
        _step("digest replay",
              [_hyp("H10", "the digest replays under the mutated md5")],
              "static-scan",
              "H10 survives: the replay matches the capture",
              used_recalled=False, tokens=2500, checkpoint_closed=True),
    ]
    return steps, {"claim": "C-A2", "status": "PROVEN",
                   "title": "fam-a retry", "family": "fam-a",
                   "tokens": 4000}


def _rollout_c1():
    steps = [_step("input grammar",
                   [_hyp("H11", "the fuzz lane covers the grammar")],
                   "fuzz",
                   "H11 survives: the grammar coverage holds",
                   used_recalled=False, tokens=500, checkpoint_closed=True)]
    return steps, {"claim": "C-C1", "status": "PROVEN",
                   "title": "fam-c grammar", "family": "fam-c",
                   "tokens": 500}


def _rollout_a4():
    """Lap 3, fam-a consolidation: the mastered repeat completes in ONE
    step at the cheapest token bill of the family's history."""
    steps = [_step("offset table",
                   [_hyp("H12", "the offset table is stable across builds")],
                   "static-scan",
                   "H12 survives: the offset table replays identically",
                   used_recalled=True, tokens=2000, checkpoint_closed=True)]
    return steps, {"claim": "C-A4", "status": "PROVEN",
                   "title": "fam-a consolidation", "family": "fam-a",
                   "tokens": 2000}


def _rollout_b3():
    steps = [_step("right-sized window",
                   [_hyp("H13", "the resized window closes its checkpoint")],
                   "vm",
                   "H13 survives: the right-sized window replays the KAT",
                   used_recalled=False, tokens=1000, checkpoint_closed=True)]
    return steps, {"claim": "C-B3", "status": "PROVEN",
                   "title": "fam-b right-sized", "family": "fam-b",
                   "tokens": 1000}


ROLLOUTS = {"a1": _rollout_a1, "b1": _rollout_b1,
            "failure-analysis:C-A1": _rollout_a2, "c1": _rollout_c1,
            "a4": _rollout_a4, "b3": _rollout_b3}


def _rollout_b2_timeout():
    """Lap 2, fam-b: the OVERSIZED task — the envelope kills the window
    with zero artifacts; classify_timeout rules it a granularity fault."""
    from rlvr import step_record
    from rlvr import timeout_triage
    # planted terminal row in the P6 gate's own documented shape
    # (hooks/worker_budget_gates.py: action "envelope_timeout", detail
    # {tier, over:[{dim, cap, actual}]}, TIER-1 wall cap 600s) — the
    # gate EMITS this row in production; the mock plants it and the
    # triage face CONSUMES it. No hooks import: scripts never import
    # the hooks package (dep surface).
    event = {"action": "envelope_timeout",
             "detail": {"tier": 1,
                        "over": [{"dim": "wall_s", "cap": 600,
                                  "actual": 700.0}]}}
    plan = step_record.backward_plan(
        "the oversized claim completes inside the window", [])
    verdict = timeout_triage.classify_timeout(plan, event, [])
    return {"checkpoints": plan, "envelope_event": event,
            "verdict": verdict}


# ------------------------------------------------------- the P4 plug-in

def _stamp_family_memory(ws, claim, family, tokens, memory):
    """THE P4 PLUG-IN POINT — memory_bridge.differential_write stands in
    here until card P4 lands. Writes through the pool's own schema face
    (the same face episode_pool.update_on_settlement uses for updates):
    family context feature + honest cost block + A1 reward re-stamp, and
    the family's ``mastered`` row in the scheduler's memory view."""
    from rlvr import episode_pool
    from rlvr import episode_schema
    from rlvr import reward_signal
    path = episode_pool.episode_path(ws, claim)
    doc, body = episode_schema.read_episode_file(path)
    doc["context_features"] = sorted(
        {*(doc.get("context_features") or []), family})
    doc["cost"] = {"tokens": tokens, "seconds": 0,
                   "spend_usd": (doc.get("cost") or {}).get("spend_usd", 0.0)}
    completion = 1.0 if (doc.get("outcome") or {}).get("status") \
        == "completed" else 0.0
    doc["reward"] = float(
        reward_signal.compute_reward(completion, 0.0, tokens, 0.0))
    episode_schema.write_episode_file(path, doc, body=body)
    return {**memory, family: {"mastered": True}}


# ------------------------------------------------------------- the loop

def _bootstrap(ws):
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n- id: pq1\n  q: replay the fixture family\n",
        encoding="utf-8")
    (ws / "runs").mkdir(parents=True, exist_ok=True)


def _register(ws, mission):
    import yaml
    doc = {"claims": [{"id": mission["claim"], "status": mission["status"],
                       "title": mission["title"]}]}
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(doc), encoding="utf-8")


def _ledger_row(ws, mission):
    from rlvr import ledger
    ledger.record(ws, "task", mission["claim"], [],
                  rollout_id=f"rollout-{mission['claim']}",
                  ts=mission["claim"].lower())
    with (ws / "cost_events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"amount": mission["tokens"] / 10_000.0}) + "\n")


def _settle_and_stamp(ws, mission, memory):
    from rlvr import episode_settle
    out = episode_settle.settle_mission(ws)
    if out["episodes_written"]:
        memory = _stamp_family_memory(ws, mission["claim"],
                                      mission["family"], mission["tokens"],
                                      memory)
        episode_settle.derived_views(ws)
    return out, memory


def _pool_state(tasks, head, memory, counts, table, ablated):
    return {"tasks": list(tasks), "head": head,
            "memory": {} if ablated else dict(memory),
            "family_counts": dict(counts),
            "value_table": {} if ablated else dict(table),
            "recall_covered": [], "stale_premises": []}


def _expected_cost_probe(state, family, base_cost):
    """Measurement, not behavior: the probe's info bonus is pinned to 0
    (its family count forced >= 1) so -task_value IS the expected cost
    the scheduler would pay for a neutral fam-a task right now."""
    import rlvr.pool_scheduler as ps
    probe = _task("probe", family, 0.0, base_cost, ())
    probe_state = {**state, "tasks": [probe],
                   "family_counts": {**state["family_counts"], family:
                                     max(int(
                                         state["family_counts"].get(family)
                                         or 0), 1)}}
    return -ps.task_value(probe, probe_state)


def run_learning_loop(ws, *, delta=DELTA, ablate_pool_memory=False):
    """Three laps of the closed loop over ``ws`` (a fresh tmp dir). See
    the module docstring. Returns the lap-by-lap report the harness
    asserts on."""
    import rlvr.pool_scheduler as ps
    from rlvr import pool_indexer
    from rlvr import step_record

    ws = Path(ws)
    _bootstrap(ws)
    pool = [_task("a1", "fam-a", 0.8, FAM_A_BASE_COST, ("static-scan",)),
            _task("b1", "fam-b", 0.6, 0.1, ("vm",))]
    head = "b1"
    counts = {"fam-b": 1}
    memory: dict = {}
    table: dict = {}
    lap_inflows = (
        (),
        # the failure-analysis inlet: the lap-1 planted failure derives
        # its follow-up through the REAL inflow face
        (ps.inflow_from_failure({"claim": "C-A1", "family": "fam-a",
                                 "attribution": "wrong tool path vm-trace; "
                                 "static-scan is the family method",
                                 "direct_value": 0.5}),
         _task("b2", "fam-b", 0.2, 0.1, ("vm",))),
        (_task("a4", "fam-a", 0.35, FAM_A_BASE_COST, ("static-scan",)),
         _task("a5", "fam-a", 0.2, FAM_A_BASE_COST, ("static-scan",)),
         _task("b3", "fam-b", 0.1, 0.1, ("vm",)),
         _task("c1", "fam-c", 0.2, 0.1, ("fuzz",))),
    )
    report = {"delta": delta, "ablated": ablate_pool_memory, "laps": [],
              "expected_cost_trace": [], "deviation_window": None,
              "timeout": None, "election": None}
    #: the serial rollout budget per lap — the lap ends when the budget
    #: is spent (or the pool is empty); the remainder sweeps retirement
    lap_budgets = (2, 2, 2)
    for lap_no, inflow in enumerate(lap_inflows, start=1):
        pool = [*pool, *(dict(t) for t in inflow)]
        lap = {"lap": lap_no, "picks": [], "transitions": [],
               "episodes": [], "retired": [], "timeout_verdict": None}
        while len(lap["picks"]) < lap_budgets[lap_no - 1]:
            state = _pool_state(pool, head, memory, counts, table,
                                ablate_pool_memory)
            pick = ps.pick_next(state, delta)
            if pick is None:
                break
            pick_id = str(pick["task_id"])
            head_task = next((t for t in pool
                              if str(t["task_id"]) == str(head)), None)
            lap["transitions"].append({
                "picked": pick_id,
                "picked_v": ps.task_value(pick, state),
                "head_before": head if head_task else None,
                "head_v": ps.task_value(head_task, state)
                if head_task else None})
            if not lap["picks"]:
                # the lap's decision point: the expected cost the
                # scheduler pays for fam-a on THIS lap's first pick
                report["expected_cost_trace"].append(
                    _expected_cost_probe(state, "fam-a", FAM_A_BASE_COST))
            if pick_id == "b2":
                triage = _rollout_b2_timeout()
                lap["timeout_verdict"] = triage["verdict"]
                report["timeout"] = triage["verdict"]
                mission = {"claim": "C-B2", "status": "NEGATIVE",
                           "title": "fam-b oversized", "family": "fam-b",
                           "tokens": TIMEOUT_TOKENS}
                steps = []
            else:
                steps, mission = ROLLOUTS[pick_id]()
            if pick_id == "a1":
                window = step_record.segment_view(steps)
                report["deviation_window"] = {
                    "anchor": window["anchor"],
                    "deviation": window["deviation"]}
            _register(ws, mission)
            _ledger_row(ws, mission)
            out, memory = _settle_and_stamp(ws, mission, memory)
            lap["episodes"].append(
                {"claim": mission["claim"], "written":
                 out["episodes_written"]})
            family = str(pick["family"])
            counts = {**counts, family: int(counts.get(family) or 0) + 1}
            pool = [t for t in pool if str(t["task_id"]) != pick_id]
            head = pick_id
            lap["picks"].append(pick_id)
            if pick_id == "c1":
                report["election"] = {
                    "picked": pick_id,
                    "picked_v": ps.task_value(pick, state),
                    "incumbent_direct_max": max(
                        float(t["direct_value"]) for t in pool),
                    "picked_direct": float(pick["direct_value"])}
        table = pool_indexer.value_table(ws)
        state = _pool_state(pool, head, memory, counts, table,
                            ablate_pool_memory)
        kept = []
        for t in pool:
            reason = ps.retire_reasons(t, state)
            if reason:
                lap["retired"].append({"task_id": str(t["task_id"]),
                                       "reason": reason})
            else:
                kept.append(t)
        pool = kept
        lap["ordering"] = [p.name for p in ps.order_task_dirs(
            [Path(f) for f in FAMILIES], state["value_table"])]
        lap["expected_cost_fam_a"] = _expected_cost_probe(
            _pool_state(pool, head, memory, counts, table,
                        ablate_pool_memory), "fam-a", FAM_A_BASE_COST)
        report["laps"].append(lap)
    report["final"] = {"memory": dict(memory), "counts": dict(counts),
                       "value_table": table,
                       "pool": [str(t["task_id"]) for t in pool]}
    from rlvr import episode_settle
    report["settle_idempotent_second_pass"] = (
        episode_settle.settle_mission(ws)["episodes_written"] == 0)
    return report
