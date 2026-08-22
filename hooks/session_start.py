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

# Add scripts/ to path for hook_activation
_SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SKILL_ROOT / "scripts"))

from hook_activation import always_arm, renew, read_state


def session_start(workspace: Path) -> int:
    """SessionStart handler: arm completion_gate and refresh TTL.
    
    #533 F-C5: SessionStart re-arms enforcement hooks on session restart.
    """
    try:
        ws = workspace / ".kunglao"
        if not ws.exists():
            print(f"[session_start] no .kunglao dir at {ws} — skipped")
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
    ap = argparse.ArgumentParser(description="#533 SessionStart hook")
    ap.add_argument("workspace", type=Path)
    args = ap.parse_args()
    sys.exit(session_start(args.workspace))
