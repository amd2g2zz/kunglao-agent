# -*- coding: utf-8 -*-
"""rlvr/stopping.py — externally checkable stopping.

Only three conditions may terminate a rollout:

  - the route-attempt ledger's exhaustion (the ledger covers the declared
    routes, or the fixed budget is spent — ``rlvr.route_ledger``);
  - a session-bound AND corroborated environment wall (``rlvr.interruption``
    is the evidence owner; the caller hands over the corroborated face);
  - the declared budget spent (``spent >= limit`` with a positive limit).

Surrogate early-stop signals are BANNED: a stagnation count, an
early-failure prediction, or an effort heuristic is not evidence, and
within-task early-failure prediction is near chance. Their presence in a
record changes nothing — ``may_terminate`` never reads them. Unknown keys
are ignored, and a malformed record fails closed (no evidence, no stop).

The checker is PURE (no I/O, no clock, no model call). Callers assemble
``{"ledger": ..., "wall": ..., "budget": {...}}`` from their own
workspace faces; ``stop_reasons`` reports which external legs paid (the
audit face — the disposition vocabulary is the classifier's, not this
module's).

Call-site contract (the one loop-facing stop in ``scripts/e2e/
checkpoints.py``): ``_tick_prelude`` refuses the heartbeat idle circuit
breaker (a stagnation surrogate) unless ``may_terminate`` returns True
for the assembled evidence; a refusal is recorded (``stop_refused``) and
the tick proceeds. The declared budget and the tick cap remain the hard
bounds.
"""
from __future__ import annotations

import math

from .disposition import _ledger_exhausted, _wall_corroborated

#: the surrogate signals that must NEVER terminate a rollout (the record
#: may carry them; ``may_terminate`` ignores every one of them)
SURROGATE_SIGNALS = (
    "stagnation",
    "early_failure",
    "effort",
    "idle",
    "stall",
)

#: the external evidence legs, in reporting order
EXTERNAL_EVIDENCE = ("ledger", "wall", "budget")


def _is_real_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _budget_spent(budget) -> bool:
    """True only for a positive declared limit actually reached."""
    if not isinstance(budget, dict):
        return False
    spent = budget.get("spent")
    limit = budget.get("limit")
    if not (_is_real_number(spent) and _is_real_number(limit)):
        return False
    return limit > 0 and spent >= limit


def stop_reasons(record) -> tuple[str, ...]:
    """Which externally checkable legs the record carries (empty = none)."""
    if not isinstance(record, dict):
        return ()
    reasons: list[str] = []
    if _ledger_exhausted(record.get("ledger")):
        reasons.append("ledger")
    if _wall_corroborated(record.get("wall")):
        reasons.append("wall")
    if _budget_spent(record.get("budget")):
        reasons.append("budget")
    return tuple(reasons)


def may_terminate(record) -> bool:
    """True iff an externally checkable stop condition is satisfied.

    Pure and fail-closed: a malformed/empty record is False, and surrogate
    keys (``SURROGATE_SIGNALS``) never count, alone or combined.
    """
    return bool(stop_reasons(record))
