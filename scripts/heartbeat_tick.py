#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.9.38 — heartbeat_tick.py: ONE-command heartbeat tick (mechanical part).

The heartbeat LOOP has a platform limit: Claude Code's cron can only fire a
prompt at the LLM, it cannot run scripts directly. Every prior design made the
tick N LLM-executed steps (selfcheck/reconcile/renew/heartbeat-check), so a busy
or compacted orchestrator skipped steps or the whole tick — the recurring
'heartbeat lost / monitoring stopped' report.

This script collapses the MECHANICAL steps of the tick into ONE command. The LLM
fires it, reads the JSON report, and does only what needs cognition (ping stuck
workers, dispatch). Fewer steps = fewer failure modes.

Steps executed (idempotent, all safe to re-run):
  0. hooks_selfcheck  — project+user settings.json kunglao hooks present; user-level
                        auto-rebuilt via --wire-up if dropped (v1.9.37)
  1. reconcile        — rebuild [active_workers] from worker-status-*.md +
                        plan-redteam-*.md (verifier visibility, v1.9.37)
  6. renew            — refresh hooks TTL + heartbeat last_tick_ts
  7. heartbeat-check  — assert last_tick_ts < 35 min old

Output: runs/.heartbeat-tick.json (report) + stdout summary. Exit 0 = all OK,
1 = heartbeat stale or project hooks missing (LLM must act).

The report carries `action_taken` (issue #237): the orchestrator fills what
convergence action this tick produced (dispatched/verified/solved/reactivated);
an empty field means the tick idled — a fault signal (tokens burned).

Usage: python heartbeat_tick.py <workspace>
"""
import json
import os
import subprocess
import sys
import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/ (scripts/ -> root)
SCRIPTS = SKILL_DIR / "scripts"


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


def run(script: str, ws: Path, *extra: str) -> dict:
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / script), str(ws), *extra],
            capture_output=True, text=True, timeout=60,
        )
        return {"rc": r.returncode, "stdout": r.stdout.strip()[-300:]}
    except Exception as exc:
        return {"rc": -1, "stdout": f"EXC {exc}"}


def main() -> int:
    ws = _resolve_ws(sys.argv[1] if len(sys.argv) > 1 else None)
    # action_taken (issue #237): the tick MUST produce a convergence action or a
    # mechanical convergence argument. The orchestrator fills this field after
    # reading the report — what it dispatched / verified / solved / reactivated.
    # An empty field is the idle-tick fault signal (tokens burned with no action).
    report = {"ts": utc_now(), "workspace": str(ws), "action_taken": ""}

    report["selfcheck"] = run("hooks_selfcheck.py", ws)
    report["reconcile"] = run("hook_activation.py", ws, "--reconcile")
    report["renew"] = run("hook_activation.py", ws, "--renew")
    report["heartbeat"] = run("hook_activation.py", ws, "--heartbeat-check")

    out = ws / "runs" / ".heartbeat-tick.json"
    try:
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    sc = report["selfcheck"].get("stdout", "")[:80]
    hb = report["heartbeat"].get("stdout", "")[:120]
    rc_renew = report["renew"].get("rc", -1)
    rc_hb = report["heartbeat"].get("rc", -1)
    action = report["action_taken"] or "(EMPTY — must be filled: what was dispatched/verified/resolved/reactivated)"
    print(f"heartbeat_tick: {sc} | renew_rc={rc_renew} | {hb}")
    print(f"action_taken: {action}")
    print(f"report: {out}")
    return 0 if rc_hb == 0 and rc_renew == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
