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
it (a) import-time verifies all 9 WIRE_UP_HOOK_FILES registry entries via
derive_hook_subset and (b) run-time checks the 4 liveness-chain hooks
PROJECT-level <workspace>/.claude/settings.json — the wire-up deployment target since
issue #258 (2026-08-12; pre-#258 wrote the user-global file and bound hooks to a
worktree path that died with the worktree). If project-level is missing any hook, it
auto-rebuilds via hook_activation.py --wire-up (which now writes the project-level
file). The user-global ~/.claude/settings.json is NOT a deployment target anymore:
if it still carries kunglao hooks, this script prints a migration warning (remove
them from global; they must live in the project settings) but never rewrites it.

Wires in via heartbeat_loop_prompt.py (step 0 of every tick). Idempotent + fast (<50ms).
"""
import json
import os
import subprocess
import sys
import datetime
from pathlib import Path

import wire_up_settings

# #536: template version stamp verify (init writes, selfcheck verifies —
# same shape as the state_hash contract).
import template_version  # noqa: E402

# #381: KONG_HOOK_FILES is a DELIBERATE narrow subset of the hook registry
# (wire_up_settings.WIRE_UP_HOOK_FILES) — the mechanical liveness chain this
# self-repair verifies (the 4 hooks from the v1.9.37 'heartbeat lost'
# incident). The other registry files (env_check_gate/recall_inject/
# state_anchor/completion_gate) are deployment gates whose drops env_check's
# full-registry scan catches. Derived from the registry via
# wire_up_settings.derive_hook_subset: a registry rename/growth raises
# loudly at import instead of this script silently checking a stale 4.
_KONG_CHAIN_FILES = (
    "heartbeat_touch.py",   # liveness refresh on any tool use
    "worker_budget.py",     # budget/tier enforcement
    "dispatch_gate.py",     # dispatch contract gate
    "worker_pulse.py",      # completion pulse
)
_KONG_SKIP_FILES = frozenset({
    "env_check_gate.py",    # env hard-gate — env_check scans it
    "recall_inject.py",     # recall injector — env_check scans it
    "state_anchor.py",      # state re-anchor — env_check scans it
    "completion_gate.py",   # Stop completion gate — env_check scans it
    "write_guard.py",       # carrier write gate — env_check scans it (#532)
    "orchestrator_tool_guard.py",  # Bash maker-checker WARN — env_check scans it (#608)
    "violation_capture.py", # Bash violation recorder — env_check scans it (#718)
    "bash_fact_guard.py",   # Bash facts-write lint recorder — env_check scans it (#809)
})

# #381: validate the subset tables against the registry (raises on drift) —
# then build the ordered list from the chain tuple, which keeps this
# script's historical check order.
wire_up_settings.derive_hook_subset(
    wire_up_settings.WIRE_UP_HOOK_FILES,
    include=_KONG_CHAIN_FILES, skip=_KONG_SKIP_FILES,
    owner="hooks_selfcheck KONG_HOOK_FILES")
KONG_HOOK_FILES = list(_KONG_CHAIN_FILES)
# User-global settings: NOT a deployment target since #258. Checked only to warn
# about leftover kunglao hooks that should be migrated to the project level.
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


def rebuild_project_level(workspace: Path) -> dict:
    """Auto-rebuild the PROJECT-level settings via --wire-up (writes
    <workspace>/.claude/settings.json since #258)."""
    skill_dir = Path(__file__).resolve().parent.parent  # kunglao-agent/ (scripts/ -> root)
    script = skill_dir / "scripts" / "hook_activation.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), str(workspace), "--wire-up"],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        return {"rebuilt": True, "rc": r.returncode, "stdout_tail": r.stdout.strip()[-200:]}
    except Exception as exc:
        return {"rebuilt": False, "error": str(exc)}


def check_stamp_version(ws: Path) -> dict:
    """#536: three-carrier template version stamp consistency.

    Faults are reported (report row + status line) but do NOT move the
    exit code here — hooks_selfcheck owns hook liveness; the stamp HARD
    gate is env_check's `template_version` row. A stamp fault printed
    every tick makes the drift visible in the operator stream without
    downing heartbeat repair for a cosmetic-to-hooks defect."""
    try:
        faults = template_version.verify_stamps(ws)
    except RuntimeError as exc:  # unreadable skill version — surface, don't crash
        return {"faults": {}, "error": str(exc)}
    return {"faults": faults}


def main() -> int:
    ws = _resolve_ws(sys.argv[1] if len(sys.argv) > 1 else None)
    proj_settings = ws / ".claude" / "settings.json"
    proj_check = check_settings(proj_settings)
    user_check = check_settings(USER_SETTINGS)

    # #258: user-global is NOT a deployment target. Leftover kunglao hooks there
    # are a migration hazard (worktree-bound paths) — warn, never rewrite.
    migration_warning = None
    if user_check.get("hooks_segment") and user_check.get("present"):
        migration_warning = (
            f"WARNING: kunglao hooks still present in user-global {USER_SETTINGS} "
            f"— migrate them to the project-level {proj_settings} and remove from "
            f"global (issue #258: global hooks bind to a worktree path and die "
            f"with it). This script never rewrites the global file."
        )
        print(migration_warning, file=sys.stderr)

    rebuilt = {}
    if proj_check.get("hooks_segment") is False or proj_check.get("missing"):
        rebuilt = rebuild_project_level(ws)
        if rebuilt.get("rc") == 0:
            # maker-checker: re-read the file — don't trust the subprocess claim.
            proj_check = check_settings(proj_settings)

    report = {
        "ts": utc_now(),
        "project_settings": str(proj_settings),
        "user_settings": str(USER_SETTINGS),
        "project_level": proj_check,
        "user_level": user_check,
        "user_migration_warning": migration_warning,
        "project_rebuild": rebuilt,
        # #536: stamp faults = per-carrier missing/mismatch map
        "template_version_stamps": check_stamp_version(ws),
    }
    out = ws / "runs" / ".hooks-selfcheck.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    proj_ok = proj_check.get("hooks_segment") and not proj_check.get("missing")
    status = f"project={'OK' if proj_ok else 'MISSING ' + str(proj_check.get('missing'))}"
    if migration_warning:
        status += " (global has leftover kunglao hooks — migrate)"
    # #536: stamp faults ride the status line (non-fatal here — see
    # check_stamp_version docstring).
    stamp_faults = report["template_version_stamps"].get("faults") or {}
    if stamp_faults:
        status += (f" (template_version stamp faults: "
                   f"{', '.join(f'{k}={v}' for k, v in sorted(stamp_faults.items()))})")
    print(f"hooks_selfcheck: {status}")
    return 0 if proj_ok else 1


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
