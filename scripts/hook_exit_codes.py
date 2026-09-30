# -*- coding: utf-8 -*-
"""hook_exit_codes.py — shared exit-code definitions for all hooks.

Mirrors the status_defs.py pattern: single source of truth for exit codes.
Claude Code reads hooks as exit(0)=allow vs non-zero=block (for Stop hooks
the block itself is carried by the stdout JSON `{"decision": "block",
"reason": ...}`); this module documents the SEMANTIC meaning per hook so
downstream consumers can distinguish BLOCKED-by-pulse from REJECT-by-budget
— the semantic distinction is for LOGS and debugging, never a wire
contract, and no emitted code may drift from the values pinned here.

Usage in hooks:
    from hook_exit_codes import ExitCode
    return ExitCode.OK.value            # 0 — allow
    return ExitCode.REJECT.value        # 2 — block (budget constraint)
    return ExitCode.BLOCKED.value       # 3 — block (stuck worker, but logged differently)

Note: Claude Code only reads 0 vs non-zero for allow/block decisions.
The semantic distinction between REJECT(2) and BLOCKED(3) is for LOGS
and debugging — both block the tool call. #472: exit 1 is dual-natured
BY DESIGN — a crash for some hooks, a documented deliberate block for
others (workguard_gate, completion_gate's second-stop refusal) — the
per-hook rows below carry the precise meaning; the enum comment points
there instead of claiming one nature.
"""
from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0                  # allow / pass / not-applicable
    REJECT = 2              # constraint violation (worker_budget: too many workers, tier gate)
    BLOCKED = 3             # operational block (worker_pulse: stuck worker)
    GENERAL_ERROR = 1       # unexpected error (hook crashed, malformed input) — OR a
                            # documented deliberate block for the hooks whose per-hook
                            # row below says so (workguard_gate, completion_gate)
    # #472: the completion-gate vocabulary joins the registry (values
    # mirror hooks/completion_gate.py's constants and scripts/
    # completion_gate.py's judge table — the registry is the single
    # source of truth, the shim derives from these members).
    INTENT_UNMATCHED = 4    # completion_gate judge: task_text anchor absent from PQs (#664)
    NOTES_DUE = 5           # completion_gate shim: owed durable-result notes (#762 K1b)
    NOTES_FAKE = 6          # completion_gate shim: notes fail structural discrimination (#834)
    SUMMARY_FAKE = 7        # completion_gate shim: summary evaporates uncertainty (#826)


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
    "recall_inject": {
        ExitCode.OK: "recall processed — knowledge injected or silent (inject-only, never rejects)",
    },
    "completion_gate": {
        # judge() face (scripts/completion_gate.py; precedence 3>2>1>4>0)
        ExitCode.OK: "PASS — task_text present, zero unresolved items, zero unsigned defers; let the session end",
        ExitCode.GENERAL_ERROR: "incomplete items remaining (judge) — deliberate fail-closed block, NOT a crash; OR the shim's second-stop refusal: stop_hook_active with no sanctioned-PASS record (#147/#199)",
        ExitCode.REJECT: "unsigned defer — the #54 self-defer denied by mechanical deny-list",
        ExitCode.BLOCKED: "fail-closed integrity refusal — no task-oracle on an activated workspace, unparseable oracle YAML (#717), or judge crash (2026-09-28 owner ruling)",
        ExitCode.INTENT_UNMATCHED: "≥1 task_text anchor absent from primary_questions at the would-be-PASS point (#664)",
        # shim-only faces (hooks/completion_gate.py, after judge PASS)
        ExitCode.NOTES_DUE: "owed durable-result notes remain (#628/#762 K1b) — write notes/<claim-id>.md to clear",
        ExitCode.NOTES_FAKE: "notes fail structural discrimination (#834) — copied fact bodies or dangling fact-ids",
        ExitCode.SUMMARY_FAKE: "summary evaporates uncertainty (#826) — no provisional section / unconveyed facts",
    },
    "workguard_gate": {
        ExitCode.OK: "turn exit allowed — actionable set empty (legal sleep) or pass-through face",
        ExitCode.GENERAL_ERROR: "turn exit BLOCKED — actionable set non-empty; reason carries the next-decision guidance (issue 434 WORKGUARD). Deliberate block, NOT a crash",
    },
    "round_closure": {
        ExitCode.OK: "closure event row appended (or pass-through; recorder, never blocks)",
    },
    "session_start": {
        ExitCode.OK: "armed + renewed + constitution injected (or non-workspace notice; never blocks a session)",
    },
    "compact_continuity": {
        ExitCode.OK: "continuity note injected (inject-only, never blocks compaction)",
    },
    "user_signal_capture": {
        ExitCode.OK: "operator observation recorded + signal routed (fail-open, never blocks user input)",
    },
}
