#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_check_gate.py - PreToolUse hard-REJECT while the AGENT_TEAMS flag is TRUTHY (#233/#276).

2026-08-12 incident: the session ran with CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1.
Every Agent dispatch routed through the teammate channel and died (400 [1210]
cascade); 19 facts were self-stamped because no independent worker ever ran.
scripts/env_check.py catches the flag at Phase 0, but a polluted session can
skip Phase 0 entirely — this hook is the mechanical backstop that fires ON the
Agent tool itself, at the exact point a worker would be dispatched.

#276 (defaults to 0): only TRUTHY values (1/true/yes/on, case-insensitive)
trigger the hard REJECT; 0/false/off/empty are the clean default state and pass
through silently — matching scripts/env_check.py check_flag semantics.

Design (mirrors dispatch_gate.py, narrow + low-IO):
  - FLAG check: ZERO IO — reads os.environ directly. No state file, no
    .hook_state.json activation check — a teammate-polluted session must not
    dispatch even during the activation TTL, and the env lookup is the one
    check that cannot be forgotten.
  - #304 INIT-completeness check: reads TWO workspace state files per dispatch
    in kunglao workspaces — claim-register.yaml ([initialized] marker) +
    analysis_state.txt (project_type=). The predicate lives in
    scripts/init_state.py (single source of truth, shared with
    scripts/env_check.py and scripts/kunglao-init.py; #304 review F6).
  - This hook ALWAYS fires on the Agent tool while the flag is TRUTHY (in a
    kunglao workspace); it sleeps (exit 0) as soon as the flag is clean or
    gone — but the init-completeness check still runs in kunglao workspaces.
  - Workspace resolution mirrors dispatch_gate._resolve_workspace: only
    kunglao-agent workspaces (claim-register.yaml present) are policed, so the
    hook (wired in the PROJECT-level .claude/settings.json by
    hook_activation.py --wire-up, the canonical registration entry #445)
    stays silent in unrelated projects.
  - flag TRUTHY -> hard REJECT (exit 2 + stderr) + hookSpecificOutput.additionalContext
    guidance: problem / alternative / fix. The additionalContext structure
    mirrors dispatch_gate.py:137-142.

Wiring (in .claude/settings.json PreToolUse, Agent matcher — registered by
scripts/hook_activation.py --wire-up, #445):
  {"matcher": "Agent", "hooks": [{"type": "command",
    "command": "uv run --project <skill_root> <skill_root>/hooks/env_check_gate.py"}]}
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from _path_hygiene import ensure_scripts_path, scripts_on_path  # #671 authority

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
# F6 (#304 review): shared init-completeness predicate lives in scripts/init_state.py.
# #671: module-level membership via the hygiene authority — idempotent,
# position-stable (an existing session entry is never reordered).
ensure_scripts_path()
import init_state  # noqa: E402
FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
TRUTHY_VALUES = ("1", "true", "yes", "on")  # #276: only truthy rejects; 0/false/empty pass
# #757: freshness window for the .env-check.json third check (must mirror the
# producer, scripts/env_check.py GATE_REPORT_TTL_SECONDS).
ENV_CHECK_TTL_SECONDS = 600


def _is_truthy(value: str | None) -> bool:
    """Truthy check: 1/true/yes/on, case-insensitive (#276 default-off semantics)."""
    return value is not None and value.strip().lower() in TRUTHY_VALUES


def _check_init_complete(ws: Path) -> tuple[bool, str]:
    """#304: Check init completeness (marker + project_type declared).

    F6 (#304 review): the predicate itself lives in scripts/init_state.py
    (single source of truth, shared with env_check.py + kunglao-init.py).
    This wrapper only composes the hook-channel guidance.
    Returns (is_complete, guidance_or_empty).
    """
    ok, detail = init_state.init_complete(ws)
    if ok:
        return True, ""
    return False, (
        f"{detail}. Run: uv run --project {SKILL_DIR} {SKILL_DIR}/scripts/kunglao-init.py {ws} "
        f"--type <windows|linux|android|web|macos>"
    )


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
        f"env_check_gate: {FLAG_NAME} is set (value={flag_val!r}) - this "
        f"Agent dispatch is REJECTED (hard block, kunglao #88/#233).\n"
        f"Problem: flag on -> subagents route through the teammate channel "
        f"(2026-08-12 incident: 400 [1210] everywhere, 19 facts self-stamped). "
        f"kunglao #88 forbids the flag: REMOVED, SHALL NOT be re-enabled "
        f"(cold-start-contract.md Phase 0).\n"
        f"Alternative: dispatch an independent worker via the Agent tool; do not enter the teammate channel.\n"
        f"Fix: unset {FLAG_NAME} in the launching shell, then RESTART the "
        f"session; re-run uv run --project {SKILL_DIR} {SKILL_DIR}/scripts/env_check.py {ws} and "
        f"get OVERALL=PASS before any further dispatch."
    )


def _fresh_blocking_fails(ws: Path) -> list[str]:
    """#757: names of BLOCKING checks that FAILed in a FRESH env-check report.

    reads <ws>/runs/.env-check.json and returns [] on every fail-open path —
    the gate must never become the new dispatch deadlock source:
      - file absent / corrupt / unparsable          -> []
      - ts missing / unparseable / stale (> TTL s)  -> []
      - legacy (pre-#757) rows without `blocking`   -> ignored (a VM-unreachable
        legacy report must not resurrect as a hard gate)
    Only rows with status FAIL AND blocking is True count.
    """
    path = ws / "runs" / ".env-check.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        dt = datetime.fromisoformat(
            str(data.get("ts", "")).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:  # noqa: BLE001 — every read failure fails open
        return []
    if age < 0 or age > ENV_CHECK_TTL_SECONDS:
        return []
    failing: list[str] = []
    for name, row in (data.get("checks") or {}).items():
        if (isinstance(row, dict) and row.get("status") == "FAIL"
                and row.get("blocking") is True):
            failing.append(str(name))
    return sorted(failing)


def evaluate(payload: dict, environ: dict | None = None) -> tuple[int, str, str | None]:
    """Hook decision for a PreToolUse(Agent) payload.

    Returns (exit_code, stderr_text, additional_context_or_None):
      - (0, "", None)      -- not a kunglao workspace, or all checks pass
        (0/false/off/empty = default disabled, #276): silent
      - (2, stderr, ctx)   -- flag TRUTHY: hard REJECT with guidance
      - (2, stderr, ctx)   -- init incomplete: hard REJECT with guidance (#304)
    environ defaults to os.environ (zero-IO direct lookup; injectable for tests).
    """
    environ = os.environ if environ is None else environ
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0, "", None

    # Check 1: agent-teams flag (existing check, unchanged)
    flag_val = environ.get(FLAG_NAME)
    if _is_truthy(flag_val):
        _emit_reject(ws, f"env_check_gate: {FLAG_NAME} set ({flag_val}) — teammate-polluted session")
        return (
            2,
            f"REJECT env_check_gate: {FLAG_NAME} set ({flag_val}) -- teammate-polluted "
            f"session (kunglao #88). Fix: unset {FLAG_NAME} + restart the session.",
            _guidance(ws, flag_val),
        )

    # Check 2: #304 init completeness (marker + project_type)
    init_ok, init_guidance = _check_init_complete(ws)
    if not init_ok:
        _emit_reject(ws, f"env_check_gate: workspace not fully initialized. {init_guidance}")
        return (
            2,
            f"REJECT env_check_gate: workspace not fully initialized. {init_guidance}",
            f"env_check_gate: {init_guidance}",
        )

    # Check 3 (#757): fresh .env-check.json with a BLOCKING FAIL -> REJECT.
    # Degraded (T3-restricted) FAILs and stale/absent/corrupt/legacy reports
    # all pass through — fail-open; Phase 0 rerun is the remedy path.
    blocking_fails = _fresh_blocking_fails(ws)
    if blocking_fails:
        names = ", ".join(blocking_fails)
        rerun = (f"uv run --project {SKILL_DIR} {SKILL_DIR}/scripts/env_check.py "
                 f"{ws}")
        guidance = (
            f"env_check_gate: the workspace's FRESH env-check report "
            f"({names}) carries a BLOCKING FAIL — dispatch rejected.\n"
            f"Fix: re-run `{rerun}`, clear the failing row(s), then dispatch. "
            f"A report older than 10 minutes, an absent/corrupt one, or rows "
            f"marked 'T3-restricted' do NOT block — enter flagged instead."
        )
        _emit_reject(ws, f"env_check_gate: fresh env-check blocking FAIL ({names})")
        return (
            2,
            f"REJECT env_check_gate: fresh env-check blocking FAIL ({names}). "
            f"Fix: re-run scripts/env_check.py and clear it.",
            guidance,
        )

    return 0, "", None


def _emit_reject(ws: Path, detail: str) -> None:
    """#624: REJECTs leave a persistent trail in the kunglao_log event stream
    (dispatch_gate/_emit_trace precedent). Fail-open: observability never
    changes the hook verdict."""
    try:
        with scripts_on_path():  # #671 scoped membership
            import kunglao_log  # noqa: E402
            kunglao_log.emit(ws, "env_check_gate", "reject", exit=2, detail=detail)
    except Exception:
        pass


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
