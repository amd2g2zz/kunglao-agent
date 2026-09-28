#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/compact_continuity.py — PreCompact wiring (event-wakeup topology,
issue 434): strategy continuity across compaction.

Compaction historically evaporated the round's operating context with no
bridge. This hook injects a compact-continuity note through the versioned
strategy seam (scripts/strategy_sections.py): the note carries the current
strategy POINTER (runs/round-strategy.json when the object exists) plus
the standing rule that the strategy must survive the compact. The seam's
producer lands later; until it does the note still fires with the pointer
named as unset — the continuity face is live from day one, never a crash,
never silence.

Inject-only (hookSpecificOutput.additionalContext for the PreCompact
event), fail-open double cage: any error -> rc 0, silent.
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
    """Resolve the workspace, print the PreCompact additionalContext JSON,
    and record ONE compact_continuity row (the injection is auditable —
    an injector face records what it injected, the recall-inject
    precedent)."""
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0
    pointer = None
    try:
        with scripts_on_path():
            import strategy_sections
            pointer = strategy_sections.pointer(ws)
    except Exception as exc:  # noqa: BLE001 — seam failure degrades, never blocks
        warn("compact_continuity_seam", f"{type(exc).__name__}: {exc}")
    note = _note_text(pointer, str(payload.get("trigger") or "auto"))
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": note,
        }
    }, ensure_ascii=False))
    try:
        with scripts_on_path():
            import json as _json

            import kunglao_log
            kunglao_log.emit(
                ws, actor="hook:compact_continuity",
                action="compact_continuity",
                detail=_json.dumps(
                    {"trigger": payload.get("trigger"),
                     "strategy_pointer": pointer},
                    ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — recording never blocks the hook
        warn("compact_continuity_record", f"{type(exc).__name__}: {exc}")
    return 0


def _note_text(pointer: str | None, trigger: str) -> str:
    """The compact-continuity note: the current strategy pointer + the
    survival rule. Absent strategy object -> the pointer is named unset
    (the seam renders nothing, the note still carries the rule)."""
    where = (f"runs/round-strategy.json (SET — read it after the compact)"
             if pointer else
             "runs/round-strategy.json (unset — no round-strategy object "
             "yet)")
    return (
        "kunglao compact-continuity: the active round strategy MUST survive "
        f"this compaction (trigger={trigger}). Strategy pointer: {where}. "
        "After the compact, re-read the strategy object at that path (if "
        "set) and continue the round under its sections; the session "
        "constitution re-injects at the next SessionStart.")


def continuity_note(ws: Path, trigger: str) -> str:
    """Test seam: the note for a workspace (pointer resolved here)."""
    pointer = None
    try:
        with scripts_on_path():
            import strategy_sections
            pointer = strategy_sections.pointer(ws)
    except Exception as exc:  # noqa: BLE001 — seam failure degrades, never blocks
        warn("compact_continuity_seam", f"{type(exc).__name__}: {exc}")
    return _note_text(pointer, trigger)


def main(stdin_stream=None) -> int:
    """PreCompact entry: JSON payload on stdin. FAIL_OPEN on every error
    face — rc 0, silent (compaction must never be disturbed)."""
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
