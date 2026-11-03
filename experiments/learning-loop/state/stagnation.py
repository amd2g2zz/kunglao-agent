# -*- coding: utf-8 -*-
"""state/stagnation.py — the stagnation trigger face (#898).

N consecutive rollout segments with ``|ΔP|`` below a documented floor
mean the current direction is mining nothing: this face emits a
``stagnation-advice/1`` receipt advising re-planning (down-weight the
current direction, widen the assigner candidate set). The receipt is
ADVISORY ONLY, pinned as data: it carries ``terminates: False`` and no
terminator action kind — the β terminator (policy/terminator.py) is the
only face that ends a rollout, and this face never touches posteriors
(it is a pure function; recording the receipt is the caller's standard
single-writer path). It fires BEFORE the loss-cut (STAGNATION_N <
terminator.LOSS_CUT_N — the advice leads the cut by one segment) so the
re-plan lands pre-death, not post-mortem.

Both constants are documented policy, NOT fitted (the same governance
class as terminator.LOSS_CUT_N / q_cells.SHRINK_CAP: changing one
follows the replay-evidence-plus-pins procedure):

- ``STAGNATION_FLOOR = 1e-6``: P is rounded to 6 decimals and every
  legal nonzero ladder move is ≥ 0.3, so the floor separates float
  noise from real moves exactly — any real move clears it.
- ``STAGNATION_N = 2``: two flat segments advise; the terminator's own
  loss-cut (3 empty steps) is the harder hammer behind it.

Idempotent by construction: the receipt is a pure function of the delta
tail (same inputs -> a byte-identical receipt) and carries no clock
field — never clock-derived, the #251 contract.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

SCHEMA = "stagnation-advice/1"

#: flat segments required before the advice fires (see module docstring)
STAGNATION_N = 2

#: |ΔP| below this is "flat" (see module docstring)
STAGNATION_FLOOR = 1e-6

#: the advice payload — the re-planning event's fixed shape (option-death
#: posture, pre-death): drop the current direction's weight, widen the
#: candidate set the assigner samples from.
ADVICE = {"action": "replan",
          "down_weight_current_direction": True,
          "widen_candidates": True}


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"state.stagnation.{field}: {why}")


def _checked_deltas(deltas: Any) -> list[float]:
    if deltas is None or isinstance(deltas, (str, bytes)) \
            or not isinstance(deltas, Sequence):
        raise _fail("deltas", "must be a sequence of finite numbers")
    out: list[float] = []
    for i, d in enumerate(deltas):
        if isinstance(d, bool) or not isinstance(d, (int, float)) \
                or not math.isfinite(d):
            raise _fail("deltas",
                        f"[{i}] must be a finite number, got {d!r}")
        out.append(float(d))
    return out


def flat_tail(deltas: Sequence[float]) -> int:
    """The length of the TRAILING run of flat segments (|ΔP| < floor).
    A real move anywhere after a flat run resets the streak."""
    values = _checked_deltas(deltas)
    n = 0
    for d in reversed(values):
        if abs(d) < STAGNATION_FLOOR:
            n += 1
        else:
            break
    return n


def stagnation_receipt(deltas: Sequence[float], *,
                       rollout_id: str) -> dict | None:
    """The trigger: the LAST STAGNATION_N deltas all flat -> the advice
    receipt; otherwise None. Pure and idempotent — no clock, no ledger
    write, no posterior mutation (the receipt is the whole deliverable;
    the β terminator keeps the terminate decision)."""
    tail = flat_tail(deltas)
    if not isinstance(rollout_id, str) or not rollout_id.strip():
        raise _fail("rollout_id", "must be a non-empty string")
    if tail < STAGNATION_N:
        return None
    return {
        "schema": SCHEMA,
        "rollout_id": rollout_id,
        "flat_segments": tail,
        "n": STAGNATION_N,
        "floor": STAGNATION_FLOOR,
        "advice": dict(ADVICE),
        "terminates": False,
    }
