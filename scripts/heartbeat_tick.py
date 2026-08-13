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

Usage: python heartbeat_tick.py <workspace>
"""
import json
import subprocess
import sys
import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/ (scripts/ -> root)
SCRIPTS = SKILL_DIR / "scripts"


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    ws = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("D:/works/samples/2026-07-01/malware-analysis-workspace").resolve()
    report = {"ts": utc_now(), "workspace": str(ws)}

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
    print(f"heartbeat_tick: {sc} | renew_rc={rc_renew} | {hb}")
    print(f"report: {out}")
    return 0 if rc_hb == 0 and rc_renew == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
