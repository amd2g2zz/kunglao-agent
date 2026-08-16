# -*- coding: utf-8 -*-
"""tool_error_policy.py — same-tool consecutive-error hysteresis (issue #309).

Absorbed idea: Rikugan loop.py:794-820 (same tool failing repeatedly gets
prompted then disabled), re-implemented as a pure mechanical policy for the
kunglao worker contract:
    streak <  3  -> ok
    3 <= streak < 5  -> warn (prompt the worker)
    streak >= 5  -> disable_escalate: disable the tool for this claim and
                    escalate, recording blocker attribution (claim + tool +
                    streak) so the failure analysis can attribute it.

The worker-contract wiring (hooks/worker_budget.py enforcement) is a
separate change; this module is the single sanctioned policy source.
"""
from __future__ import annotations

WARN_THRESHOLD = 3
DISABLE_THRESHOLD = 5


def evaluate_streak(streak: int, tool: str = "tool") -> dict:
    """Pure policy decision for a consecutive-error streak of one tool."""
    streak = max(0, int(streak))
    if streak < WARN_THRESHOLD:
        return {"action": "ok", "streak": streak,
                "message": f"{tool}: {streak} consecutive error(s) — no action"}
    if streak < DISABLE_THRESHOLD:
        return {"action": "warn", "streak": streak,
                "message": f"{tool}: {streak} consecutive errors — prompt worker "
                           f"to switch approach"}
    return {"action": "disable_escalate", "streak": streak,
            "message": f"{tool}: {streak} consecutive errors — tool disabled "
                       f"and escalated",
            "blocker_note": f"tool {tool} disabled after {streak} consecutive "
                            f"errors; escalate for blocker attribution"}


def apply_policy(tool: str, streak: int, claim_id: str | None = None) -> dict:
    """Evaluate the policy and embed claim attribution in the blocker note."""
    r = evaluate_streak(streak, tool=tool)
    if r["action"] == "disable_escalate":
        note = f"tool {tool} disabled after {r['streak']} consecutive errors"
        if claim_id:
            note += f" on claim {claim_id}"
        note += "; escalate for blocker attribution"
        r["blocker_note"] = note
    return r
