#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrator_tool_guard.py — PreToolUse/Bash WARN gate (#608).

The maker-checker separation lived only in workspace CLAUDE.md prose: the
Bash matcher carried nothing but heartbeat_touch (exit 0 forever), so the
ORCHESTRATOR ran jadx directly in production (~7 min of violation, zero
signal — issue #608 field report).

Adjudicated posture (v0.1.3 §三.3): TARGET-BASED arming (#532 write_guard
precedent — "nobody dispatched, so nothing was armed" applies to the
orchestrator's own shell too) + WARN, never block:
  - command matches an analysis-binary pattern AND
  - cwd is NOT inside a .wt-* worker worktree
→ exit 0 with additionalContext (the corrective guidance) + one durable
kunglao_log event. Workers inside .wt-* pass silently — they are the ones
SUPPOSED to run these tools.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Analysis binaries only the dispatched workers should invoke (worker_budget's
# VM_TOOLS covers the dynamic-analysis family on the Agent face; this list is
# the static/decompile face seen in the #608 incident).
ANALYSIS_BINARIES = re.compile(
    r"(?:^|[/\s;&|])(?:jadx|apktool|baksmali|ghidra|analyzeHeadless|"
    r"idat64|ida64|frida|strings3|diec|floss)(?:$|[\s;]|-[a-zA-Z])"
)

CTX = ("[kunglao #608 maker-checker] The ORCHESTRATOR does not analyze — "
       "decompile/strings/emulation belongs to a dispatched worker "
       "(dispatch_gate guards the Agent face; this Bash call bypassed it). "
       "Dispatch a worker for this claim instead. (WARN only — recorded in "
       "runs/logs/.)")


def _in_worker_worktree(cwd: str) -> bool:
    p = Path(cwd)
    return any(part.startswith(".wt-") for part in p.parts)


def evaluate(payload: dict) -> tuple[int, str, str | None]:
    """(rc, stderr, additionalContext). WARN posture: always rc 0."""
    cwd = payload.get("cwd") or ""
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if not cmd or not ANALYSIS_BINARIES.search(cmd):
        return 0, "", None
    if _in_worker_worktree(cwd):
        return 0, "", None
    # durable trail (fail-open — the WARN never depends on logging succeeding)
    try:
        if cwd:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
            import kunglao_log  # noqa: E402
            kunglao_log.emit(Path(cwd), "orchestrator", "orchestrator_tool_violation",
                             detail=f"bash analysis-binary outside worker worktree: "
                                    f"{cmd.split()[0] if cmd.split() else cmd}")
    except Exception:
        pass
    return 0, "", CTX


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0  # fail-open: a broken payload must never block Bash
    rc, err, ctx = evaluate(payload)
    if err:
        print(err, file=sys.stderr)
    if ctx:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": ctx}}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
