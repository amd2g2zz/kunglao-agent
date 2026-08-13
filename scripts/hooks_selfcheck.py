#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.9.37 — hooks_selfcheck.py (root-cause fix for recurring 'heartbeat/monitoring lost').

Incident (2026-08-05 14:20): ~/.claude/settings.json had its entire `hooks` segment
dropped by an unrelated settings rewrite (enabledPlugins/env/statusLine keys were
preserved, hooks vanished). All kunglao hooks (heartbeat_touch + worker_budget +
dispatch_gate + worker_pulse) disappeared -> mechanical heartbeat stopped (last_tick
frozen, back to cron-cognitive refresh) -> user report 'heartbeat lost again'. This
is the SAME class as the v1.9.18 'settings rewrites drop hooks' failure: any settings
mutation by Claude Code UI / plugin toggle / enabledPlugins change can silently omit
the hooks key, and nothing restores it.

This script is the mechanical cure. Run every heartbeat tick (step 0 of the tick,
before reconcile/dispatch): it verifies the 4 kunglao hooks are present in BOTH
project-level (workspace-parent/.claude/settings.json — the stable source of truth,
carries block_malware_exec + mcpServers + env) AND user-level (~/.claude/settings.json
— backup). If user-level is missing any hook, it auto-rebuilds via hook_activation.py
--wire-up. If project-level is missing any hook, it reports exit=1 (project-level is
not auto-rewritten because it carries mcpServers/env/block_malware_exec that need care;
orchestrator surfaces to user for manual fix).

Wires in via heartbeat_loop_prompt.py (step 0 of every tick). Idempotent + fast (<50ms).
"""
import json
import os
import subprocess
import sys
import datetime
from pathlib import Path

KONG_HOOK_FILES = [
    "heartbeat_touch.py",
    "worker_budget.py",
    "dispatch_gate.py",
    "worker_pulse.py",
]
USER_SETTINGS = Path.home() / ".claude" / "settings.json"


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve_ws(arg: str | None) -> Path:
    """Workspace root: explicit arg wins; else probe cwd; else hard error.

    Issue #228: the old fallback defaulted to one operator's absolute Windows
    workspace path — silently wrong on any other machine. Never guess
    a workspace: a wrong one means state written to the wrong tree.
    """
    if arg:
        return Path(arg).resolve()
    cwd = Path(os.getcwd())
    for cand in (cwd, cwd / "malware-analysis-workspace"):
        if (cand / "claim-register.yaml").exists() or (cand / "analysis_state.txt").exists():
            return cand.resolve()
    print(f"ERROR: no workspace found under cwd ({cwd}); pass the workspace "
          f"explicitly: python {Path(sys.argv[0]).name} <workspace>",
          file=sys.stderr)
    sys.exit(2)


def check_settings(settings_path: Path) -> dict:
    if not settings_path.exists():
        return {"exists": False, "hooks_segment": False, "present": [], "missing": list(KONG_HOOK_FILES)}
    try:
        s = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"exists": True, "hooks_segment": False, "parse_error": str(exc), "present": [], "missing": list(KONG_HOOK_FILES)}
    hooks = s.get("hooks")
    if not hooks:
        return {"exists": True, "hooks_segment": False, "present": [], "missing": list(KONG_HOOK_FILES)}
    cmds = []
    for ev, entries in hooks.items():
        for e in entries:
            for h in e.get("hooks", []):
                cmds.append(h.get("command", ""))
    present, missing = [], []
    for hf in KONG_HOOK_FILES:
        (present if any(hf in c for c in cmds) else missing).append(hf)
    return {"exists": True, "hooks_segment": True, "present": present, "missing": missing}


def rebuild_user_level(workspace: Path) -> dict:
    skill_dir = Path(__file__).resolve().parent.parent  # kunglao-agent/ (scripts/ -> root)
    script = skill_dir / "scripts" / "hook_activation.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), str(workspace), "--wire-up"],
            capture_output=True, text=True, timeout=30,
        )
        return {"rebuilt": True, "rc": r.returncode, "stdout_tail": r.stdout.strip()[-200:]}
    except Exception as exc:
        return {"rebuilt": False, "error": str(exc)}


def main() -> int:
    ws = _resolve_ws(sys.argv[1] if len(sys.argv) > 1 else None)
    proj_settings = ws.parent / ".claude" / "settings.json"
    user_check = check_settings(USER_SETTINGS)
    proj_check = check_settings(proj_settings)

    report = {
        "ts": utc_now(),
        "user_settings": str(USER_SETTINGS),
        "project_settings": str(proj_settings),
        "user_level": user_check,
        "project_level": proj_check,
    }

    if user_check.get("hooks_segment") is False or user_check.get("missing"):
        report["user_level_rebuild"] = rebuild_user_level(ws)

    out = ws / "runs" / ".hooks-selfcheck.json"
    try:
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    proj_ok = proj_check.get("hooks_segment") and not proj_check.get("missing")
    user_ok = not user_check.get("missing") or report.get("user_level_rebuild", {}).get("rebuilt")
    status = f"project={'OK' if proj_ok else 'MISSING ' + str(proj_check.get('missing'))}, user={'OK' if user_ok else 'DEGRADED'}"
    print(f"hooks_selfcheck: {status}")
    return 0 if proj_ok else 1


if __name__ == "__main__":
    sys.exit(main())
