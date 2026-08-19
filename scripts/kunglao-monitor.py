#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-monitor — M5 MONITOR standalone CLI (phase 5, E5.3).

Combines heartbeat_check + loop_reconcile + help_watch + stuck_watch +
health_check → TickOutput (schemas/tick-output.json, M5.3 L396-406 frozen).

Background process (2026-08-12, #88): this CLI runs as a BACKGROUND process —
its output is advisory. The loop's scheduled tick actions (re-dispatch /
verify / TaskStop) NEVER wait for monitor output; the tick advances on file
state (worker-status-*.md freshness / .heartbeat.json). The monitor's `next`
is a suggestion, not a gate.

Isolation boundary (#88): no agent-team features
(CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS never enabled / no teammates / no team
setup / no worker↔worker messaging); SendMessage orchestrator→worker ping is
the sanctioned heartbeat channel.

Reused as-is: loop_state.reconcile (TEMP mtime → loop-state),
convergence_health.assess (HEALTHY/STALLED/SPINNING),
active_intervention.find_help_requests/find_responses,
backtrack_gate.parse_status/parse_backtrack.

Usage: python kunglao-monitor.py <ws> [--json]
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

HEARTBEAT_FILE = "runs/.heartbeat.json"
HEARTBEAT_MAX_MIN = 35          # same threshold as worker_budget.check_heartbeat_alive
STUCK_MIN = 20                  # same as backtrack_gate --stuck-min default
VALID_BACKTRACK_DECISIONS = ("continue", "retry_different", "escalate", "redispatch")
# #475: env-state drift threshold — mirrors hooks/worker_budget
# ENV_STATE_TTL_MINUTES (advisory threshold here, reject line there is 2x).
ENV_STATE_TTL_MINUTES = 30


def utc_now() -> str:
    """UTC ISO-8601, second precision, Z suffix (schema ts pattern)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_now_dt() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def heartbeat_check(ws: Path) -> tuple[str, str]:
    """M5.2 L382: check runs/.heartbeat.json last_tick_ts (< 35min) → (alive|STALE, detail).

    Missing/corrupt file → STALE + re-register hint (M5.5 L424-425).
    """
    path = ws / HEARTBEAT_FILE
    if not path.exists():
        return ("STALE", "no runs/.heartbeat.json — monitoring never registered")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        last_str = data.get("last_tick_ts", "")
        last = datetime.datetime.fromisoformat(last_str.replace("Z", "+00:00"))
    except Exception as exc:
        return ("STALE", f".heartbeat.json unreadable ({exc}) — re-register (--heartbeat-on)")
    age = _utc_now_dt() - last
    if age > datetime.timedelta(minutes=HEARTBEAT_MAX_MIN):
        return ("STALE", f"last tick {last_str} ({int(age.total_seconds() // 60)} min > {HEARTBEAT_MAX_MIN})")
    return ("alive", f"last tick {last_str}")


def loop_reconcile(ws: Path) -> dict:
    """M5.2 L385: TEMP mtime → loop-state; diff vs previous snapshot → gone events.

    TEMP glob failure / import failure → empty state (no crash, M5.5 L423);
    no snapshot → treat everything as first sight (NEW).
    """
    prev: dict = {}
    prev_path = ws / "runs" / "loop-state.json"
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}
    try:
        from loop_state import reconcile
        state = reconcile(ws)
    except Exception as exc:
        state = {"ts": utc_now(), "agent_count": 0, "active": [], "stale": [],
                 "agents": {}, "error": str(exc)}
    prev_active = set(prev.get("active") or [])
    current_ids = set(state.get("agents") or {})
    gone = sorted(prev_active - current_ids)
    try:
        (ws / "runs").mkdir(parents=True, exist_ok=True)
        prev_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # snapshot write failure must not crash — next tick treats all as first sight
    return {"state": state, "gone_events": gone, "prev_ts": prev.get("ts")}


def help_watch(ws: Path) -> list[str]:
    """M5.1 help_watch: worker-status files with unanswered help_requests (active_intervention semantics)."""
    try:
        import active_intervention as ai
    except Exception:
        return []
    reqs = ai.find_help_requests(ws)
    if not reqs:
        return []
    responded = {r.get("claim_id") for r in ai.find_responses(ws)}
    return sorted({r["file"] for r in reqs if r.get("claim_id") not in responded})


def stuck_watch(ws: Path) -> list[str]:
    """M5.1 stuck_watch: worker files in_progress ≥20min with no valid backtrack."""
    try:
        import backtrack_gate as bg
    except Exception:
        return []
    workers_dir = ws / "runs"
    if not workers_dir.exists():
        return []
    now = _utc_now_dt()
    stuck: list[str] = []
    for p in sorted(workers_dir.glob("worker-status-*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if bg.parse_status(text) != "in_progress":
            continue
        age = now - datetime.datetime.fromtimestamp(p.stat().st_mtime, tz=datetime.timezone.utc)
        if age < datetime.timedelta(minutes=STUCK_MIN):
            continue
        bt = bg.parse_backtrack(text)
        if bt is None or bt.get("decision", "").lower() not in VALID_BACKTRACK_DECISIONS:
            stuck.append(p.name)
    return stuck


def health_check(ws: Path) -> dict:
    """M5.2 L388: .convergence_ledger.jsonl trajectory → HEALTHY|STALLED|SPINNING.

    NO_DATA (no ledger / not assessable) → HEALTHY (cannot declare STALLED
    without evidence); the raw field keeps its original value.
    """
    try:
        import convergence_health as ch
        r = ch.assess(ch._read_ledger(ws))
    except Exception as exc:
        return {"verdict": "HEALTHY", "raw": "NO_DATA",
                "detail": f"convergence_health unavailable ({exc})"}
    raw = r.get("verdict", "NO_DATA")
    verdict = raw if raw in ("HEALTHY", "STALLED", "SPINNING") else "HEALTHY"
    return {"verdict": verdict, "raw": raw, "detail": r.get("action", ""),
            "rounds": r.get("rounds", 0)}


def decide_next(hb: str, health: dict, help_reqs: list[str], stuck: list[str],
                gone: list[str], active_workers: int) -> str:
    """M5.4 L418 mechanical next-step inference (priority: heartbeat → health → help → stuck → gone → idle)."""
    if hb == "STALE":
        return "re-register heartbeat: python hook_activation.py <ws> --heartbeat-on"
    if health["verdict"] == "SPINNING":
        return health["detail"] or "STOP dispatching — spinning (see convergence_health)"
    if health["verdict"] == "STALLED":
        return health["detail"] or "diagnose before dispatching — stalled (see convergence_health)"
    if help_reqs:
        return f"respond to help_request(s): {', '.join(help_reqs)} (SendMessage workaround / redispatch / B1d)"
    if stuck:
        return f"force `## backtrack` on stuck worker(s): {', '.join(stuck)}"
    if gone:
        return f"reconcile ledger for gone agent(s): {', '.join(gone)}"
    if active_workers == 0:
        return "converged-check: run convergence_check.py (no active workers)"
    return "poll active workers (SATURATED — no free slot)"


def env_drift_watch(ws: Path) -> dict:
    """#475: read runs/env-state.json → advisory drift decision.

    ADVISORY ONLY (#88 contract): the returned field rides the tick output;
    it never gates a tick action. Missing file → NO_DATA; any FAIL entry or
    entry older than ENV_STATE_TTL_MINUTES (mirrors worker_budget) → DRIFT
    with the capability list + ages; else OK. Corrupt JSON → NO_DATA.
    """
    p = ws / "runs" / "env-state.json"
    if not p.exists():
        return {"status": "NO_DATA", "drifted": [], "detail": "no runs/env-state.json"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # #475 review HIGH-1: wrong-shape JSON (list top-level / string
        # entries) parses fine then crashes .get — guard both, NO_DATA path.
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
        per = data.get("per_capability") or {}
        if not isinstance(per, dict):
            raise ValueError("per_capability is not an object")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "NO_DATA", "drifted": [], "detail": f"env-state unreadable ({exc})"}
    now = _utc_now_dt()
    drifted: list[str] = []
    for name, entry in per.items():
        if not isinstance(entry, dict):
            continue  # wrong-shape entry — not evidence
        if entry.get("status") == "fail":
            drifted.append(name)
            continue
        try:
            ts = datetime.datetime.fromisoformat(
                str(entry.get("last_probe_ts", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if now - ts > datetime.timedelta(minutes=ENV_STATE_TTL_MINUTES):
            drifted.append(name)
    if drifted:
        return {"status": "DRIFT", "drifted": sorted(drifted),
                "detail": "env drifted: " + ", ".join(sorted(drifted))}
    return {"status": "OK", "drifted": [], "detail": "env fresh and passing"}


def tick(ws: Path) -> dict:
    """M5.4 L410-420: heartbeat → loop_reconcile → help/stuck/health → next → TickOutput."""
    hb, hb_detail = heartbeat_check(ws)
    ls = loop_reconcile(ws)
    state = ls["state"]
    active_workers = len(state.get("active") or [])
    help_reqs = help_watch(ws)
    stuck = stuck_watch(ws)
    health = health_check(ws)
    gone = ls["gone_events"]
    return {
        "ts": utc_now(),
        "heartbeat": hb,
        "active_workers": active_workers,
        "stale_agents": state.get("stale") or [],
        "gone_events": gone,
        "help_requests": help_reqs,
        "stuck": stuck,
        "health": health["verdict"],
        "next": decide_next(hb, health, help_reqs, stuck, gone, active_workers),
        "heartbeat_detail": hb_detail,
        "health_detail": health["detail"],
        # #475: env drift — ADVISORY (never gates a tick, #88 contract)
        "env_drift": env_drift_watch(ws),
    }


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI: python kunglao-monitor.py <ws> [--json]."""
    ap = argparse.ArgumentParser(description="kunglao-monitor — M5 MONITOR tick")
    ap.add_argument("ws", type=Path, help="workspace root")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    args = ap.parse_args(argv)
    out = tick(args.ws)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"heartbeat={out['heartbeat']} | active_workers={out['active_workers']} | "
              f"health={out['health']} | help={out['help_requests']} | stuck={out['stuck']}")
        print(f"next: {out['next']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
