# -*- coding: utf-8 -*-
"""rlvr/pool_scheduler.py — the two-level task scheduler (the scheduler
card, P5 of the learning-loop live-wire program).

LEVEL 2 (the task pool, sequential rollouts) — one round picks ONE task,
argmax over V; no re-selection mid-rollout:

    V(task) = direct_value + info_value - expected_cost

  info_value     the family-prior calibration bonus: the FIRST task of a
                 family carries it; in-family repeats decay it as
                 bonus * INFO_DECAY**repeat_count (decay = 0.0 -> strictly
                 first-of-family, the scheduler pin: second-of-family == 0);
  expected_cost  DERIVED from memory, never trained: the empirical mean
                 cost of the family's value-table cells when the pool has
                 stamped any, else the task's base cost; a family whose
                 method the memory face marks mastered pays only
                 MASTERY_COST_FACTOR of it (cost down -> V auto-down on
                 repeats — no separate ranking weights).

  hysteresis     pick_next keeps the incumbent head unless a challenger
                 beats it by MORE than delta (== delta keeps the head —
                 noise-level repricing must not churn the queue);
  re-pricing     reprice_scope returns ONLY the affected subtree (the
                 tasks sharing the settled task's family — the shared
                 context feature), never a full-pool reshuffle;
  churn          inlets: inflow_from_failure derives the failure-analysis
                 follow-up task; outlets: retire_reasons names why a task
                 should leave (learned / recall-covered / premise-expired).

LEVEL 3/4 (steps inside a rollout, parallel, slot-bounded) —
select_batch fills the free slots in ONE pass over the value-ranked
tasks: unmet dependency -> skipped (a dependency is never inverted, not
even within the batch); a scarce tool already in-flight (present in
tool_load, or taken earlier in this same batch) -> skipped (max ONE
in-flight per tool); tier spread: a T3 in the batch blocks further T3
but never T1 (SERIAL_TIER).

Pure functions over plain dicts — no I/O, no storage, no telemetry
(Standard 11). The pool shapes are the scheduler's contract:

    task = {task_id, family, direct_value, base_cost, tools, tier,
            deps, premises}
    pool_state = {tasks, head, value_table, memory, family_counts,
                  recall_covered, stale_premises}

  where value_table is pool_indexer.value_table's shape (keys are
  (sorted context features, action)), memory maps family -> {mastered},
  family_counts maps family -> settled in-family episode count.
"""
from __future__ import annotations

from pathlib import Path

#: the family-prior calibration bonus (first-of-family only)
INFO_BONUS = 1.0
#: the info-decay base: bonus * INFO_DECAY**repeat_count; 0.0 makes the
#: bonus strictly first-of-family (second-of-family bonus == 0, the pin)
INFO_DECAY = 0.0
#: a family with its method already in memory pays this fraction of the
#: expected cost (learned = cheap)
MASTERY_COST_FACTOR = 0.25
#: the derived failure-analysis task's default direct value (a failure
#: with a clean attribution is the pool's cheapest honest information)
FAILURE_ANALYSIS_VALUE = 0.5
#: the serial tier: one T3 in the batch blocks further T3s (T1/T2 run
#: concurrently)
SERIAL_TIER = 3


# ------------------------------------------------------- level 2: V value

def _info_value(family: str, family_counts: dict) -> float:
    """The calibration bonus, decayed by in-family repeats."""
    repeats = int(family_counts.get(family) or 0)
    return INFO_BONUS * (INFO_DECAY ** repeats)


def _family_mean_cost(family: str, table: dict) -> float | None:
    """The n-weighted empirical mean cost over the family's value-table
    cells (feature membership, the pool's intersection face); None when
    the pool has no stamped cell for the family."""
    total_n = 0
    weighted = 0.0
    for key, cell in table.items():
        if family not in key[0]:
            continue
        n = int(cell.get("n") or 0)
        total_n += n
        weighted += float(cell.get("mean_cost") or 0.0) * n
    if total_n == 0:
        return None
    return weighted / total_n


def _expected_cost(task: dict, pool_state: dict) -> float:
    """Memory-derived cost: empirical family cost when the pool has one,
    else the task's base estimate; mastered family method discounts it."""
    family = str(task.get("family") or "")
    empirical = _family_mean_cost(family,
                                  pool_state.get("value_table") or {})
    base = empirical if empirical is not None \
        else float(task.get("base_cost") or 0.0)
    memory = pool_state.get("memory") or {}
    mastered = bool((memory.get(family) or {}).get("mastered"))
    return base * (MASTERY_COST_FACTOR if mastered else 1.0)


def task_value(task: dict, pool_state: dict) -> float:
    """V = direct_value + info_value - expected_cost (see module doc)."""
    family = str(task.get("family") or "")
    return (float(task.get("direct_value") or 0.0)
            + _info_value(family, pool_state.get("family_counts") or {})
            - _expected_cost(task, pool_state))


