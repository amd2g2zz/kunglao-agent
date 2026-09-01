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
  10. think-seat      — #759 H1: a WAITING period (register present, ranking
                        yields zero dispatchable actions) writes
                        runs/.think-<ts>.md and its path REPLACES the empty
                        action_taken (#711 E1: idle ≠ EMPTY — cognition is an
                        action). Advisory like the other watchers: rc never
                        enters the alert weights; unparseable seat output is
                        treated as seat-unavailable (contract unchanged).

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
# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="heartbeat_tick", action="dispatch",
                             detail="module wired")
except NameError:
    pass
from pathlib import Path

import hook_activation as ha

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/ (scripts/ -> root)
SCRIPTS = SKILL_DIR / "scripts"

# Renewal-margin early warning (issue #365): a tick chain that is ALIVE but
# cadence-mismatched with the 30-min TTL renews just before expiry — the one
# silent-gate case no other anomaly surfaces. 10 min = a third of the TTL:
# enough lead time to act before the NEXT tick misses the renewal entirely.
# #597: the 10-min value is single-sourced in liveness_policy (rationale there).
from liveness_policy import RENEW_MARGIN_LOW_MINUTES  # noqa: E402
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
            capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
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


def noop_breaker(ws: Path, current_hash: str,
                 threshold: int | None = None) -> dict:
    """#634 Part B: no-progress circuit breaker state machine.

    Same content hash as the previous tick → consecutive_noop += 1; any
    change resets. At >= threshold (env KUNGLAO_NOOP_BREAKER_N, default 6)
    the breaker trips: the loop prompt treats rc=2 as a mandatory stop,
    not a warning. Pure state helper — main() owns persistence+rc.
    """
    import json as _json
    import os
    ws = Path(ws)
    n = threshold if threshold is not None else int(
        os.environ.get("KUNGLAO_NOOP_BREAKER_N", "6"))
    state_path = ws / "runs" / ".heartbeat-noop.json"
    prev = {}
    try:
        prev = _json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — absent/corrupt → fresh counter
        prev = {}
    if prev.get("hash") == current_hash:
        count = int(prev.get("count", 0)) + 1
    else:
        count = 1
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(_json.dumps(
            {"hash": current_hash, "count": count}), encoding="utf-8")
    except Exception:  # noqa: BLE001 — telemetry must not break the tick
        pass
    return {"tripped": count >= n, "consecutive_noop": count, "threshold": n}


