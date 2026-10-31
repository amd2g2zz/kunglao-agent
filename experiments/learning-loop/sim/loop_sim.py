# -*- coding: utf-8 -*-
"""loop_sim.py — the closed-loop mock harness driver (card P7 of the
learning-loop live-wire program; lives under experiments/learning-loop/
since the #865 relocation — an experiment driver, never a production
package member).

The simulator behind tests/test_learning_loop_harness.py and
tests/test_proof_battery.py: a synthetic, deterministic workspace (no
real sessions) over which the FULL loop runs for N laps with mock
workers:

    pick (pool argmax, hysteresis delta) -> goal-backward plan ->
    steps (real step/1 records, validated) -> rolling step settlement
    (real step_reward) -> planted-failure deviation window (real
    segment_view) -> timeout triage (real classify_timeout) ->
    terminal settle (real settle_mission) -> family-memory stamp ->
    retire / inflow -> next lap.

THIN BY CONTRACT: every learning decision rides a REAL face —
step_record (validate_step / segment_view / backward_plan / tree_view),
reward_signal.step_reward / episode_reward, timeout_triage
.classify_timeout, episode_settle (settle_mission / derived_views),
pool_indexer.value_table, pool_scheduler (task_value / pick_next /
reprice_scope / retire_reasons / inflow_from_failure /
order_task_dirs), ledger.record, review_windows (the attribution
bridge), and memory_bridge (the differential write-through + recall
sensors + gate). This module owns only the mock worker's choices
(which tool, how many tokens, which conclusion) — every mission's cost
booking is the settle line's OWN honest arithmetic: episode_settle's
per-mission spend window (_spend_window, the P7c fix) books each
episode the cost events SINCE the previous settle mark, and stamps the
A1 reward from that block. The mock's one cost-event row per mission
(`_ledger_row`, amount = tokens/1e4) lands exactly one-to-one in its
mission's window, so the episodes carry the REAL per-mission spend —
the old compensation re-booking (a workaround for the pre-P7c
cumulative fold) is gone, not patched around.

  _stamp_family_memory — THE P4 WRITE-THROUGH, LIVE: the settled
    episode's family identity rides the REAL memory_bridge differential
    write-through — the context features (bare + ``family:`` prefixed)
    name the family the scheduler joins on, the episode's own
    ``family`` field carries the TRUE identity the bridge's mastery
    face validates against, and memory_bridge's own differential
    decides what a memory row is and whether the family is mastered
    (EARNED: completed + positive reward + identity match — the loop
    never grants it). ``scramble`` misfiles the CONTEXT features under
    the ring's next family (the E1c control): the memory face is FED
    but fed the WRONG family, and post-identity-validation a misfiled
    episode masters nothing.

run_learning_loop(ws, *, delta, ablate_pool_memory, laps,
ablate_value_table, ablate_memory, scramble_memory) -> report dict.
The ablation arms replay the IDENTICAL lap history with the pool's
memory faces absent at the scheduler boundary (both, or one each);
``scramble_memory=True`` feeds the memory face WRONG-family features
(the E1c control); laps 4+ run fam-a consolidation repeats (the E1d
/E3b dose arms). Whatever learning delta disappears under ablation or
scrambling is attributable to the pool's memory CONTENT, nothing else.
"""
from __future__ import annotations

import json
from pathlib import Path

