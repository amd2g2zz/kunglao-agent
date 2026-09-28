#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/round_closure.py — SubagentStop wiring (event-wakeup topology,
issue 434): the round-closure event feed.

Between-turns wakes come from worker completion notifications — but the
closure itself left no ledger row the decision faces could consume (the
lifecycle pipe existed with no live producer on this event). This hook
appends ONE closure event row per SubagentStop: a lifecycle_completed
transition (kunglao_log.emit_lifecycle — the established subagent
lifecycle face) carrying the session identity in detail.

Pure recorder, fail-open double cage: any error -> rc 0, silent. A
closure observation must never disturb the subagent's own stop path.
"""
from __future__ import annotations
# The canonical warn — ONE implementation (process-wide dedupe per
# (op, reason) + the ledger face). The stderr-only fallback is the
# partial-deploy lifeline; production imports kunglao_log.
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

CLOSURE_ACTOR = "subagent:stop"


def _resolve_workspace(payload: dict) -> Path | None:
    """Workspace markers (claim-register.yaml / .hook_state.json) under
    cwd or cwd/malware-analysis-workspace — the deployed convention."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / "claim-register.yaml").exists() \
                or (base / ".hook_state.json").exists():
            return base
    return None


def process_event(payload: dict) -> int:
    """Resolve the workspace, append the closure row, rc 0."""
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0
    detail = {
        "session_id": payload.get("session_id"),
        "transcript": payload.get("transcript_path"),
        "source": "SubagentStop",
    }
    try:
        with scripts_on_path():
            import kunglao_log
            kunglao_log.emit_lifecycle(
                ws, CLOSURE_ACTOR, "completed",
                detail=json.dumps(detail, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — recorder, never blocks
        warn("round_closure", f"{type(exc).__name__}: {exc}")
    return 0


def main_with_payload(payload: dict) -> int:
    return process_event(payload)


def main(stdin_stream=None) -> int:
    """SubagentStop entry: JSON payload on stdin. FAIL_OPEN on every
    error face — rc 0, silent."""
    try:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        data = stream.read()
        payload = json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    try:
        return process_event(payload)
    except Exception:  # noqa: BLE001 — body-level fail-open
        return 0


if __name__ == "__main__":
    sys.exit(main())
