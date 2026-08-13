#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_check_gate.py - PreToolUse hard-REJECT while the AGENT_TEAMS flag is TRUTHY (#233/#276).

2026-08-12 incident: the session ran with CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1.
Every Agent dispatch routed through the teammate channel and died (400 [1210]
cascade); 19 facts were self-stamped because no independent worker ever ran.
scripts/env_check.py catches the flag at Phase 0, but a polluted session can
skip Phase 0 entirely — this hook is the mechanical backstop that fires ON the
Agent tool itself, at the exact point a worker would be dispatched.

#276 (default 0 化): only TRUTHY values (1/true/yes/on, case-insensitive)
trigger the hard REJECT; 0/false/off/empty are the clean default state and pass
through silently — matching scripts/env_check.py check_flag semantics.

Design (mirrors dispatch_gate.py, narrow + zero-IO):
  - ZERO IO by design: reads os.environ directly. No state file, no
    .hook_state.json activation check — a teammate-polluted session must not
    dispatch even during the activation TTL, and the env lookup is the one
    check that cannot be forgotten. This hook ALWAYS fires on the Agent tool
    while the flag is TRUTHY (in a kunglao workspace); it sleeps (exit 0) as
    soon as the flag is clean or gone.
  - Workspace resolution mirrors dispatch_gate._resolve_workspace: only
    kunglao-agent workspaces (claim-register.yaml present) are policed, so the
    hook (wired in the GLOBAL settings.json via wire_up_settings.py) stays
    silent in unrelated projects.
  - flag TRUTHY -> hard REJECT (exit 2 + stderr) + hookSpecificOutput.additionalContext
    guidance: problem / alternative / fix. The additionalContext structure
    mirrors dispatch_gate.py:137-142.

Wiring (in ~/.claude/settings.json PreToolUse, Agent matcher — registered by
scripts/wire_up_settings.py):
  {"matcher": "Agent", "hooks": [{"type": "command",
    "command": "python <skill_root>/hooks/env_check_gate.py"}]}
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
TRUTHY_VALUES = ("1", "true", "yes", "on")  # #276: only truthy rejects; 0/false/空 pass


def _is_truthy(value: str | None) -> bool:
    """Truthy 判定: 1/true/yes/on, 不区分大小写 (#276 默认 0 化语义)."""
    return value is not None and value.strip().lower() in TRUTHY_VALUES


def _resolve_workspace(payload: dict) -> Path | None:
    """Same resolution as dispatch_gate.py: cwd -> malware-analysis-workspace."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / "claim-register.yaml").exists():
            return base
    return None


def _guidance(ws: Path, flag_val: str) -> str:
    """additionalContext injected into the model when the dispatch is rejected.

    Three points (issue #233): the problem (flag on -> teammate channel),
    the alternative (dispatch an independent worker), the fix (unset + restart).
    """
    return (
        f"env_check_gate: {FLAG_NAME} is set (value={flag_val!r}) — this "
        f"Agent dispatch is REJECTED (hard block, kunglao #88/#233).\n"
        f"Problem: flag on -> subagents route through the teammate channel "
        f"(2026-08-12 incident: 400 [1210] everywhere, 19 facts self-stamped). "
        f"kunglao #88 forbids the flag: REMOVED, SHALL NOT be re-enabled "
        f"(cold-start-contract.md Phase 0).\n"
        f"Alternative: 用 Task 工具派发独立 worker,不进入 teammate 通道.\n"
        f"Fix: unset {FLAG_NAME} in the launching shell, then RESTART the "
        f"session; re-run python {SKILL_DIR}/scripts/env_check.py {ws} and "
        f"get OVERALL=PASS before any further dispatch."
    )


def evaluate(payload: dict, environ: dict | None = None) -> tuple[int, str, str | None]:
    """Hook decision for a PreToolUse(Agent) payload.

    Returns (exit_code, stderr_text, additional_context_or_None):
      - (0, "", None)      — not a kunglao workspace, or flag not TRUTHY
        (0/false/off/empty = default disabled, #276): silent
      - (2, stderr, ctx)   — flag TRUTHY: hard REJECT with guidance
    environ defaults to os.environ (zero-IO direct lookup; injectable for tests).
    """
    environ = os.environ if environ is None else environ
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0, "", None
    flag_val = environ.get(FLAG_NAME)
    if not _is_truthy(flag_val):
        return 0, "", None
    return (
        2,
        f"REJECT env_check_gate: {FLAG_NAME} set ({flag_val}) — teammate-polluted "
        f"session (kunglao #88). Fix: unset {FLAG_NAME} + restart the session.",
        _guidance(ws, flag_val),
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    rc, stderr_text, context = evaluate(payload)
    if stderr_text:
        print(stderr_text, file=sys.stderr)
    if context:
        # mirror dispatch_gate.py:137-151 — additionalContext feeds the model
        # the corrective path even though the tool call is blocked
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": context,
            }
        }, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