# the lazy `from rlvr import ...` faces and the production scaffold
# import need scripts/ + the learning-loop faces on sys.path after the
# #936 relocation into the sim tier
import sys
_SIM = Path(__file__).resolve().parent
_LOOP = _SIM.parent
_SCRIPTS = _SIM.parents[2] / "scripts"
for _p in (_SIM, _LOOP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from loop import _bootstrap  # noqa: E402 — the production scaffold (sim→production)

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


def _make_consolidation(seq: int):
    """Laps 4+ (the E1d/E3b dose arms): the mastered family's in-family
    repeat — one step at the family's cheapest honest bill (2000
    tokens), a fresh claim each time so each mission is one DISTINCT
    episode in the value table's cell."""
    def _rollout():
        hyp_id = f"H{20 + seq}"
        steps = [_step("offset table",
                       [_hyp(hyp_id, "the offset table is stable "
                             "across builds")],
                       "static-scan",
                       f"{hyp_id} survives: the offset table replays "
                       "identically",
                       used_recalled=True, tokens=2000,
                       checkpoint_closed=True)]
        return steps, {"claim": f"C-A{5 + seq}", "status": "PROVEN",
                       "title": f"fam-a consolidation {seq}",
                       "family": "fam-a", "tokens": 2000}
    return _rollout


def _scenario_extensions(laps: int):
    """The laps-4+ scenario extension: two fam-a consolidation tasks per
    lap (inflow) and their rollout builders. The dose that drives the
    empirical mean toward its asymptote; each mission settles at the
    family's cheapest honest bill."""
    inflows = []
    for lap_no in range(4, laps + 1):
        seq0 = 2 * (lap_no - 4)
        inflows.append(
            (_task(f"a{6 + seq0}", "fam-a", 0.2, FAM_A_BASE_COST,
                   ("static-scan",)),
             _task(f"a{7 + seq0}", "fam-a", 0.15, FAM_A_BASE_COST,
                   ("static-scan",))))
    rollouts = {f"a{5 + seq}": _make_consolidation(seq)
                for seq in range(1, 2 * max(laps - 3, 0) + 1)}
    return tuple(inflows), rollouts


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

def _scrambled(family: str) -> str:
    """The E1c control's fault injection: rotate the family token one
    step around the family ring (fam-a -> fam-b -> fam-c -> fam-a), so
    the memory face is FED but fed the WRONG family."""
    names = list(FAMILIES)
    return names[(names.index(family) + 1) % len(names)]


def _stamp_family_memory(ws, claim, family, memory, *, scramble=False):
    """THE P4 WRITE-THROUGH, LIVE: the settled episode's family identity
    rides the REAL memory_bridge differential write-through — mastery is
    EARNED there (a completed mission with a positive A1 reward whose
    OWN family matches the stamping family; a failed, reward-negative,
    or misfiled mission never masters). Returns the scheduler's memory
    view, read back from memory_bridge.family_view.

    NO COST BOOKING HERE ANY MORE: the pre-P7c settle face booked the
    workspace's CUMULATIVE cost events into every episode, and this face
    re-booked the per-mission block as a workaround. P7c's spend window
    fixed the settle line itself — each episode now carries its own
    window's spend and the A1 reward stamped from it — so the stamp face
    is back to its ONE job: family identity. It writes the context
    features the scheduler's join reads (bare + ``family:`` prefixed)
    and the episode's own ``family`` field the bridge's mastery face
    validates against. ``scramble`` misfiles ONLY the context features
    (the E1c control); the true identity rides the ``family`` field a
    misfiling cannot rewrite — post-identity-validation a misfiled
    episode masters nothing.
    """
    from rlvr import episode_pool
    from rlvr import episode_schema
    from rlvr import memory_bridge
    carrier = _scrambled(family) if scramble else family
    path = episode_pool.episode_path(ws, claim)
    doc, body = episode_schema.read_episode_file(path)
    doc["context_features"] = sorted(
        {*(doc.get("context_features") or []),
         carrier, f"family:{carrier}"})
    doc["family"] = family
    episode_schema.write_episode_file(path, doc, body=body)
    memory_bridge.stamp_family_memory(ws, doc)
    return {str(k).removeprefix("family:"):
            v for k, v in memory_bridge.family_view(ws).items()}


# ------------------------------------------------------------- the loop

# the one-workspace-one-run scaffold moved to the production face
# (loop._bootstrap — the #936 extraction; the sim was its first
# consumer, not its owner) and imported back above under the same
# name, so ``loop_sim._bootstrap`` call sites keep resolving.

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


def _settle_and_stamp(ws, mission, memory, *, scramble=False):
    from rlvr import episode_settle
    out = episode_settle.settle_mission(ws)
    if out["episodes_written"]:
        memory = _stamp_family_memory(ws, mission["claim"],
                                      mission["family"], memory,
                                      scramble=scramble)
        episode_settle.derived_views(ws)
    return out, memory


def _pool_state(tasks, head, memory, counts, table, ablated, *,
                use_table=True, use_memory=True):
    """The scheduler's pool_state view. ``ablated`` kills BOTH memory
    faces (the classic P7 ablation); the keyword flags kill one each
    (the E3a component arms: cost-face-only / method-memory-only)."""
    return {"tasks": list(tasks), "head": head,
            "memory": dict(memory) if use_memory and not ablated else {},
            "value_table": dict(table) if use_table and not ablated else {},
            "family_counts": dict(counts),
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


def run_learning_loop(ws, *, delta=DELTA, ablate_pool_memory=False,
                      laps=3, ablate_value_table=False,
                      ablate_memory=False, scramble_memory=False):
    """``laps`` laps of the closed loop over ``ws`` (a fresh tmp dir);
    laps 4+ run fam-a consolidation repeats (the E1d/E3b dose arms ride
    them). ``ablate_pool_memory`` kills BOTH memory faces at the
    scheduler boundary (the classic P7 ablation); ``ablate_value_table``
    / ``ablate_memory`` kill one each (the E3a component arms);
    ``scramble_memory`` feeds the memory face WRONG-family features at
    stamp time (the E1c control). Returns the lap-by-lap report the
    harness and the proof battery assert on."""
    import rlvr.pool_scheduler as ps
    from rlvr import pool_indexer
    from rlvr import step_record

    ws = Path(ws)
    _bootstrap(ws)
    use_table = not (ablate_pool_memory or ablate_value_table)
    use_memory = not (ablate_pool_memory or ablate_memory)
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
    extra_inflows, extra_rollouts = _scenario_extensions(laps)
    lap_inflows = lap_inflows + extra_inflows
    rollouts = {**ROLLOUTS, **extra_rollouts}
    report = {"delta": delta, "ablated": ablate_pool_memory, "laps": [],
              "expected_cost_trace": [], "deviation_window": None,
              "timeout": None, "election": None, "trajectory_steps": {}}
    #: the serial rollout budget per lap — the lap ends when the budget
    #: is spent (or the pool is empty); the remainder sweeps retirement
    lap_budgets = (2,) * laps
    for lap_no, inflow in enumerate(lap_inflows[:laps], start=1):
        pool = [*pool, *(dict(t) for t in inflow)]
        lap = {"lap": lap_no, "picks": [], "transitions": [],
               "episodes": [], "retired": [], "timeout_verdict": None}
        while len(lap["picks"]) < lap_budgets[lap_no - 1]:
            state = _pool_state(pool, head, memory, counts, table,
                                ablate_pool_memory, use_table=use_table,
                                use_memory=use_memory)
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
                steps, mission = rollouts[pick_id]()
                report["trajectory_steps"][pick_id] = steps
            if pick_id == "a1":
                window = step_record.segment_view(steps)
                report["deviation_window"] = {
                    "anchor": window["anchor"],
                    "deviation": window["deviation"]}
            _register(ws, mission)
            _ledger_row(ws, mission)
            out, memory = _settle_and_stamp(ws, mission, memory,
                                            scramble=scramble_memory)
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
                            ablate_pool_memory, use_table=use_table,
                            use_memory=use_memory)
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
                        ablate_pool_memory, use_table=use_table,
                        use_memory=use_memory), "fam-a", FAM_A_BASE_COST)
        report["laps"].append(lap)
    report["final"] = {"memory": dict(memory), "counts": dict(counts),
                       "value_table": table,
                       "pool": [str(t["task_id"]) for t in pool]}
    from rlvr import episode_settle
    report["settle_idempotent_second_pass"] = (
        episode_settle.settle_mission(ws)["episodes_written"] == 0)
    return report
