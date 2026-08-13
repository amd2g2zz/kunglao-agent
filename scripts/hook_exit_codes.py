# -*- coding: utf-8 -*-
"""hook_exit_codes.py — shared exit-code definitions for all hooks.

Mirrors the status_defs.py pattern: single source of truth for exit codes.
Claude Code constrains hooks to exit(0)=allow, exit(2)=block; this module
documents the SEMANTIC meaning per hook so downstream consumers can
distinguish BLOCKED-by-pulse from REJECT-by-budget.

Usage in hooks:
    from hook_exit_codes import ExitCode
    return ExitCode.OK.value            # 0 — allow
    return ExitCode.REJECT.value        # 2 — block (budget constraint)
    return ExitCode.BLOCKED.value       # 3 — block (stuck worker, but logged differently)

Note: Claude Code only reads 0 vs non-zero for allow/block decisions.
The semantic distinction between REJECT(2) and BLOCKED(3) is for LOGS
and debugging — both block the tool call.
"""
from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0                  # allow / pass / not-applicable
    REJECT = 2              # constraint violation (worker_budget: too many workers, tier gate)
    BLOCKED = 3             # operational block (worker_pulse: stuck worker)
    GENERAL_ERROR = 1       # unexpected error (hook crashed, malformed input)


HOOK_EXIT_SEMANTICS = {
    "worker_budget": {
        ExitCode.OK: "dispatch allowed",
        ExitCode.REJECT: "dispatch rejected — constraint violation (≤3 workers / tier gate / deadline)",
    },
    "worker_pulse": {
        ExitCode.OK: "pulse processed, no action needed",
        ExitCode.BLOCKED: "worker stuck > STUCK_MINUTES — orchestrator intervention required",
    },
    "state_anchor": {
        ExitCode.OK: "state checkpoint recorded",
        ExitCode.GENERAL_ERROR: "checkpoint failed — state loss risk",
    },
    "dispatch_gate": {
        ExitCode.OK: "dispatch gate passed",
        ExitCode.REJECT: "dispatch gate failed — missing prerequisite",
    },
    "env_check_gate": {
        ExitCode.OK: "flag not set — dispatch allowed",
        ExitCode.REJECT: "dispatch rejected — CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS set (#88/#233): teammate-polluted session",
    },
}
