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
  9. mechanisms       — #878: registry-driven scheduling pass. The tick is
                        the ONLY time host; every mechanism declared in
                        scripts/mechanisms.yaml (trigger/cost_class/
                        cockpit_signal schema-gated, 不入册不许跑) is
                        scheduled here — cheap gates first, expensive
                        mechanisms queued, single-pass time cap. Legacy
                        report keys (env_state/monitor/feedback/
                        verify_watch/rollup_sweep/think/backtrack) are
                        back-filled from the scheduler results; the full
                        face rides report["mechanisms"]. Think-seat
                        contract unchanged: a waiting seat REPLACES the
                        empty action_taken (#711 E1). Whole pass is
                        advisory — never weighed into rc/alert.

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
from liveness_policy import (  # noqa: E402
    HEARTBEAT_STALE_MINUTES, RENEW_MARGIN_LOW_MINUTES)
RENEW_MARGIN_LOW_LINE = "[hooks] renewal margin low (<10 min) — check tick cadence vs 30-min TTL"

# #863 Family C: workspace resolution is single-sourced in ws_layout
# (the #228 strict family: arg wins, probe, exit 2 — never guess).
from ws_layout import resolve_strict as _resolve_ws  # noqa: E402


from harness_common import utc_now_z as utc_now  # #863 Family F: single source (was a local def)


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


def _all_workers_waiting(ws: Path, *, now: 'datetime.datetime | None' = None) -> bool:
    """True when zero workers are active and at least one is WAITING with
    a FRESH heartbeat (wait-flag mtime within HEARTBEAT_STALE_MINUTES).

    A stable state fingerprint with every worker parked in the wait loop is
    idle spin-down (delivered workers heartbeat-polling for the next
    dispatch), not a stuck loop — the breaker must not trip on it. But the
    wait flag itself is a heartbeat: a fleet whose flags have all gone
    stale is a DEAD fleet mid-wait, not an idle one — without the
    freshness guard such a fleet would latch the exemption forever and
    the breaker would never rc=2 on it. The worker-liveness protocol is
    loaded by explicit path: the lib_kunglao name has hooks/scripts twins
    and ambient sys.path order must not decide which one answers. Any
    failure -> False (the breaker keeps its teeth)."""
    try:
        # #863 Family B + #671: scripts→hooks loads go through the
        # append-only bridge (_hooks_path), never a raw insert(0) — the
        # canonical loader caches the hooks twin under its own name.
        from _hooks_path import load_hooks_lib
        mod = load_hooks_lib()
        states = mod.iter_worker_states(ws)
        active, _stuck = mod.scan_active_workers(ws, states=states)
        waiting = [s for s in states if s["status"] == mod.WAITING_WORKER_STATUS]
        if active != 0 or not waiting:
            return False
        now = now or datetime.datetime.now(datetime.timezone.utc)
        cutoff = datetime.timedelta(minutes=HEARTBEAT_STALE_MINUTES)
        fresh = [s for s in waiting if (now - s["mtime"]) <= cutoff]
        return len(fresh) > 0
    except Exception:  # noqa: BLE001 — breaker failure must not fail the tick
        return False


def noop_breaker(ws: Path, current_hash: str,
                 threshold: int | None = None) -> dict:
    """#634 Part B: no-progress circuit breaker state machine.

    Same content hash as the previous tick → consecutive_noop += 1; any
    change resets. At >= threshold (env KUNGLAO_NOOP_BREAKER_N, default 6)
    the breaker trips: the loop prompt treats rc=2 as a mandatory stop,
    not a warning. One healthy-freeze exemption: when the freeze is
    explained by workers WAITING (zero active, >=1 waiting) the breaker
    stays quiet with reason "all-workers-waiting" — idle spin-down, not a
    stall. Pure state helper — main() owns persistence+rc.
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
    if count >= n and _all_workers_waiting(ws):
        return {"tripped": False, "reason": "all-workers-waiting",
                "consecutive_noop": count, "threshold": n}
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


def _run_mechanisms(ws: Path, runner) -> dict:
    """#878 mechanism-scheduler face: one registry-driven scheduling pass
    (mechanisms.yaml, schema-gated + fail-closed on a broken registry),
    with the legacy tick-report keys back-filled from the scheduler results.

    The migration moves the TRIGGER, not the report contract: the loop
    prompt and the per-step wiring tests still consume
    env_state / monitor / feedback / verify_watch / rollup_sweep / think /
    backtrack verbatim, and `runner` stays THIS module's execution seam so
    per-script wiring keeps its monkeypatch point. Returns
    {"mechanisms": <compact face>, <legacy_key>: <result>, ...}."""
    import mechanism_scheduler as ms
    sched = ms.run_due(ws, runner=runner)
    payload = {"mechanisms": {
        "ts": sched["ts"], "ran": sched["ran"], "skipped": sched["skipped"],
        "dropped": sched["dropped"], "events_seen": sched["events_seen"],
        "budget_s": sched["budget_s"], "elapsed_ms": sched["elapsed_ms"],
        "error": sched["error"],
        "mechanisms": sched["mechanisms"]}}
    for name, key in ms.LEGACY_REPORT_KEYS.items():
        res = sched["results"].get(name)
        if res is not None:
            payload[key] = dict(res)
    return payload


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
    # #878: registry-driven mechanism scheduling — the tick is the ONLY time
    # host, so the advisory children are no longer hand-wired here. The
    # scheduler walks mechanisms.yaml (schema gate: trigger/cost_class/
    # cockpit_signal prerequisites, 不入册不许跑), evaluates cheap gates
    # first, queues expensive mechanisms by cost class, and enforces the
    # single-pass time cap. Fail-open like every other watcher: a crashed
    # scheduler is recorded and NEVER fails the tick. Sits where the old
    # hand-wired advisory block sat — before the report write and before the
    # cockpit sample + snapshot, so both still reflect the post-retro lag.
    try:
        payload = _run_mechanisms(ws, runner=run)
    except Exception as exc:  # noqa: BLE001 — a crashed scheduler never fails the tick
        payload = {"mechanisms": {"error": [f"scheduler unavailable: {exc}"],
                                  "ran": [], "skipped": [], "dropped": []}}
    report["mechanisms"] = payload.pop("mechanisms")
    report.update(payload)
    # #759 H1: THINK seat contract — a seat that REPORTS waiting with an
    # artifact substitutes action_taken (idle != EMPTY, #711 E1); anything
    # else keeps the orchestrator-filled #237 contract. Guarded: a scheduler
    # face without the think key (crash / registry fail-closed) skips too.
    if isinstance(report.get("think"), dict):
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

    # #873: per-checkpoint 座舱采样——V/D/ETA + cost/burn 落账。
    # mission_ledger 缺失的旧 workspace 跳过（零噪声）；异常 fail-open。
    try:
        if (ws / "runs" / "mission_ledger.yaml").exists():
            from tuition_curve import cockpit_summary
            kunglao_log.emit(
                Path(ws), actor="heartbeat_tick",
                action="cockpit_sample",
                detail=json.dumps(cockpit_summary(ws),
                                  ensure_ascii=False))
    except Exception:  # noqa: BLE001 — cockpit 采样永不打断 tick
        pass

    # #883: pre-write the statusline health snapshot (O(1) atomic; the user's
    # combined-statusline.mjs only reads this file — zero spawn). Fail-open
    # like the cockpit sample above: a snapshot crash must never fail the tick.
    try:
        import statusline_snapshot as _sls
        _sls.write_snapshot(ws)
    except Exception:  # noqa: BLE001 — 快照永不打断 tick
        pass

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