def state_fingerprint(ws: Path) -> str:
    """#634 Part B hash input: register + _INDEX + mission ledger. Any real
    state advance changes at least one of these."""
    import hashlib
    ws = Path(ws)
    h = hashlib.sha256()
    for rel in ("claim-register.yaml", "facts/_INDEX.md",
                "runs/mission_ledger.yaml"):
        p = ws / rel
        if p.exists():
            h.update(rel.encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


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

    # #620 Gap C: the monitor finally has a runtime consumer. #88 freeze:
    # BACKGROUND advisory — recorded, never weighed into rc/alert (a crashed
    # monitor must never fail the tick; its findings surface via the report).
    report["monitor"] = run("kunglao-monitor.py", ws, "--json")

    # #629: feedback.check_stale gets its mechanical caller (was standalone
    # since #237 planned it). Same advisory posture as the monitor: recorded,
    # never weighed into rc/alert.
    report["feedback"] = run("feedback.py", ws, "--check-stale")

    # #718 P3: verify-stamp disk-vs-stream reconciliation. Advisory like
    # the monitor — an UNWITNESSED transition lands in the report + the
    # event stream (verify_status_change), never in rc/alert (a watch
    # finding must not fail the tick).
    report["verify_watch"] = run("verify_status_watch.py", ws, "--json")

    # #762 K1a: mechanical notes-closure sweep — every terminal claim without
    # its ledger rollup row gets the write loop now (outcomes -> lessons ->
    # notes-due queue -> checkpoint). This is THE mechanical trigger that
    # replaces the SKILL-prose-only contract ("claim terminal triggers rollup"
    # had zero call sites enforcing it). Advisory like monitor/feedback/
    # verify_watch: recorded in the report, NEVER weighed into rc/alert
    # (a crashed sweep must not fail the tick; fail-open by construction).
    report["rollup_sweep"] = run("rollup.py", ws, "--sweep-terminal")

    # #759 H1: THINK seat — the waiting period gets a cognitive action instead
    # of an idle action_taken (#711 E1). Advisory like monitor/feedback/
    # verify_watch/rollup_sweep: recorded in the report, NEVER weighed into
    # rc/alert. Only a seat that REPORTS waiting with an artifact substitutes
    # the field; anything else keeps the orchestrator-filled #237 contract.
    report["think"] = run("think_seat.py", ws)
    try:
        think = json.loads(report["think"].get("stdout") or "{}")
    except ValueError:
        think = {}
    if isinstance(think, dict) and think.get("waiting") and think.get("artifact"):
        report["action_taken"] = f"THINK {think['artifact']}"

    sc = report["selfcheck"].get("stdout", "")[:80]
    hb = report["heartbeat"].get("stdout", "")[:120]
    rc_sc = report["selfcheck"].get("rc", -1)
    rc_renew = report["renew"].get("rc", -1)
    rc_hb = report["heartbeat"].get("rc", -1)
    # #617: the decisive rc reaches the summary; failures carry a loud banner
    # and a truncation-immune alert field in the persisted report.
    first_failure = None
    for name, rc in (("selfcheck", rc_sc), ("renew", rc_renew), ("heartbeat", rc_hb)):
        if rc != 0 and first_failure is None:
            first_failure = {"step": report[name].get("script", name), "rc": rc}
    report["alert"] = first_failure is not None
    report["first_failure"] = first_failure

    out = ws / "runs" / ".heartbeat-tick.json"
    try:
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    # #634 Part B: no-progress circuit breaker — N consecutive identical
    # state fingerprints is the suspended-workspace burn the issue documented
    # ($230+ of self-referential TTL renewal). rc=2 is a MANDATORY stop for
    # the loop prompt, mirroring how BLOCKED forces self-recovery.
    breaker_rc = None
    try:
        br = noop_breaker(ws, state_fingerprint(ws))
        if br["tripped"]:
            report["idle_circuit_breaker"] = {
                "tripped": True,
                "consecutive_noop": br["consecutive_noop"],
                "threshold": br["threshold"],
            }
            try:
                out.write_text(json.dumps(report, indent=2),
                               encoding="utf-8")
            except Exception:
                pass
            print(f"*** IDLE CIRCUIT BREAKER: {br['consecutive_noop']} "
                  f"consecutive no-op ticks (>= {br['threshold']}) — "
                  f"PARK or end the session (#634) ***")
            breaker_rc = 2
    except Exception:  # noqa: BLE001 — breaker failure must not fail the tick
        breaker_rc = None

    action = report["action_taken"] or "(EMPTY — must be filled: what was dispatched/verified/resolved/reactivated)"
    print(f"heartbeat_tick: {sc} | selfcheck_rc={rc_sc} | renew_rc={rc_renew} | heartbeat_rc={rc_hb} | {hb}")
    if first_failure is not None:
        print(f"*** HEARTBEAT ALERT: step {first_failure['step']} failed (rc={first_failure['rc']}) — re-arm before next dispatch ***")
    print(f"action_taken: {action}")
    print(f"report: {out}")
    # #381: selfcheck rc weighs in — a crashed selfcheck (registry drift at
    # import, failed rebuild) must fail the tick, not ride it silently.
    if breaker_rc is not None:
        return breaker_rc
    return 0 if rc_hb == 0 and rc_renew == 0 and rc_sc == 0 else 1


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
