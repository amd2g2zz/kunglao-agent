#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/workguard_gate.py — Stop-hook shim for the WORKGUARD (issue 434).

The Stop face was liveness-only; it is redefined as the WORKGUARD: on a
turn-exit attempt, compute the DAG actionable set (scripts/workguard.py —
the pure predicate) and

    non-empty -> BLOCK the exit + inject next-decision guidance
    empty     -> allow the exit (all PARKed/blocked/walled = LEGAL SLEEP)

Activation / posture (mirrors hooks/completion_gate.py):
  - no workspace markers            -> pass-through (nothing kunglao runs)
  - workspace resolved, not strict-active (no/expired .hook_state.json,
    gate absent from active_hooks)  -> pass-through (default-inactive)
  - stop_hook_active=true           -> pass-through — Claude Code's second
    stop face. The guard never blocks twice in a row (anti-deadlock by
    construction); the completion gate owns second-stop adjudication.
  - actionable set non-empty        -> print {"decision": "block",
    "reason": guidance}, exit 1, and record ONE guard_fired ledger row
    (no silent gate decisions)
  - legal sleep                     -> empty stdout, exit 0 (the pass IS
    the decision; per-exit rows would be ledger spam — only FIRE faces
    and degradation warns are recorded)
  - any exception                   -> pass-through (FAIL_OPEN: a guard
    failure must never deadlock the session)
"""
from __future__ import annotations
# The canonical warn — ONE implementation (process-wide dedupe per
# (op, reason) + the ledger face). The stderr-only fallback is the
# partial-deploy lifeline (scripts/ not importable here); production
# imports kunglao_log.
try:
    from _path_hygiene import ensure_scripts_path as _esp406
    _esp406()
    from kunglao_log import warn
except Exception:  # noqa: BLE001 — fail-open lifeline, never block the hook
    def warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)
import json
import sys
from pathlib import Path

from _path_hygiene import scripts_on_path  # #671 sys.path hygiene authority

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
HOOK_NAME = "workguard_gate"


def _resolve_workspace(payload: dict) -> Path | None:
    """First candidate with a workspace MARKER wins (claim-register.yaml
    or .hook_state.json, under cwd or cwd/malware-analysis-workspace) —
    the completion-gate convention."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / "claim-register.yaml").exists() \
                or (base / ".hook_state.json").exists():
            return base
    return None


def _strict_active(ws: Path) -> bool:
    """Default-inactive strict activation (mirrors the completion gate):
    the guard fires only when explicitly activated AND not expired."""
    try:
        with scripts_on_path():
            import hook_activation as ha
        return ha.is_active_strict(ws, HOOK_NAME)
    except Exception:  # noqa: BLE001 — never block on an activation error
        return False


def process_event(payload: dict) -> int:
    """Testable core: second-stop pass-through -> workspace resolve ->
    strict activation -> actionable set -> block+guidance or legal sleep.
    Returns rc."""
    if payload.get("stop_hook_active"):
        return 0  # second stop: never re-block (anti-deadlock contract)
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0
    if not _strict_active(ws):
        return 0
    with scripts_on_path():
        import workguard
        result = workguard.actionable_set(ws)
        guidance = workguard.turn_exit_guidance(ws, result)
    if not result["claims"]:
        return 0  # legal sleep — silent pass
    _record_fire(ws, result)
    print(json.dumps({"decision": "block", "reason": guidance},
                     ensure_ascii=False))
    return 1


def _record_fire(ws: Path, result: dict) -> None:
    """One guard_fired ledger row per FIRE (actor hook:workguard_gate,
    detail = the actionable faces + standing walls). Best-effort:
    observability must never break the block decision."""
    try:
        with scripts_on_path():
            import kunglao_log
            kunglao_log.emit(
                ws, actor=f"hook:{HOOK_NAME}", action="guard_fired",
                detail=json.dumps(
                    {"claims": result["claims"], "walls": result["walls"],
                     "active_workers": result["active_workers"]},
                    ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — fail-open, leave the trace
        warn("workguard_record", f"{type(exc).__name__}: {exc}")


def main(stdin_stream=None) -> int:
    """Stop entry. Reads the JSON payload from stdin (or stdin_stream for
    tests). FAIL_OPEN: unparseable stdin or any processing error -> exit 0
    (never deadlock the session)."""
    try:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        data = stream.read()
        payload = json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    try:
        return process_event(payload)
    except Exception:  # noqa: BLE001 — FAIL_OPEN at the body level
        return 0


if __name__ == "__main__":
    sys.exit(main())
