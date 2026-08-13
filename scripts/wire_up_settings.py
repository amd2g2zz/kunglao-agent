# -*- coding: utf-8 -*-
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
    "Bash"), and under Stop (no matcher — Stop fires on every termination)
    registers hooks/completion_gate.py (#55). Skips entries that already exist
    (same command path / basename), preserves every other key. Writes back with
    4-space indent. Returns the number of hook entries registered.
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

    def _ensure_stop(entries: list, hook_file: str) -> tuple[list, bool]:
        """Stop hooks carry no matcher (they fire on every Stop event). Dedupe
        by command basename across all Stop entries so re-wiring replaces, not
        stacks. Appends one entry with the single hook."""
        kept, found = [], False
        for e in entries:
            hs = e.get("hooks", [])
            filtered = []
            for h in hs:
                cmd = str(h.get("command", "")).replace("\\", "/")
                if cmd.rsplit("/", 1)[-1] == hook_file:
                    found = True  # drop existing — re-added fresh below
                else:
                    filtered.append(h)
            if filtered:
                kept.append({"hooks": filtered})
        kept.append({"hooks": [_entry(hook_file)]})
        return kept, True

    count = 0
    # env_check_gate FIRST: the environment hard-gate (#233) must reject a
    # teammate-polluted dispatch before any budget/state logic runs.
    pre, added = _ensure(pre, "Agent", "env_check_gate.py")
    count += added
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
    # state_anchor (#44): per-turn mechanical state re-anchor on every worker
    # completion — the L1 PREVENT layer (F5 forget/refresh). Same matcher /
    # _entry shape as worker_pulse; idempotent via _ensure's basename dedupe.
    post, added = _ensure(post, "Agent", "state_anchor.py")
    count += added

    # completion_gate (#55): the code-owned completion gate. Stop hook — fires
    # at session termination, blocks when task-oracle.yaml is unsatisfied.
    # No matcher (Stop is not a tool-use event); dedupe by command basename.
    stop = hooks.get("Stop") or []
    stop, added = _ensure_stop(stop, "completion_gate.py")
    count += added

    hooks["PreToolUse"] = pre
    hooks["PostToolUse"] = post
    hooks["Stop"] = stop
    existing["hooks"] = hooks
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return count
