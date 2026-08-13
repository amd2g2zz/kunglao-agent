# -*- coding: utf-8 -*-
"""wire_up_settings.py - register kunglao-agent hooks in the PROJECT settings.json.

Extracted from hook_activation.py (T-2 split) — the --wire-up job.

Issue #258 (2026-08-12): hook deployment is PROJECT-scoped. The pre-#258
hardcoded `Path.home()/.claude/settings.json` wrote hooks globally; in a
worktree (C:/Users/hr/.claude/.wt-*/) that binds the hook commands to a path
that dies with the worktree — deleting the worktree silently killed all 8
hooks and blocked every session's tool calls. Project-level deployment makes
hooks live and die WITH the workspace: no global pollution, no stale
worktree-bound commands.

Issue #269 (2026-08-13): hook COMMAND paths are absolute and point at the
CANONICAL deployed skill install (~/.claude/skills/kunglao-agent/hooks) — the
generation used `Path(__file__)` (the script's own location), so a --wire-up
run from a dev worktree bound the commands to the worktree path, which dies
with the worktree (#228 lesson). _canonical_hooks_dir() decouples the
registered path from wherever this module happens to run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _settings_target(workspace: Path | None) -> Path:
    """Project-level settings.json target (never the user-global, #258).

    - workspace given -> <workspace>/.claude/settings.json
    - workspace None  -> <cwd>/.claude/settings.json (cwd probe: an existing
      .claude/settings.json or a claim-register.yaml workspace root in cwd;
      else the file is created at <cwd>/.claude/settings.json)
    """
    if workspace is not None:
        return Path(workspace).resolve() / ".claude" / "settings.json"
    cwd = Path.cwd().resolve()
    return cwd / ".claude" / "settings.json"


def _canonical_hooks_dir() -> Path:
    """Canonical deployed skill hooks dir — where hook COMMAND paths must point.

    Issue #269: hook commands are absolute paths into the CANONICAL skill
    install (~/.claude/skills/kunglao-agent/hooks), never this module's own
    location. This script may be run from a dev worktree
    (C:/Users/hr/.claude/wt-*/); a worktree-bound command dies with the
    worktree — the #228 incident: 8 hooks went silent at once when the
    referenced path was deleted. When this module IS deployed at the canonical
    location (the normal production case), the two coincide and `here` wins.
    """
    here = Path(__file__).resolve().parent.parent / "hooks"
    canonical = Path.home() / ".claude" / "skills" / "kunglao-agent" / "hooks"
    return here if here == canonical else canonical


def wire_up_settings(workspace: Path | None = None, global_opt_in: bool = False) -> int:
    """Register kunglao-agent hooks in the PROJECT-level settings.json.

    Deployment target (issue #258):
      - workspace given  -> <workspace>/.claude/settings.json
      - workspace None   -> <cwd>/.claude/settings.json (probe; created if absent)
      - global_opt_in=True -> Path.home()/.claude/settings.json — EXPLICIT
        opt-in only; the old default wrote the user-global settings, and in a
        worktree that bound hooks to a worktree path that later died (the
        #258 incident: 8 hooks silently dead, session tool calls blocked).

    Idempotent merge: reads current settings, appends our hook entries under
    PreToolUse/PostToolUse with matcher "Agent" (heartbeat_touch on matcher
    "Bash"), and under Stop (no matcher — Stop fires on every termination)
    registers hooks/completion_gate.py (#55). Skips entries that already exist
    (same command path / basename), preserves every other key. Writes back with
    4-space indent. Returns the number of hook entries registered.
    """
    if global_opt_in:
        settings_path = Path.home() / ".claude" / "settings.json"
        print(f"WARNING: wiring kunglao-agent hooks into the USER-GLOBAL "
              f"{settings_path} — hooks must live in the project-level "
              f".claude/settings.json (issue #258); global deployment is "
              f"explicit opt-in ONLY.", file=sys.stderr)
    else:
        settings_path = _settings_target(workspace)

    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    hooks = existing.get("hooks") or {}
    pre = hooks.get("PreToolUse") or []
    post = hooks.get("PostToolUse") or []

    # hook_dir: the CANONICAL deployed skill hooks dir — NOT this module's
    # own location (#269; running from a worktree must not bind hook commands
    # to the worktree path, which dies with it — #228).
    hook_dir = _canonical_hooks_dir()

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
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return count
