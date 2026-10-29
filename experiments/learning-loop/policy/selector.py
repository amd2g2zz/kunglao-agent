# -*- coding: utf-8 -*-
"""policy/selector.py — the DTS task selector, decision face 1 (#880).

Task selection is a SAMPLE, never a mean-argmax: each candidate task's
Beta posterior is derived from the unified ledger's TERMINAL rollout
returns (the (s,a,r) store is the only source — no parallel tally,
the #879 charter); one Thompson draw per candidate and the largest
draw takes the task. Cold tasks carry the wide Beta(1,1) and are
still sampled (exploration is the prior, not a bolt-on epsilon); a
task whose history banked successes concentrates its posterior and
dominates the draw (exploitation emerges from the sharpening, never
from a greedy rule — the greedy lock-in this face retires).

Pure: (ws, candidates, rng) -> receipt. The receipt carries every
candidate's (alpha, beta, theta, weight) — 逐句可归因, the
sample_method_family receipt discipline — plus the ``select_task``
action shape the unified decision protocol consumes. Recording is the
separate ``record_selection`` face (the standard single-writer
append); the selector itself writes nothing.

priority_ratio's argmax ordering is SUPERSEDED by this face; the
physical file removal is the #886 charter (483 live references — a
mid-program deletion would destabilize ten faces), so the scoping
note rides the #880 PR instead.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Sequence

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import q_cells  # noqa: E402 — the ledger faces

SCHEMA = "task-select/1"

#: the wide aggregate prior — cold tasks are sampled through the draw,
#: never a fabricated score.
BASE_ALPHA = 1.0
BASE_BETA = 1.0


def _validate_candidates(task_ids: Sequence) -> list[str]:
    ids: list[str] = []
    for t in task_ids:
        if not isinstance(t, str) or not t.strip():
            raise ValueError(
                "policy.selector: candidate tasks must be non-empty "
                f"string tokens, got {t!r}")
        ids.append(t)
    if not ids:
        raise ValueError(
            "policy.selector: the candidate task list is empty")
    if len(set(ids)) != len(ids):
        raise ValueError(
            "policy.selector: duplicate candidate task "
            "(a duplicate would double-weight its posterior)")
    return ids


def task_posteriors(ws, task_ids: Sequence) -> dict[str, tuple[float, float]]:
    """Per-task ``(alpha, beta)`` accumulated from the ledger.

    ONE scan of ``trajectory_rows``: select_task action rows join
    rollout_id -> task target; result rows keep each rollout's LAST
    numeric ``r_t`` (its TERMINAL return — step mass never
    double-banks). Every terminal return of the task's rollouts
    accumulates into the Beta mass (r, 1-r) — ten rollouts are ten
    observations (the learning signal), while steps within one
    rollout collapse to their endpoint (one episode, one outcome). A
    pending rollout (no r_t yet) banks nothing; a task with no
    history stays the wide prior. Out-of-range returns project onto
    the [0, 1] rail (r < 0 banks full failure, r > 1 full success) —
    the projection is the documented mass semantics, never a
    fabricated value. One selection per rollout is the v1 contract:
    a second select_task row for the SAME rollout_id re-points the
    join (last-wins), so a mid-rollout re-selection would attribute
    the terminal to the new target.
    """
    ids = _validate_candidates(task_ids)
    target_of: dict[str, str] = {}
    terminal_of: dict[str, float] = {}
    for row in q_cells.trajectory_rows(ws):
        rid = str(row.get("rollout_id") or "")
        if not rid:
            continue
        if row.get("schema") == q_cells.SCHEMA_ACTION_V2 \
                and row.get("kind") == "select_task":
            tgt = str(row.get("target") or "")
            if tgt:
                target_of[rid] = tgt
            continue
        if row.get("schema") == q_cells.SCHEMA_RESULT_V2:
            r_t = row.get("r_t")
            if isinstance(r_t, (int, float)) \
                    and not isinstance(r_t, bool):
                terminal_of[rid] = float(r_t)   # append order: last wins
    success: dict[str, float] = {}
    failure: dict[str, float] = {}
    for rid, tgt in target_of.items():
        terminal = terminal_of.get(rid)
        if terminal is None:
            continue
        success[tgt] = success.get(tgt, 0.0) + max(terminal, 0.0)
        failure[tgt] = failure.get(tgt, 0.0) + max(1.0 - terminal, 0.0)
    return {tid: (BASE_ALPHA + success.get(tid, 0.0),
                  BASE_BETA + failure.get(tid, 0.0))
            for tid in ids}


def select_task(ws, task_ids: Sequence,
                rng: random.Random | None = None) -> dict:
    """DTS draw over the candidate tasks — ONE task leaves the face.

    Deterministic: ``rng=None`` anchors to Random(0); live callers
    thread a seed derived from ledger state (the evidence-sensitivity
    contract — the draw moves when the ledger moves). The fork order
    is the sorted candidate list (a reorder never reshuffles, the
    q_cells discipline)."""
    ids = _validate_candidates(task_ids)
    if rng is None:
        rng = random.Random(0)   # anchor-deterministic default
    base = rng.getrandbits(64)
    post = task_posteriors(ws, ids)
    order = sorted(ids)
    weights: dict[str, float] = {}
    cand_doc: dict[str, dict] = {}
    for tid in order:
        alpha, beta = post[tid]
        child = random.Random(f"task-select/{base}/{tid}")
        theta = child.betavariate(alpha, beta)
        weights[tid] = theta
        cand_doc[tid] = {"alpha": alpha, "beta": beta,
                         "theta": round(theta, 6)}
    # Thompson's own selection: the LARGEST SAMPLE takes the task —
    # the exploration lives in the posterior draws, never in a soft
    # (proportional) re-selection, which squashes the sharpened
    # posterior's advantage back toward uniform (the review-found
    # defect: proportional picking halved a Beta(11,1) arm's win
    # rate). The retired greedy was argmax over the posterior MEAN —
    # it never sampled at all; argmax over the sample IS the sampler.
    chosen = max(order, key=lambda t: weights[t])
    return {"schema": SCHEMA, "task": chosen, "candidates": cand_doc,
            "action": {"kind": "select_task", "target": chosen}}


def record_selection(ws, task: str, *, rollout_id: str,
                     policy_version: str | None = None,
                     params: dict | None = None) -> dict:
    """Land the selection as ONE ``q-cell-action/1`` row (kind =
    ``select_task``, target = the task) — the standard single-writer
    append; the trajectory's first row of every rollout."""
    return q_cells.append_action(ws, kind="select_task",
                                 rollout_id=rollout_id, target=task,
                                 policy_version=policy_version,
                                 params=params)
