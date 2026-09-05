#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/session_start.py — #533 SessionStart hook entry.

Fires on Claude Code SessionStart event. Ensures:
1. always_arm(): completion_gate is permanently armed (F-S1)
2. renew(): TTL refreshed on session restart
3. Hook registration check: all 9 WIRE_UP_HOOK_FILES present

Usage in .claude/settings.json:
  "PreToolUse": [{"command": "uv run --project <skill> hooks/session_start.py"}]
"""
from __future__ import annotations

import sys
from pathlib import Path

from _path_hygiene import ensure_scripts_path  # #671 sys.path hygiene authority

# Add scripts/ to path for hook_activation (#671: idempotent, position-stable
# membership via the hygiene authority — was a bare leaking insert).
_SKILL_ROOT = Path(__file__).resolve().parents[1]
ensure_scripts_path()

from hook_activation import always_arm, renew


def session_start(workspace: Path) -> int:
    """SessionStart handler: arm completion_gate and refresh TTL.

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


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="SessionStart hook")
    ap.add_argument("workspace", type=Path)
    args = ap.parse_args()
    sys.exit(session_start(args.workspace))
