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
  0. hooks_selfcheck  — (a) import-time verifies all 9 WIRE_UP_HOOK_FILES via
                        derive_hook_subset (loud fail on registry drift); (b) run-time
                        checks 4 liveness-chain hooks (heartbeat_touch/worker_budget/
                        dispatch_gate/worker_pulse) in project settings.json; auto-rebuilds
                        via --wire-up if missing; warns on global leftover hooks (#258)
                        auto-rebuilt via --wire-up if dropped (v1.9.37)
  1. reconcile        — rebuild [active_workers] from worker-status-*.md +
                        plan-redteam-*.md (verifier visibility, v1.9.37)
  6. renew            — refresh hooks TTL + heartbeat last_tick_ts
  7. heartbeat-check  — assert last_tick_ts < 35 min old
  8. oracle-check     — task-oracle.yaml registered (#473 gate power-on;
                        report field oracle_registered + actionable line
                        when missing; report-only, never fails the tick)
  9. env-probe        — liveness-subset env snapshot → runs/env-state.json
                        (#475: env freshness bound to the tick by
                        construction — the only mechanically-enforced
                        periodic; probe failure never fails the tick)

Output: runs/.heartbeat-tick.json (report) + stdout summary. Exit 0 = all OK,
1 = heartbeat stale, project hooks missing, or selfcheck failed (LLM must act;
the report's per-step stderr tails carry the failure text).

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

import hook_activation as ha

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/ (scripts/ -> root)
SCRIPTS = SKILL_DIR / "scripts"

# Renewal-margin early warning (issue #365): a tick chain that is ALIVE but
# cadence-mismatched with the 30-min TTL renews just before expiry — the one
# silent-gate case no other anomaly surfaces. 10 min = a third of the TTL:
# enough lead time to act before the NEXT tick misses the renewal entirely.
RENEW_MARGIN_LOW_MINUTES = 10
RENEW_MARGIN_LOW_LINE = "[hooks] renewal margin low (<10 min) — check tick cadence vs 30-min TTL"


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
        # stdout AND stderr tails both ride the report (#381): a crashed step
        # (e.g. hooks_selfcheck import-time registry drift) prints its
        # traceback to stderr — stdout-only storage dropped the failure text,
        # leaving an rc=1 step mute in the report.
        return {"rc": r.returncode, "stdout": r.stdout.strip()[-300:],
                "stderr": r.stderr.strip()[-300:]}
    except Exception as exc:
        return {"rc": -1, "stdout": f"EXC {exc}", "stderr": ""}


def _renew_margin_low(ws: Path) -> bool:
    """True when < RENEW_MARGIN_LOW_MINUTES of the current activation remains.

    Fail-open by design (#365): missing/corrupt state, unparseable expiry —
    return False (no warning). The margin check must never fail the tick.
    """
    try:
        expires = ha.read_state(ws).get("expires_at")
        if not expires:
            return False
        exp = datetime.datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        margin = exp - datetime.datetime.now(datetime.timezone.utc)
        return margin < datetime.timedelta(minutes=RENEW_MARGIN_LOW_MINUTES)
    except Exception:
        return False


def _oracle_registered(ws: Path) -> bool:
    """#473 gate power-on: true iff the workspace carries a non-empty
    task-oracle.yaml (the completion-gate anchor init registers + Phase 0
    backfills). Fail-open on read errors -> False (reported, never crashes
    the tick); does NOT change the tick exit code by itself (the
    selfcheck/renew/heartbeat rc weights stay authoritative)."""
    try:
        p = ws / "task-oracle.yaml"
        if not p.exists() or not p.read_text(encoding="utf-8").strip():
            return False
        # #473 review HIGH-1: the init skeleton marker is not a registered
        # oracle — the Phase-0 backfill (user's verbatim task) is what
        # powers the completion gate. Marker still present = still
        # unregistered (the nag line below must fire).
        return "pending-user-input-backfill" not in p.read_text(encoding="utf-8")
    except OSError:
        return False


ORACLE_MISSING_LINE = (
    "[gate] task-oracle.yaml not registered — the closing gate chain is "
    "unpowered; run Phase 0 backfill (write the user's task verbatim into "
    "task-oracle.yaml) before completion can be judged (#473)"
)


def main(argv: list[str] | None = None) -> int:
    """argv: explicit CLI args (defaults to sys.argv[1:]) — lets the kunglao.py
    router pass the caller's workspace instead of the router's own argv
    (issue #370: bare main() resolved the subcommand token "tick" as the ws)."""
    # UTF-8 stdout unification (same pattern as scripts/mcp_probe.py) — scoped
    # to CLI execution so importing this module never mutates the importer's
    # stdout (kunglao.py router imports it). Without it the #365 warn line's
    # em-dash prints as cp936 on a GBK console/pipe and the caller's UTF-8
    # read sees mojibake (#457 triage #6).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # captured stream without reconfigure (pytest capsys)
    args = sys.argv[1:] if argv is None else argv
    ws = _resolve_ws(args[0] if args else None)
    # action_taken (issue #237): the tick MUST produce a convergence action or a
    # mechanical convergence argument. The orchestrator fills this field after
    # reading the report — what it dispatched / verified / solved / reactivated.
    # An empty field is the idle-tick fault signal (tokens burned with no action).
    report = {"ts": utc_now(), "workspace": str(ws), "action_taken": ""}

    report["selfcheck"] = run("hooks_selfcheck.py", ws)
    report["reconcile"] = run("hook_activation.py", ws, "--reconcile")
    # step 6 — renew, with pre-renewal margin warning (#365): measured BEFORE
    # --renew overwrites expires_at. Diagnostic only: the renew always runs,
    # healthy margin stays silent (field + line appear only when low).
    if _renew_margin_low(ws):
        report["renew_margin_low"] = True
        print(RENEW_MARGIN_LOW_LINE)
    report["renew"] = run("hook_activation.py", ws, "--renew")
    report["heartbeat"] = run("hook_activation.py", ws, "--heartbeat-check")
    # step 8 (#473): oracle registration check — one report field + one
    # actionable stdout line when missing (mechanical催告; the LLM reading
    # the tick acts). Report-only: rc weights unchanged.
    report["oracle_registered"] = _oracle_registered(ws)
    if not report["oracle_registered"]:
        print(ORACLE_MISSING_LINE)
    # step 9 — env-probe (#475): liveness-subset snapshot into
    # runs/env-state.json (check_env_fresh / env_drift_watch consume it).
    # The subprocess rc is advisory-only: env drift is surfaced by the
    # monitor + the fresh gate, and a probe crash must never fail the tick
    # (env_state_probe itself exits 0 on probe failure; rc!=0 here means
    # the script itself crashed — recorded, not fatal).
    report["env_state"] = run("env_state_probe.py", ws)

    out = ws / "runs" / ".heartbeat-tick.json"
    try:
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    sc = report["selfcheck"].get("stdout", "")[:80]
    hb = report["heartbeat"].get("stdout", "")[:120]
    rc_sc = report["selfcheck"].get("rc", -1)
    rc_renew = report["renew"].get("rc", -1)
    rc_hb = report["heartbeat"].get("rc", -1)
    action = report["action_taken"] or "(EMPTY — must be filled: what was dispatched/verified/resolved/reactivated)"
    print(f"heartbeat_tick: {sc} | selfcheck_rc={rc_sc} | renew_rc={rc_renew} | {hb}")
    print(f"action_taken: {action}")
    print(f"report: {out}")
    # #381: selfcheck rc weighs in — a crashed selfcheck (registry drift at
    # import, failed rebuild) must fail the tick, not ride it silently.
    return 0 if rc_hb == 0 and rc_renew == 0 and rc_sc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
