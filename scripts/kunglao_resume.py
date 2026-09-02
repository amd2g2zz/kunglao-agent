#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao_resume.py — crash/reboot breakpoint recovery brief (issue #466).

Scope split vs scripts/external_kicker.py (#39) — design D1
(openspec/changes/issue-466-resume-subcommand/design.md):
  kicker = the DYING session: OS cron detects deadness and WRITES
           (settings re-registration, prompt staging, spawns `claude -p`).
  resume = the CRASHED workspace: a human/orchestrator in a FRESH session
           asks "where was this analysis?" and gets a READ-ONLY brief.

READ-ONLY CONTRACT (#466 dispatch constraint): resume writes nothing — no
heartbeat start, no TTL renew, no dispatch, no state file. In particular it
calls convergence_check.decide() directly and NEVER convergence_check.main()
(main() appends to .convergence_ledger.jsonl and emits a kunglao_log event).
Re-arming a dead workspace is init's job (#461 bootstrap, merged fa08fd3);
resume only ADVISES the chain.

Decision source: convergence_check.decide() — the #443 state machine. The
next-step text is a LOOKUP keyed by the decision name (mirrors the
convergence-loop rule §3 table); resume never recomputes a decision.

Exit codes (design D2):
  0  RC_RESUMABLE  state coherent, heartbeat alive, next step actionable
  1  RC_MANUAL     state present, one manual step first (dead heartbeat ->
                   #461 re-arm advice; claim-register missing; BLOCKED/INVALID)
  2  RC_NO_STATE   nothing to resume -> guidance points at /kunglao-agent:init
  1  RC_ERROR      unexpected INTERNAL failure (review F4): same code as
                   RC_MANUAL so the 0/1/2 triage surface stays stable, but
                   labeled on stderr as a tool failure — never presented as
                   a workspace verdict

Usage:
    python scripts/kunglao_resume.py <workspace> [--json]
    python scripts/kunglao.py resume <workspace> [--json]   (unified entry)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import claim_expiry
import convergence_check as cc
import digest_build
import external_kicker as kicker
import hook_activation
import kunglao_log
# #536: workspace template version cross-check (status + resume both print it)
import template_version
from status_defs import ACTIVE_STATUSES, PARTIAL_STATUSES
from kunglao_log import iter_jsonl  # noqa: E402  (#863 Family K single source)

RC_RESUMABLE = 0
RC_MANUAL = 1
RC_NO_STATE = 2
# Review F4: RC_ERROR == RC_MANUAL by design (the triage contract is the
# 0/1/2 surface), but it is a distinct constant and main() labels the
# failure on stderr — an internal crash must never silently wear the
# "needs a manual step" verdict.
RC_ERROR = 1

# Liveness line = the repo-wide mechanical gate (heartbeat.py check +
# worker_budget.check_heartbeat_alive v1.9.28): max(last_tick_ts,
# activity_ts) older than 35 min = dead. Resume predicts whether the NEXT
# dispatch would pass that gate, so it reuses the same predicate via
# external_kicker.session_is_dead (#39 D1 — the single dead-session
# definition). The issue comment's "2x heartbeat period" (10 min) is kept
# as data-age DISPLAY only: a 10-min rc line would false-STALE every
# legitimate quick restart (design D3).
# legitimate quick restart (design D3). #597: minutes constants
# single-sourced in liveness_policy (values unchanged).
from liveness_policy import HEARTBEAT_STALE_MINUTES  # noqa: E402
# Worker-status freshness: kicker D3 constant — an in-progress file older
# than this is a dead session's stale worker, surfaced for reconcile.
from liveness_policy import FRESH_WORKER_MINUTES as WORKER_FRESH_MINUTES  # noqa: E402,F401
# Claim-class staleness: claim_expiry's own line (24 h without activity).
CLAIM_STALE_HOURS = 24
# Plan freshness: issue #466 comment — a plan mtime ≥ 2 days old is drift
# the plan_drift_detector cannot see (it checks claim↔plan mapping, not
# plan freshness).
PLAN_STALE_DAYS = 2
# #603: how many gate-rejection rows the brief renders (bounded summary —
# the full ledger stays in runs/gate-rejections.jsonl).
GATE_REJECTIONS_LAST_N = 5
# Decisions that require a manual step before the loop may continue (both
# map to EXIT_BLOCKED in convergence_check.VERDICTS).
MANUAL_DECISIONS = frozenset({"BLOCKED", "INVALID"})

HEARTBEAT_PATH = Path("runs") / ".heartbeat.json"
# POSIX-literal row/timeline label (Path str is backslashed on Windows)
HEARTBEAT_ROW = "runs/.heartbeat.json"
LEDGER_NAME = kicker.RESUME_LEDGER_NAME  # .convergence_ledger.jsonl

# Next-step lookup — the convergence-loop rule §3 decision table, verbatim
# semantics. Lookup ONLY: the decision itself always comes from cc.decide().
NEXT_STEP_BY_DECISION = {
    "CONVERGED": ("loop is done — run the handoff checklist (blind_gate "
                  "spot-check + kunglao-verify L1 + --heartbeat-check) "
                  "before delivering; do not dispatch"),
    "DISPATCH": ("dispatch the scripts/priority.py top claim (<=3 workers "
                 "cap + tier gate); worker done -> verify facts -> update "
                 "claim-register + _INDEX"),
    "DISPATCH_VERIFIER": ("dispatch an independent verifier for the partial "
                          "fact(s) — no PROVEN without sign-off"),
    "SATURATED": ("poll ALL active workers before anything else (behavior "
                  "#4 — no idle waiting while slots are full)"),
    "BLOCKED": ("self-recovery first (behavior #1: L1 same-MCP mode swap -> "
                "L2 skill setup.sh -> L3 env-fix worker); ladder exhausted "
                "-> escalate to the human"),
    "INVALID": ("fix task_spec primary_questions first — the loop refuses to "
                "run on an invalid value function"),
}
NO_REGISTER_STEP = ("decision unavailable — claim-register.yaml missing; "
                    "restore or re-initialize the register before continuing")
UNKNOWN_DECISION_STEP = ("decision not in the resume lookup table — rerun "
                         "convergence_check.py for the authoritative action")

REARM_ADVICE = (
    "re-arm before continuing (the #461 bootstrap chain — resume itself "
    "never writes):\n"
    "  uv run --project <skill> <skill>/scripts/hook_activation.py <ws> --wire-up\n"
    "  uv run --project <skill> <skill>/scripts/hook_activation.py <ws> --heartbeat-on\n"
    "  CronCreate */5 * * * * (heartbeat_loop_prompt.py output) — accept it "
    "with heartbeat_loop_prompt.py --verify"
)

# SEAM (issue #370 family): decide is injected under a private name so
# tests can pin the decision without building exotic fixtures; production
# always runs the real #443 machine.
from functools import partial
_decide = partial(cc.decide, emit_snapshot=False)  # #466 read-only contract: resume must not write


from harness_common import utc_now as _utc_now  # #863 Family F: single source (was a local def)


def _parse_ts(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fmt_ts(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") \
        if dt else "(none)"


def _age_minutes(dt: datetime | None, now: datetime) -> float | None:
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 60, 1)


# ---------- D2 rc inputs: health ----------

def _heartbeat_health(ws: Path, now: datetime) -> dict:
    """Liveness from runs/.heartbeat.json via the #39 dead-session
    predicate at the 35-min gate line (design D3)."""
    p = ws / HEARTBEAT_PATH
    hb = None
    if p.exists():
        try:
            hb = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            hb = None  # corrupt -> recovery bias: treat as dead
    if hb is None and not p.exists():
        status = "MISSING"
    elif hb is None:
        status = "STALE"  # unreadable file: counts as dead (kicker D1)
    else:
        status = "STALE" if kicker.session_is_dead(
            hb, now, stale_minutes=HEARTBEAT_STALE_MINUTES) else "ALIVE"
    return {
        "status": status,
        "last_tick_ts": (hb or {}).get("last_tick_ts"),
        "activity_ts": (hb or {}).get("activity_ts"),
    }


def _activation_health(ws: Path, now: datetime) -> dict:
    """Activation TTL from .hook_state.json (hook_activation.read_state —
    the activation owner; expiry parse mirrors is_active)."""
    state = hook_activation.read_state(ws)
    if not state:
        return {"status": "MISSING", "expires_at": None, "active_hooks": []}
    exp = _parse_ts(state.get("expires_at"))
    status = "EXPIRED" if (exp is not None and now > exp) else "ACTIVE"
    return {
        "status": status,
        "expires_at": state.get("expires_at"),
        "active_hooks": list(state.get("active_hooks") or []),
    }


# ---------- D3/D4: data age, staleness, degradation ----------

def _mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _newest(pattern_paths) -> datetime | None:
    best = None
    for p in pattern_paths:
        m = _mtime(p)
        if m and (best is None or m > best):
            best = m
    return best


def _stale_claims(ws: Path, now: datetime) -> list[dict]:
    """OPEN/PARTIAL claims untouched beyond claim_expiry's line — reuse
    claim_expiry.last_activity_for (the activity-field owner), never a
    second field list."""
    out = []
    for c in digest_build._claims(ws):  # noqa: SLF001 — digest's yaml parse (design D4)
        status = str(c.get("status") or "").upper()
        if status not in ACTIVE_STATUSES and status not in PARTIAL_STATUSES:
            continue
        last = claim_expiry.last_activity_for(c)
        if last is None:
            continue
        age_h = (now - last).total_seconds() / 3600
        if age_h > CLAIM_STALE_HOURS:
            out.append({"id": c.get("id"), "status": status,
                        "age_hours": round(age_h, 1)})
    return out


def _stale_workers(ws: Path, now: datetime) -> list[dict]:
    """In-progress worker-status files older than the kicker D3 fresh line
    (parse via the #444 protocol through kicker's reader)."""
    out = []
    for wid in kicker._in_progress_workers(ws):  # noqa: SLF001 — fired-predicate reader
        p = ws / "runs" / f"worker-status-{wid}.md"
        age = _age_minutes(_mtime(p), now)
        if age is not None and age > WORKER_FRESH_MINUTES:
            out.append({"worker": wid, "age_min": age})
    return out


def _plan_health(ws: Path, now: datetime) -> dict:
    """global_plan presence/age + D1-family variant warning. The active-
    pointer FIX is #446's (mechanism governance, landed); resume only
    detects and warns."""
    variants = sorted(p.name for p in ws.glob("global_plan*")) if ws.exists() else []
    mtime = _mtime(ws / "global_plan.txt")
    age = _age_minutes(mtime, now)
    return {
        "exists": bool(variants),
        "age_min": age,
        "stale": bool(age is not None and age >= PLAN_STALE_DAYS * 24 * 60),
        "variants": variants,
    }


def _last_structured_event(ws: Path) -> dict | None:
    """Last row of the newest runs/logs/kunglao-*.jsonl (#287 event log).
    kunglao_log owns the location (log_path); it has no read API, so the
    last-line read here is the only new code in the reuse map (design D4)."""
    try:
        logs_dir = kunglao_log.log_path(ws).parent
        files = sorted(logs_dir.glob("kunglao-*.jsonl"))
    except OSError:
        return None
    for p in reversed(files):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for row in iter_jsonl(reversed(lines)):
            if isinstance(row, dict):
                return {"ts": row.get("ts"), "file": p.name,
                        "actor": row.get("actor"), "action": row.get("action")}
    return None


def _open_hypotheses(ws: Path) -> dict:
    """#528: OPEN hypothesis pointers (what re-hydrates at restart) via the
    single hypothesis-layer parser. Reads hypotheses/ ONLY — never notes/
    (the result layer). FAIL_OPEN: no dir / broken layer -> empty."""
    hyp_dir = ws / "hypotheses"
    if not hyp_dir.is_dir():
        return {"open_count": 0, "pointers": []}
    try:
        from hypothesis_store import HypothesisStore
        hyps = HypothesisStore(hyp_dir).list_open()
        return {"open_count": len(hyps),
                "pointers": [{"claim_id": h.claim_id, "hyp_id": h.id}
                             for h in hyps]}
    except Exception:  # noqa: BLE001 — degrade, never block the brief
        return {"open_count": 0, "pointers": []}


def _gate_rejections(ws: Path) -> dict | None:
    """#603: gate-rejections summary from runs/gate-rejections.jsonl — the
    durable ledger hooks/dispatch_gate.py appends one row to per REJECT.

    FAIL_OPEN: absent file -> None (the brief section is simply omitted —
    a workspace with no rejections, or pre-#603, renders unchanged); an
    unreadable/corrupt file also degrades to None (a broken ledger must
    never break the recovery brief). Read-only: this function never
    writes, matching resume's READ-ONLY CONTRACT.

    Returns {"total": int, "last": [rows]} capped at
    GATE_REJECTIONS_LAST_N most recent rows — the ledger is the replay
    source, the brief is a summary, never the whole file.
    """
    p = ws / "runs" / "gate-rejections.jsonl"
    try:
        lines = [ln for ln in
                 p.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.strip()]
    except OSError:
        return None
    if not lines:
        return None  # empty ledger == no rejections == section omitted
    rows = [row for row in iter_jsonl(lines) if isinstance(row, dict)]
    if not rows:
        return None
    return {"total": len(rows), "last": rows[-GATE_REJECTIONS_LAST_N:]}


def _data_age_rows(ws: Path, now: datetime) -> list[dict]:
    """The design D3 matrix as data: one row per declared source with its
    missing/stale verdict. CRITICAL rows are the only rc-moving ones."""
    hb = _heartbeat_health(ws, now)
    act = _activation_health(ws, now)
    plan = _plan_health(ws, now)
    workers = list((ws / "runs").glob("worker-status-*.md")) if (ws / "runs").exists() else []
    register = ws / "claim-register.yaml"
    index = ws / "facts" / "_INDEX.md"
    ledger = ws / LEDGER_NAME
    task_spec = ws / "task_spec.yaml"
    blockers = ws / "blockers"

    def row(source, cls, exists, age_min, flag):
        return {"source": source, "class": cls, "exists": exists,
                "age_min": age_min, "flag": flag}

    ev = _last_structured_event(ws)
    hb_flag = "ok" if hb["status"] == "ALIVE" else "stale"
    act_flag = {"ACTIVE": "ok", "EXPIRED": "expired", "MISSING": "missing"}[act["status"]]
    plan_flag = "plan-stale" if plan["stale"] else ("ok" if plan["exists"] else "missing")

    return [
        row("claim-register.yaml", "claims", register.exists(),
            _age_minutes(_mtime(register), now),
            "ok" if register.exists() else "critical-missing"),
        row("facts/_INDEX.md", "facts", index.exists(),
            _age_minutes(_mtime(index), now),
            "ok" if index.exists() else "missing"),
        row(LEDGER_NAME, "events", ledger.exists(),
            _age_minutes(_mtime(ledger), now),
            "ok" if ledger.exists() else "missing"),
        row("runs/worker-status-*.md", "workers", bool(workers),
            _age_minutes(_newest(workers), now),
            "ok" if workers else "missing"),
        row("task_spec.yaml", "value", task_spec.exists(),
            _age_minutes(_mtime(task_spec), now),
            "ok" if task_spec.exists() else "missing"),
        row("analysis_state.txt", "narrative", (ws / "analysis_state.txt").exists(),
            _age_minutes(_mtime(ws / "analysis_state.txt"), now),
            "ok" if (ws / "analysis_state.txt").exists() else "missing"),
        row("global_plan.txt", "plan", plan["exists"], plan["age_min"], plan_flag),
        row("progress.txt", "narrative", (ws / "progress.txt").exists(),
            _age_minutes(_mtime(ws / "progress.txt"), now),
            "ok" if (ws / "progress.txt").exists() else "missing"),
        row("blockers/", "blockers", blockers.exists() and any(blockers.iterdir()),
            _age_minutes(_mtime(blockers), now),
            "ok" if blockers.exists() and any(blockers.iterdir()) else "missing"),
        row(HEARTBEAT_ROW, "liveness", (ws / HEARTBEAT_PATH).exists(),
            _age_minutes(max(filter(None, [_parse_ts(hb["last_tick_ts"]),
                                           _parse_ts(hb["activity_ts"])]), default=None), now),
            hb_flag),
        row(".hook_state.json", "activation", bool(hook_activation.read_state(ws)),
            _age_minutes(_parse_ts(act["expires_at"]), now), act_flag),
        row("runs/logs/kunglao-*.jsonl", "eventlog", ev is not None,
            _age_minutes(_parse_ts((ev or {}).get("ts")), now),
            "ok" if ev else "missing"),
        # #528: the cold-start 9th file — a missing digest means the
        # restart re-hydrates 8 files (degraded, flagged, never fatal).
        row("runs/digest.md", "digest", (ws / "runs" / "digest.md").exists(),
            _age_minutes(_mtime(ws / "runs" / "digest.md"), now),
            "ok" if (ws / "runs" / "digest.md").exists() else "missing"),
    ]


def _sources_flags(rows: list[dict]) -> dict:
    """{source: 'present'|'missing'} — the degradation flags (design D3)."""
    return {r["source"]: ("present" if r["exists"] else "missing") for r in rows}


# ---------- D5: timeline ----------

def _timeline(ws: Path, now: datetime) -> list[dict]:
    """Breakpoint timeline: every datable signal, oldest -> newest. The
    newest entry is labelled the crash point (the best mechanical
    approximation of where the session died)."""
    entries: list[tuple[datetime, str, str]] = []

    def add(ts, source, note):
        dt = _parse_ts(ts) if isinstance(ts, str) else ts
        if dt is not None:
            entries.append((dt, source, note))

    snap, _rounds = kicker._ledger_last_snapshot(ws)  # noqa: SLF001 — fired-predicate reader
    if snap is not None:
        add(snap.get("ts"), LEDGER_NAME,
            f"last snapshot: decision={snap.get('decision')}")
    hb = None
    if (ws / HEARTBEAT_PATH).exists():
        try:
            hb = json.loads((ws / HEARTBEAT_PATH).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            hb = None  # corrupt file -> recovery bias: no timeline entry
    if isinstance(hb, dict):
        add(hb.get("activity_ts"), HEARTBEAT_ROW, "last tool activity")
        add(hb.get("last_tick_ts"), HEARTBEAT_ROW, "last loop tick")
    ev = _last_structured_event(ws)
    if ev:
        add(ev.get("ts"), "runs/logs/kunglao-*.jsonl",
            f"last event: {ev.get('actor')}/{ev.get('action')}")
    for name in ("task_spec.yaml", "claim-register.yaml", "analysis_state.txt",
                 "global_plan.txt", "progress.txt", "facts/_INDEX.md"):
        m = _mtime(ws / name)
        if m is not None:
            add(m, name, "file mtime")
    workers = list((ws / "runs").glob("worker-status-*.md")) if (ws / "runs").exists() else []
    newest_worker = _newest(workers)
    if newest_worker is not None:
        add(newest_worker, "runs/worker-status-*.md", "newest worker status write")

    entries.sort(key=lambda e: e[0])
    out = [{"ts": _fmt_ts(dt), "source": src, "note": note}
           for dt, src, note in entries]
    if out:
        out[-1]["note"] += " — crash point (newest mechanical signal)"
    return out


# ---------- assembly ----------

def build_brief(ws) -> dict:
    """The whole resume brief. Pure read: no write to any file under ws."""
    ws = Path(ws).resolve()
    now = _utc_now()

    register = ws / "claim-register.yaml"
    has_state = any(p.exists() for p in (
        register, ws / LEDGER_NAME, ws / "facts" / "_INDEX.md", ws / "runs"))

    data_age = _data_age_rows(ws, now)
    heartbeat = _heartbeat_health(ws, now)
    activation = _activation_health(ws, now)
    plan = _plan_health(ws, now)
    blockers = kicker._blocker_ids(ws, None)  # noqa: SLF001 — fired-predicate reader

    decision = _decide(ws) if (has_state and register.exists()) else None
    manual_reasons: list[str] = []
    if has_state and not register.exists():
        manual_reasons.append(
            "claim-register.yaml missing while other state survives — claim "
            "counts untrustworthy, decision withheld")
    if has_state and heartbeat["status"] != "ALIVE":
        manual_reasons.append(
            f"heartbeat {heartbeat['status']} — liveness dead (> "
            f"{HEARTBEAT_STALE_MINUTES} min line), the loop cannot dispatch")
    if decision is not None and decision.get("decision") in MANUAL_DECISIONS:
        manual_reasons.append(
            f"convergence decision {decision['decision']} (exit "
            f"{decision.get('exit_code')}) — manual step required")

    if not has_state:
        rc, verdict = RC_NO_STATE, "NO-STATE"
    elif manual_reasons:
        rc, verdict = RC_MANUAL, "NEEDS-MANUAL"
    else:
        rc, verdict = RC_RESUMABLE, "RESUMABLE"

    advice: list[str] = []
    if heartbeat["status"] != "ALIVE" and has_state:
        advice.append(REARM_ADVICE)
    if plan["variants"] and len(plan["variants"]) > 1:
        advice.append(
            f"global_plan variants coexist ({plan['variants']}) — D1-family "
            "single-source violation; the active-pointer fix is #446's "
            "mechanism governance")
    # #536: workspace template behind skill → one-line upgrade advice
    # (read-only surface: advice never moves rc; env_check is the hard gate)
    try:
        upgrade = template_version.upgrade_warning(ws)
    except RuntimeError:
        upgrade = None
    if upgrade:
        advice.append(upgrade)

    d = decision or {}
    summary = {
        "decision": decision,
        "open_count": d.get("open_count"),
        "partial_count": d.get("partial_count"),
        "active_workers": d.get("active_workers"),
        "free_slots": d.get("free_slots"),
        "worker_cap": d.get("worker_cap"),
        "stuck_workers": d.get("stuck_workers"),
        "active_blockers": d.get("active_blockers", blockers),
        "failure_blocked": d.get("failure_blocked"),
    }
    if not has_state:
        next_step = (f"no resumable state under {ws} — initialize with "
                     f"/kunglao-agent:init <workspace> [--type windows|linux|android|web|macos]")
    elif decision is None:
        next_step = NO_REGISTER_STEP
    else:
        next_step = NEXT_STEP_BY_DECISION.get(str(d.get("decision")),
                                              UNKNOWN_DECISION_STEP)

    return {
        "workspace": str(ws),
        "verdict": verdict,
        "rc": rc,
        "manual_reasons": manual_reasons,
        "health": {
            "claim_register": "present" if register.exists() else "MISSING",
            "heartbeat": heartbeat,
            "activation": activation,
            "blockers": blockers,
        },
        "summary": summary,
        "data_age": data_age,
        "stale_claims": _stale_claims(ws, now),
        "stale_workers": _stale_workers(ws, now),
        "plan": plan,
        "timeline": _timeline(ws, now),
        "hypotheses": _open_hypotheses(ws),
        "gate_rejections": _gate_rejections(ws),
        "next_step": next_step,
        "advice": advice,
        "sources": _sources_flags(data_age),
    }


# ---------- render ----------

def _fmt_count(v) -> str:
    """decide()'s counters (open_count / partial_count / active_workers /
    free_slots / worker_cap) are INTs — active_workers is a COUNT
    (convergence_check._DecideInputs.active: int), never a worker list.
    Render the int directly; '-' only when the decision is withheld
    (register missing — counts unknown, never faked as 0). Review F1:
    `len(active_workers or [])` raised TypeError the instant >=1 worker
    was in flight (`0 or []` had masked the type mismatch)."""
    return str(v) if isinstance(v, int) and not isinstance(v, bool) else "-"


def render_text(brief: dict) -> str:
    b = brief
    L: list[str] = []
    L.append(f"=== RESUME BRIEF: {b['workspace']} ===")
    L.append(f"verdict: {b['verdict']} (rc {b['rc']})")
    if b["rc"] == RC_NO_STATE:
        L.append(f"no resumable state — {b['next_step']}")
        return "\n".join(L) + "\n"

    hb = b["health"]["heartbeat"]
    act = b["health"]["activation"]
    L.append("")
    L.append("## health")
    L.append(f"claim-register: {b['health']['claim_register']}")
    L.append(f"heartbeat: {hb['status']} (last_tick={hb['last_tick_ts']}, "
             f"activity={hb['activity_ts']})")
    L.append(f"activation: {act['status']} (expires_at={act['expires_at']}, "
             f"{len(act['active_hooks'])} active hook(s))")
    L.append(f"blockers: {len(b['health']['blockers'])} "
             f"({', '.join(b['health']['blockers']) or 'none'})")

    L.append("")
    L.append("## state summary (decision from convergence_check.decide — not recomputed)")
    d = b["summary"]["decision"]
    if d is None:
        L.append("decision: WITHHELD (claim-register missing — never approximated)")
    else:
        L.append(f"decision: {d['decision']} (exit {d['exit_code']})")
        L.append(f"action: {d['action']}")
    L.append(f"open claims: {_fmt_count(b['summary']['open_count'])} | partial "
             f"facts: {_fmt_count(b['summary']['partial_count'])} | workers: "
             f"{_fmt_count(b['summary']['active_workers'])}/"
             f"{_fmt_count(b['summary']['worker_cap'])} "
             f"({_fmt_count(b['summary']['free_slots'])} free)")

    L.append("")
    L.append("## data age (per-source, STALE rules by class)")
    L.append("source | class | age_min | flag")
    for r in b["data_age"]:
        L.append(f"{r['source']} | {r['class']} | {r['age_min']} | {r['flag']}")
    if b["stale_claims"]:
        ids = ", ".join(f"{s['id']}({s['age_hours']}h)" for s in b["stale_claims"])
        L.append(f"STALE claims (> {CLAIM_STALE_HOURS}h, claim_expiry line): {ids}")
    if b["stale_workers"]:
        ids = ", ".join(f"{s['worker']}({s['age_min']}m)" for s in b["stale_workers"])
        L.append(f"STALE in-progress workers (> {WORKER_FRESH_MINUTES}m): {ids}")

    L.append("")
    L.append("## breakpoint timeline (oldest -> newest)")
    for e in b["timeline"]:
        L.append(f"{e['ts']}  {e['source']}: {e['note']}")

    # #528: what re-hydrates — OPEN hypothesis pointers (ids only).
    hyps = b.get("hypotheses") or {}
    if hyps.get("open_count"):
        ptrs = ", ".join(f"{p['hyp_id']}({p['claim_id']})"
                         for p in hyps["pointers"])
        L.append("")
        L.append("## open hypotheses (re-hydrate at cold start)")
        L.append(f"open_count: {hyps['open_count']} | {ptrs}")

    # #603: gate-rejections summary (fail-open — section absent when the
    # ledger does not exist; read-only consumer of the REJECT ledger).
    rej = b.get("gate_rejections")
    if rej:
        L.append("")
        L.append(f"## gate-rejections (last {len(rej['last'])} of "
                 f"total: {rej['total']})")
        for r in rej["last"]:
            L.append(f"{r.get('ts', '?')}  {r.get('gate', '?')} rejected "
                     f"{r.get('claim', '?')}: {r.get('msg', '')}")

    L.append("")
    L.append("## next step")
    L.append(b["next_step"])
    for reason in b["manual_reasons"]:
        L.append(f"manual: {reason}")
    for a in b["advice"]:
        L.append(a)
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kunglao_resume.py",
        description="kunglao-agent crash/reboot recovery brief — "
                    "read-only: health, state summary, data age, breakpoint "
                    "timeline, next step (from convergence_check)")
    parser.add_argument("workspace", help="crashed workspace root")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable brief")
    args = parser.parse_args(argv)

    # Review F4 boundary: a resume tool failure is NOT a workspace verdict.
    # Catch, label on stderr, exit RC_ERROR (== 1: the 0/1/2 triage surface
    # stays stable) — never let an internal crash wear RC_MANUAL's meaning
    # or leak a bare traceback.
    try:
        brief = build_brief(Path(args.workspace))
        if args.json:
            print(json.dumps(brief, ensure_ascii=False, indent=2))
        else:
            print(render_text(brief), end="")
    except Exception as exc:  # top-level boundary — the message is the contract
        print(f"kunglao_resume.py: internal error — {exc!r}\n"
              "(this is a resume tool failure, NOT a workspace verdict like "
              "NEEDS-MANUAL; inspect the workspace directly: "
              f"{args.workspace})", file=sys.stderr)
        return RC_ERROR
    return brief["rc"]


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