def pick_next(pool_state: dict, delta: float) -> dict | None:
    """ONE task: argmax V over the pool with hysteresis — the incumbent
    head stays unless a challenger beats it by MORE than delta. Ties
    break on task_id (deterministic). Empty pool -> None."""
    tasks = list(pool_state.get("tasks") or [])
    if not tasks:
        return None
    scored = sorted(((-task_value(t, pool_state), str(t.get("task_id")), t)
                     for t in tasks), key=lambda s: (s[0], s[1]))
    best = scored[0][2]
    head_id = pool_state.get("head")
    head = next((t for t in tasks
                 if str(t.get("task_id")) == str(head_id)), None) \
        if head_id else None
    if head is not None:
        challenger_v = task_value(best, pool_state)
        head_v = task_value(head, pool_state)
        if challenger_v - head_v <= delta:
            return head  # within delta (== included): the head keeps the slot
    return best


def reprice_scope(settled_task: dict, pool: dict) -> list[dict]:
    """The affected subtree ONLY: pool tasks sharing the settled task's
    family (the shared context feature). Never a global reshuffle; the
    settled task itself is not part of its own scope."""
    family = str(settled_task.get("family") or "")
    settled_id = str(settled_task.get("task_id"))
    return [t for t in (pool.get("tasks") or [])
            if str(t.get("family") or "") == family
            and str(t.get("task_id")) != settled_id]


# ---------------------------------------------------- pool in/out faces

def retire_reasons(task: dict, pool_state: dict) -> str | None:
    """Why the task should leave the pool, or None to keep it. Checked in
    the card's order: learned, recall-covered, premise-expired."""
    family = str(task.get("family") or "")
    memory = pool_state.get("memory") or {}
    if bool((memory.get(family) or {}).get("mastered")):
        return "learned"
    tid = str(task.get("task_id"))
    if tid in {str(c) for c in pool_state.get("recall_covered") or []}:
        return "recall-covered"
    stale = {str(p) for p in pool_state.get("stale_premises") or []}
    if any(str(p) in stale for p in task.get("premises") or []):
        return "premise-expired"
    return None


def inflow_from_failure(failure_row: dict) -> dict:
    """The failure-analysis inlet: a clean-attribution failure row derives
    its follow-up task (same family, documented default direct value).
    A row without a claim or family is a contract breach -> loud."""
    claim = str(failure_row.get("claim") or "").strip()
    family = str(failure_row.get("family") or "").strip()
    if not claim:
        raise ValueError("inflow_from_failure: failure_row has no claim")
    if not family:
        raise ValueError(f"inflow_from_failure: failure row {claim!r} "
                         "has no family")
    dv = failure_row.get("direct_value")
    return {
        "task_id": f"failure-analysis:{claim}",
        "family": family,
        "direct_value": float(dv) if isinstance(dv, (int, float))
        else FAILURE_ANALYSIS_VALUE,
        "base_cost": 0.0,
        "tools": [],
        "tier": 1,
        "deps": [],
        "premises": [],
        "origin": "failure-analysis",
        "origin_claim": claim,
    }


# --------------------------------------------------- level 3/4: the batch

def select_batch(ranked: list[dict], free_slots: int, deps: dict,
                 tiers: dict, tool_load: dict) -> list[dict]:
    """One round over the value-ranked tasks until the slots fill:

    - unmet deps (a non-empty entry in ``deps``) -> skip: a dependency is
      never inverted, not even by scheduling both ends in one batch;
    - any of the task's tools already in-flight (a key of ``tool_load``
      or taken by an earlier pick in THIS batch) -> skip: max one
      in-flight per scarce tool;
    - tier spread: a SERIAL_TIER task in the batch blocks further
      SERIAL_TIER tasks; other tiers keep filling the batch.

    ``tiers`` is keyed by task_id — a missing entry raises (loud)."""
    batch: list[dict] = []
    in_flight: set[str] = {str(t) for t in (tool_load or {})}
    serial_in_batch = False
    for task in ranked:
        if len(batch) >= free_slots:
            break
        tid = str(task.get("task_id"))
        if deps.get(tid):
            continue
        tools = {str(x) for x in task.get("tools") or []}
        if tools & in_flight:
            continue
        tier = int(tiers[tid])
        if tier >= SERIAL_TIER and serial_in_batch:
            continue
        batch.append(task)
        in_flight |= tools
        serial_in_batch = serial_in_batch or tier >= SERIAL_TIER
    return batch


# ------------------------------------------------------- wiring face

def family_value(family: str, table: dict) -> float:
    """Best (mean_reward - mean_cost) over the value-table cells whose
    context features contain the family; no cell -> 0.0 (neutral)."""
    best: float | None = None
    for key, cell in table.items():
        if family not in key[0]:
            continue
        value = (float(cell.get("mean_reward") or 0.0)
                 - float(cell.get("mean_cost") or 0.0))
        best = value if best is None else max(best, value)
    return 0.0 if best is None else best


def order_task_dirs(dirs: list[Path], table: dict | None) -> list[Path]:
    """The tier's task dirs in pool-value order; a None/empty table (no
    pool data) returns the caller's order unchanged (a new list). Stable
    and deterministic: value descending, input order on ties."""
    if not table:
        return list(dirs)
    keyed = [(-family_value(d.name, table), i, d)
             for i, d in enumerate(dirs)]
    keyed.sort(key=lambda s: (s[0], s[1]))
    return [s[2] for s in keyed]
