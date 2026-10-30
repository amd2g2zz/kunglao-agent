# -*- coding: utf-8 -*-
"""hooks/budget_tracker.py — continuous budget visibility (#885).

The BATS-style construction face: the worker's spend is visible
CONTINUOUSLY instead of being intercepted at the moment it overspends.
The tracker reads the ledger's own RESULT rows (the ``q-cell-result/1``
``cost`` columns — the single (s,a,r) substrate, no parallel tally,
the #879 charter) and reports spent vs the Budget envelope: remaining
wall, remaining calls, utilization, and the over flags. Observation
only — nothing here blocks, gates or settles; the report is a receipt
the caller (the loop, the brief face, analysis) reads.

Pure and deterministic: (Budget, trajectory rows) -> receipt; no
clock, no seeds — the numbers are the ledger's numbers (逐句可归因:
every figure traces to named result rows). Fail-closed at the row
boundary (the terminator's posture): structural garbage in the rows
or the envelope raises, because a silently tolerated malformed cost
would fabricate a spend figure.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_HERE = Path(__file__).resolve().parent.parent          # learning-loop/
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from _common import seq_sum as _seq_sum  # noqa: E402 — the canonical leaf
from core import Budget  # noqa: E402
from rlvr import q_cells  # noqa: E402

#: the receipt stamp — every report names its schema (the audit face)
SCHEMA = "budget-report/1"

#: the row wall: the tracker's evidence base is the trajectory stream;
#: rows of other schemas are structural garbage (never half-read).
_ROW_SCHEMAS = frozenset({q_cells.OBS_SCHEMA, q_cells.SCHEMA_ACTION_V2,
                          q_cells.SCHEMA_RESULT_V2})


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"budget_tracker.{field}: {why}")


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty trajectory-row field")
    return value


def _real(value: Any, field: str, *, minimum: float, exclusive: bool = False
          ) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) \
            or (value <= minimum if exclusive else value < minimum):
        bound = f"> {minimum}" if exclusive else f">= {minimum}"
        raise _fail(field, f"must be a finite number {bound}")
    return float(value)


def _envelope(budget: Any) -> Budget:
    """The spend envelope — a real core.Budget (positive finite wall:
    a zero envelope cannot report utilization) with an optional call
    cap."""
    if not isinstance(budget, Budget):
        raise _fail("budget", "must be a core.Budget value object")
    _real(budget.wall_s, "budget.wall_s", minimum=0.0, exclusive=True)
    mc = budget.max_calls
    if mc is not None and (isinstance(mc, bool) or not isinstance(mc, int)
                           or mc < 1):
        raise _fail("budget.max_calls", "must be None or an integer >= 1")
    return budget


def _rows_wall(rows: Any) -> list[dict]:
    """The fail-closed row boundary — mirrors the terminator's wall: a
    list of mappings whose schema is one of the three q-cell
    trajectory kinds."""
    if not isinstance(rows, (list, tuple)):
        raise _fail("rows", "must be a list of ledger rows")
    for row in rows:
        if not isinstance(row, Mapping):
            raise _fail("rows", "every row must be a mapping")
        schema = row.get("schema")
        if schema not in _ROW_SCHEMAS:
            raise _fail("rows",
                        f"{schema!r} outside the q-cell trajectory "
                        f"schemas {sorted(_ROW_SCHEMAS)}")
    return list(rows)


def budget_report(budget: Any, rows: Sequence[Mapping], *,
                  rollout_id: str | None = None) -> dict:
    """The BATS visibility receipt: spent vs envelope from the ledger's
    result-row ``cost`` columns. ``rollout_id`` scopes the report to
    one rollout; None pools the whole workspace. Remaining wall floors
    at 0.0 (the over-budget truth rides ``over_budget``, never a
    negative-remaining fabrication)."""
    bud = _envelope(budget)
    wall = float(bud.wall_s)
    mc = bud.max_calls
    rid = None if rollout_id is None else _non_empty(rollout_id,
                                                     "rollout_id")
    safe = _rows_wall(rows)
    costs: list[float] = []
    for row in safe:
        if row.get("schema") != q_cells.SCHEMA_RESULT_V2:
            continue
        if rid is not None and str(row.get("rollout_id") or "") != rid:
            continue
        cost = row.get("cost")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) \
                or not math.isfinite(cost) or cost < 0.0:
            raise _fail("cost",
                        "result-row cost must be a finite number >= 0")
        costs.append(float(cost))
    spent = round(_seq_sum(costs), 6)
    calls = len(costs)
    remaining_calls = None if mc is None else max(mc - calls, 0)
    return {
        "schema": SCHEMA,
        "rollout_id": rid,
        "wall_s": wall,
        "max_calls": mc,
        "calls_used": calls,
        "spent_s": spent,
        "remaining_s": round(max(wall - spent, 0.0), 6),
        "utilization": round(spent / wall, 6),
        "over_budget": spent > wall,
        "remaining_calls": remaining_calls,
        "over_calls": bool(mc is not None and calls > mc),
    }
