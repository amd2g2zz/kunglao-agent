#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/session_start.py — SessionStart hook entry.

Fires on Claude Code SessionStart (startup / resume / clear). Ensures:
1. always_arm(): completion_gate is permanently armed
2. renew(): TTL refreshed on session restart
3. THE CONSTITUTION (event-wakeup topology, issue 434): the loop's static
   decision semantics inject HERE, once per session — the cron heartbeat
   no longer re-injects the operating manual every interval. The injection
   lands on stdout (SessionStart context) and is recorded as ONE
   constitution_injected ledger row (the once-per-session contract is
   auditable, not self-declared).
4. STRATEGY RESUME: the last round strategy re-attaches through the
   versioned seam (runs/round-strategy.json) when the object exists; an
   absent object renders nothing, cleanly (the producer lands later).

Usage in .claude/settings.json (registered by hook_activation
--wire-up; payload arrives on stdin like every hook event):
  {"hooks": [{"type": "command",
    "command": "uv run --project <skill_root> hooks/session_start.py"}]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _path_hygiene import ensure_scripts_path  # #671 sys.path hygiene authority

# Add scripts/ to path for hook_activation (#671: idempotent, position-stable
# membership via the hygiene authority — was a bare leaking insert).
_SKILL_ROOT = Path(__file__).resolve().parents[1]
ensure_scripts_path()

from hook_activation import always_arm, renew  # noqa: E402

CONSTITUTION_MARK = "constitution"


def session_start(workspace: Path) -> int:
    """SessionStart handler: arm completion_gate and refresh TTL.

    The legacy direct-call face (kept verbatim — the workspace-notice
    contract is pinned by an older suite). The constitution/strategy
    injection lives in the payload face (main_with_payload), which has the
    event's source + resolved workspace markers.

    #533 F-C5: SessionStart re-arms enforcement hooks on session restart.
    #25 D4: hooks-only-in-workspace is a silent assumption failure — when
    this entry runs WITHOUT a kunglao workspace (user-level registration,
    a half-initialized dir, or a path passed by hand), the gates will not
    fire, so say so loudly instead of quietly skipping: one line, hooks
    NOT active + the activation hint.
    """
    try:
        ws = workspace / ".kunglao"
        if not ws.exists():
            print(f"[session_start] kunglao hooks are NOT active in this "
                  f"session — no kunglao workspace at {workspace} "
                  f"(hooks are workspace-scoped: they deploy to and fire "
                  f"only inside <ws>/.claude/settings.json). To activate: "
                  f"cd into the workspace and run /kunglao-agent:init")
            return 0

        # F-S1: ensure completion_gate is always armed
        state = always_arm(ws)
        print(f"[session_start] always_arm: active={state.get('active_hooks', [])}")

        # Refresh TTL
        renew(ws)
        print(f"[session_start] renewed TTL")

        return 0
    except Exception as exc:
        print(f"[session_start] ERROR: {exc}", file=sys.stderr)
        return 0  # non-fatal: don't block session


def _resolve_ws(payload: dict) -> Path | None:
    """Pure delegation to scripts/ws_layout.py (#863 Family C)."""
    from ws_layout import resolve_payload_ws
    return resolve_payload_ws(payload)


def main_with_payload(payload: dict) -> int:
    """The registered SessionStart face: arm + renew + inject the
    constitution (once per session event) + the last strategy through the
    seam. FAIL_OPEN: any error -> rc 0 (a session must never be blocked by
    its own bootstrap), with the error on stderr."""
    try:
        ws = _resolve_ws(payload)
        if ws is None:
            # not a kunglao workspace session — the direct-call notice face
            # owns the loud guidance; payload face stays silent-exit-0
            return 0
        state = always_arm(ws)
        print(f"[session_start] always_arm: "
              f"active={state.get('active_hooks', [])}")
        renew(ws)
        print("[session_start] renewed TTL")

        import heartbeat_loop_prompt
        print(heartbeat_loop_prompt.constitution(str(ws)))

        try:
            import strategy_sections
            sections = strategy_sections.render(ws)
            if sections:
                print("[session_start] last round strategy (resume via the "
                      "strategy seam):")
                print(sections)
        except Exception as exc:  # noqa: BLE001 — seam renders nothing on failure
            print(f"[session_start] WARN: strategy seam unavailable "
                  f"({type(exc).__name__}: {exc})", file=sys.stderr)

        try:
            import kunglao_log
            kunglao_log.emit(ws, actor="hook:session_start",
                             action="constitution_injected",
                             detail=str(payload.get("source") or "startup"))
        except Exception as exc:  # noqa: BLE001 — recording never blocks
            print(f"[session_start] WARN: injection record failed "
                  f"({type(exc).__name__}: {exc})", file=sys.stderr)
        return 0
    except Exception as exc:  # noqa: BLE001 — FAIL_OPEN body level
        print(f"[session_start] ERROR: {exc}", file=sys.stderr)
        return 0


def main(stdin_stream=None) -> int:
    """SessionStart entry: JSON payload on stdin (the registered shape);
    argv positional falls back to the legacy direct call."""
    try:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        data = stream.read()
    except OSError:
        data = ""
    if data:
        try:
            payload = json.loads(data)
            if isinstance(payload, dict):
                return main_with_payload(payload)
        except (json.JSONDecodeError, ValueError):
            pass  # not a payload — fall through to the legacy argv face
    import argparse
    ap = argparse.ArgumentParser(description="SessionStart hook")
    ap.add_argument("workspace", type=Path, nargs="?")
    args, _unknown = ap.parse_known_args()
    if args.workspace is None:
        return 0
    return session_start(args.workspace)


if __name__ == "__main__":
    sys.exit(main())
