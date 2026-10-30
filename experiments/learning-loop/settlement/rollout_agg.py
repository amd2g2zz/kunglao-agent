# -*- coding: utf-8 -*-
"""settlement/rollout_agg.py — the rollout's Σ + terminal aggregate.

Rollout settlement = Σ(per-dispatch credits) + the terminal adjustment:
completion banks +bonus, a rollback banks −bonus — the exact
``credit/returns.py`` TERMINALS vocabulary and terminal_bonus sign
semantics (the terminal step's return flips at the outcome; here the
FLIP is the batch's aggregate adjustment). The per-dispatch rows arrive
as data (the priced draft rows); the face is pure arithmetic over them
— no ledger read, no clock, no verification of its own.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from credit import returns  # noqa: E402 — the terminal vocabulary
from settlement import per_dispatch  # noqa: E402 — the draft schema stamp

#: the closed terminal vocabulary, MIRRORED from credit/returns.py (the
#: single source; re-exported so consumers read one vocabulary).
TERMINALS = returns.TERMINALS

#: the default outcome-bonus magnitude. A documented policy constant
#: (NOT fitted) — the caller's policy constant in returns.py; here the
#: magnitude doubles a fully-verified rollout on completion and zeroes
#: it on a rollback (the same magnitude as per_dispatch.PASS_CREDIT).
TERMINAL_BONUS = 1.0


def _fail(field: str, wall: str) -> ValueError:
    return ValueError(f"settlement.rollout_agg.{field}: {wall}")


def _checked_drafts(rows: Any) -> list[Mapping]:
    """The draft-row wall: only priced ``settlement-draft/1`` rows
    settle — a foreign schema in the batch is structural garbage (a
    silently folded foreign row would fabricate the aggregate)."""
    if not isinstance(rows, (list, tuple)):
        raise _fail("rows", "must be a list of draft rows")
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping) \
                or row.get("schema") != per_dispatch.DRAFT_SCHEMA:
            raise _fail("rows",
                        f"every row must be a {per_dispatch.DRAFT_SCHEMA!r} "
                        f"mapping, got {type(row).__name__}")
        for field in ("credit", "spend"):
            v = row.get(field)
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or v != v or v in (float("inf"), float("-inf")):
                raise _fail(
                    f"rows[{i}].{field}",
                    "must be a finite number (the aggregate would "
                    "fabricate or crash on this row)")
    if not rows:
        raise _fail("rows", "must be non-empty (an empty batch settles "
                            "nothing — credit the terminal to a real batch)")
    return list(rows)


def _checked_bonus(bonus: Any) -> float:
    if isinstance(bonus, bool) or not isinstance(bonus, (int, float)) \
            or not math.isfinite(bonus) or bonus < 0.0:
        raise _fail("terminal_bonus", "must be a finite number >= 0")
    return float(bonus)


def aggregate(rows: Sequence[Mapping], *, terminal: str,
              terminal_bonus: float = TERMINAL_BONUS) -> dict:
    """Σ(draft credits) + the terminal adjustment — pure. The bonus is
    + on ``completed``, − on ``rolled_back`` (the returns.py sign
    flip); the spend aggregates the rows' own figures. Never the clock,
    never the ledger — the caller supplies the rows."""
    safe = _checked_drafts(rows)
    if terminal not in TERMINALS:
        raise _fail("terminal",
                    f"terminal must be one of {TERMINALS}, got {terminal!r}")
    bonus = _checked_bonus(terminal_bonus)
    signed = bonus if terminal == "completed" else -bonus
    return {
        "dispatch_count": len(safe),
        "credits_sum": round(sum(float(r["credit"]) for r in safe), 6),
        "spend": round(sum(float(r["spend"]) for r in safe), 6),
        "terminal": terminal,
        "terminal_adjustment": round(signed, 6),
        "total_credit": round(sum(float(r["credit"]) for r in safe)
                              + signed, 6),
    }
