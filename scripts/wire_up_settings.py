"""wire_up_settings.py - register kunglao-agent hooks in the global settings.json.

Extracted from hook_activation.py (T-2 split) — the --wire-up job.
"""
from __future__ import annotations

import json
from pathlib import Path


def wire_up_settings() -> int:
    """Register kunglao-agent hooks in the global settings.json.

    Idempotent merge: reads current settings, appends our hook entries under
    PreToolUse/PostToolUse with matcher "Agent" (heartbeat_touch on matcher
    "Bash"), skips entries that already exist (same command path), preserves
    every other key. Writes back with 4-space indent. Returns the number of
    hook entries registered.
    """
    settings_path = Path.home() / ".claude" / "settings.json"
    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    hooks = existing.get("hooks") or {}
    pre = hooks.get("PreToolUse") or []
    post = hooks.get("PostToolUse") or []

    # hook_dir: <skill>/hooks (this module lives in <skill>/scripts/)
    hook_dir = Path(__file__).resolve().parent.parent / "hooks"

    def _entry(hook_file: str) -> dict:
        # POSIX path (forward slashes): hooks run via `sh -c` — Windows
        # backslash paths get their backslashes eaten as escape chars
        # (C:\Users\... -> C:Users...).
        p = (hook_dir / hook_file).as_posix()
        return {"type": "command", "command": f"python {p}"}

    def _ensure(entries: list, matcher: str, hook_file: str) -> tuple[list, bool]:
        new = [e for e in entries if e.get("matcher") == matcher]
        other = [e for e in entries if e.get("matcher") != matcher]
        # remove legacy entries with the same basename (backslash paths from
        # pre-posix wire-up) so re-wiring replaces them, not stacks.
        new = [
            e for e in new
            if not any((h.get("command", "").replace("\\", "/").rsplit("/", 1)[-1] == hook_file) for h in e.get("hooks", []))
        ]
        new.append({"matcher": matcher, "hooks": [_entry(hook_file)]})
        return other + new, True

    count = 0
    pre, added = _ensure(pre, "Agent", "worker_budget.py")
    count += added
    pre, added = _ensure(pre, "Agent", "dispatch_gate.py")
    count += added
    # heartbeat_touch on matcher=Bash — ANY tool activity refreshes
    # last_tick_ts, decoupling heartbeat liveness from orchestrator cognition.
    pre, added = _ensure(pre, "Bash", "heartbeat_touch.py")
    count += added
    post, added = _ensure(post, "Agent", "worker_budget.py")
    count += added
    post, added = _ensure(post, "Agent", "worker_pulse.py")
    count += added

    hooks["PreToolUse"] = pre
    hooks["PostToolUse"] = post
    existing["hooks"] = hooks
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return count
