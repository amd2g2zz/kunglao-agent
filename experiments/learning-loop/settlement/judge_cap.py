# -*- coding: utf-8 -*-
"""settlement/judge_cap.py — the judge injection's cumulative cap
(card 933).

The judge's per-step delta is bounded at the seam, but BOUNDED STEPS
COMPOUND: an unbounded SUM of small modulations is the battery's
inflation lesson (raw injection 9.0 over a mechanical terminal of 6.0 —
a judge-pleasing trajectory pricing above every honest climb). The cap
is the load-bearing wall: per trajectory, the judge's total injected
credit may not exceed epsilon of the MECHANICAL terminal reward.

Integration point: the cap binds to the COMMIT marker's certified
aggregate — ``draft_commit.committed_rollout`` re-reads the landed
drafts (the settled source of truth) and raises on a rollout without
its commit marker, so the ceiling is always epsilon of a CERTIFIED
mechanical total, never a caller-supplied figure. This face is a
read-only composition over the settlement faces: no pinned row shape
changes, no landed row is rewritten — the #884 settlement pins stay
byte-unchanged.

``JUDGE_CAP_EPSILON`` is a RECORDED PARAMETER (the battery's 10% arm;
the 5% arm also held) — documented policy, NOT fitted. The capped
injection caps a judge that argues a trajectory DOWN by magnitude too.
On a non-positive certified base the ceiling is ZERO — a negative
judge delta is zeroed there (nothing to modulate), not sign-kept;
that collapse is pinned, not incidental.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (Path(__file__).resolve().parents[1], _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from settlement import draft_commit  # noqa: E402 — the certified read
from state import judge  # noqa: E402 — the injection read

#: the recorded cap parameter: judge-injected total per trajectory
#: <= epsilon of the mechanical terminal reward (the battery's 10%
#: arm; the 5% arm held as well).
JUDGE_CAP_EPSILON = 0.10


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"settlement.judge_cap.{field}: {why}")


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise _fail(field, "must be a finite number")
    return float(value)


def _checked_epsilon(epsilon: Any) -> float:
    eps = _finite(epsilon, "epsilon")
    if not 0.0 <= eps <= 1.0:
        raise _fail("epsilon",
                    f"must lie in [0, 1] (a share of the mechanical "
                    f"total), got {eps}")
    return eps


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def capped_injection(judge_total: Any, mechanical_total: Any, *,
                     epsilon: Any = JUDGE_CAP_EPSILON) -> float:
    """The cap as pure arithmetic: ``clamp(judge_total,
    -eps x max(mechanical, 0), +eps x max(mechanical, 0))`` — sign
    preserved, magnitude bound by epsilon of the mechanical base. A
    zero mechanical base binds to zero: the judge can never mint from
    nothing."""
    total = _finite(judge_total, "judge_total")
    mechanical = _finite(mechanical_total, "mechanical_total")
    eps = _checked_epsilon(epsilon)
    ceiling = eps * max(mechanical, 0.0)
    return round(max(-ceiling, min(ceiling, total)), 6)


def trajectory_total(ws, rollout_id: str, *,
                     epsilon: Any = JUDGE_CAP_EPSILON) -> dict:
    """The trajectory's capped composition, through the REAL
    settlement path: the mechanical terminal is the commit marker's
    certified ``total_credit`` (an uncommitted or discarded rollout
    has nothing to bind to — the certified read raises); the raw
    injection is the judge rows' strict-parse sum; the return carries
    both figures so the capped-vs-uncapped delta stays auditable::

        {rollout_id, mechanical, judge_raw, judge_capped, epsilon,
         total}
    """
    rid = _non_empty(rollout_id, "rollout_id")
    eps = _checked_epsilon(epsilon)
    view = draft_commit.committed_rollout(ws, rid)
    if not view.get("committed"):
        raise _fail("rollout_id",
                    f"{rid!r} has no commit marker — the cap binds "
                    "only to a CERTIFIED mechanical total")
    mechanical = float(view["total_credit"])
    raw = judge.trajectory_delta(ws, rid)
    capped = capped_injection(raw, mechanical, epsilon=eps)
    return {"rollout_id": rid, "mechanical": mechanical,
            "judge_raw": raw, "judge_capped": capped, "epsilon": eps,
            "total": round(mechanical + capped, 6)}
