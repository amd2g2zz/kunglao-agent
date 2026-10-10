#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workguard.py — the DAG actionable-set predicate (event-wakeup topology,
issue 434 design item 1).

Topology finding (no new primitive): in-turn wakes come from the blocking
dispatch return; between-turns wakes from worker completion notifications;
turn-exit is judged by the Stop WORKGUARD (hooks/workguard_gate.py). The
cron heartbeat demotes to a true watchdog. This module is the PURE
predicate the WORKGUARD evaluates at every turn-exit attempt:

    actionable := claims OPEN-or-returnable with no active worker,
                  not PARKed, no blocking wall (budget/deadline),
                  deps satisfied

  non-empty actionable set -> the turn exit is BLOCKED (guidance injected);
  empty                    -> LEGAL SLEEP (all PARKed/blocked/budget-walled).

Anti-runaway by construction: the definition respects PARK and walls, so
sleeping states can never be judged actionable, and the wiring passes
through on stop_hook_active (second stop).

Fields consumed (workspace state, read-only):
  claim-register.yaml   id / status / depends_on / superseded_by /
                        promotion_attempts   (status sets from
                        status_defs — TERMINAL / IN_PROGRESS_STATUSES /
                        SUSPENDED)
  claim_deps.yaml       depends_on map (register fallback per-claim field,
                        same precedence as the sanctioned scorer)
  runs/worker-status-*.md  (+ every worker worktree) via the lib_kunglao
                        protocol — active workers, stuck list
  .hook_state.json      tier == HARD_PAUSE  -> BUDGET wall (cost gate)
  task_spec.yaml + runs/.heartbeat.json
                        time_budget_minutes elapsed since started_ts ->
                        DEADLINE wall

Fail-open posture: an unreadable register degrades to the empty set with
ONE canonical warn (the guard must never become a session deadlock
source; the degradation is recorded, never silent). An empty or missing
claims list is a legal empty set — a missing register FILE in an otherwise
live workspace also warns once.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation

from status_defs import IN_PROGRESS_STATUSES, SUSPENDED, TERMINAL

#: Worker capacity (worker_budget MAX_WORKERS / convergence WORKER_CAP —
#: restating per-module would rot; the guard imports the worker-protocol
#: owner's constant when available and pins the same value as fallback).
WORKER_CAP = 3

WHY_DISPATCHABLE = "dispatchable"
WHY_RETURNED = "returned-worker"


def _load_claims(ws: Path) -> tuple[list[dict], bool]:
    """Register read: (claims, ok). ok=False on every unreadable face —
    the caller degrades to the empty set with the warn already emitted
    here (one trace, one place)."""
    p = Path(ws) / "claim-register.yaml"
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        warn("workguard_register", f"{type(exc).__name__}: {p}: {exc}")
        return [], False
    import yaml
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        warn("workguard_register", f"unparseable {p}: {exc}")
        return [], False
    claims = data.get("claims")
    if claims is None:
        warn("workguard_register", f"{p}: no claims list — empty verdict")
        return [], True
    if not isinstance(claims, list):
        warn("workguard_register", f"{p}: claims is not a list")
        return [], False
    return [c for c in claims if isinstance(c, dict)], True


def _deps_map(ws: Path, claims: list[dict]) -> dict[str, list[str]]:
    """The dependency graph: claim_deps.yaml depends_on when populated,
    else the register's per-claim depends_on field (the sanctioned
    scorer's precedence). Read failures degrade to the register face."""
    depends_on: dict = {}
    p = Path(ws) / "claim_deps.yaml"
    if p.is_file():
        try:
            import yaml
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            graph = data.get("depends_on") or {}
            if isinstance(graph, dict):
                depends_on = graph
        except (OSError, ValueError) as exc:
            warn("workguard_deps", f"{type(exc).__name__}: {p}: {exc}")
    if not depends_on:
        depends_on = {str(c["id"]): list(c.get("depends_on") or [])
                      for c in claims if c.get("id") and c.get("depends_on")}
    return depends_on


def _worker_faces(ws: Path):
    """(active_count, stuck_list) via the worker-liveness protocol owner
    (lib_kunglao — the single parse point). Failure -> (0, []) with one
    warn trace. The protocol's own unknown-status rule already counts
    invisible workers active inside its scan, so this outer failure face
    is the honest 'cannot see' verdict; the register status still gates
    the returned-worker claim (IN_PROGRESS with zero VISIBLE workers)."""
    try:
        from _hooks_path import load_hooks_lib
        mod = load_hooks_lib()
        states = mod.iter_worker_states(ws)
        return mod.scan_active_workers(ws, states=states)
    except Exception as exc:  # noqa: BLE001 — see docstring; guard never crashes
        warn("workguard_workers", f"{type(exc).__name__}: {exc}")
        return 0, []


def _budget_wall(ws: Path) -> dict | None:
    """tier == HARD_PAUSE in .hook_state.json: the cost gate paused
    non-essential work — no dispatch is sanctioned while it stands."""
    import json
    p = Path(ws) / ".hook_state.json"
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(state, dict) and state.get("tier") == "HARD_PAUSE":
        return {"wall": "budget",
                "detail": "hook state tier HARD_PAUSE — cost gate"}
    return None


def _deadline_wall(ws: Path, now: datetime) -> dict | None:
    """task_spec.time_budget_minutes > 0 and the run exceeded it since the
    heartbeat start — the operator-set deadline passed. Missing spec or
    heartbeat start = no wall (fail-open; there is nothing to measure)."""
    p = Path(ws) / "task_spec.yaml"
    if not p.is_file():
        return None
    try:
        import yaml
        spec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError) as exc:
        warn("workguard_deadline", f"{type(exc).__name__}: {p}: {exc}")
        return None
    budget = spec.get("time_budget_minutes")
    if budget is None:
        budget = (spec.get("constraints") or {}).get("time_budget_minutes")
    try:
        budget = float(budget or 0)
    except (TypeError, ValueError):
        return None
    if budget <= 0:
        return None
    import json
    hb = Path(ws) / "runs" / ".heartbeat.json"
    try:
        started = json.loads(hb.read_text(encoding="utf-8")).get("started_ts")
        started_dt = datetime.fromisoformat(
            str(started).replace("Z", "+00:00"))
    except (OSError, ValueError, TypeError):
        return None  # no measurable start -> no wall (fail-open)
    elapsed_min = (now - started_dt).total_seconds() / 60
    if elapsed_min > budget:
        return {"wall": "deadline",
                "detail": f"time budget {budget:g} min elapsed "
                          f"({elapsed_min:.0f} min since heartbeat start)"}
    return None


def _deps_satisfied(claim: dict, depends_on: dict[str, list[str]],
                    terminal: set[str], superseded: set[str]) -> bool:
    """Every depends_on parent is terminal (or terminal-by-replacement —
    the supersession consult mirrors the sanctioned scorer's register
    face). Unknown parent ids count as unsatisfied: the conservative
    direction for a guard is sleep, not runaway."""
    cid = str(claim.get("id"))
    for parent in depends_on.get(cid, []) or list(
            claim.get("depends_on") or []):
        p = str(parent)
        if p not in terminal and p not in superseded:
            return False
    return True


def actionable_set(ws: Path, *, now: datetime | None = None) -> dict:
    """The pure WORKGUARD predicate. Returns:

        {"claims": [{"id", "why"}],       actionable, ordered (returned
                                          faces first — settle before
                                          dispatch), then register order
         "walls":  [{"wall", "detail"}],  standing blocking walls
         "active_workers": int, "free_slots": int,
         "legal_sleep": bool}             claims == []

    Walls gate BOTH faces (a paused/deadline'd run may not dispatch nor
    re-dispatch; settlement stays legal only because it is not this
    guard's job to force it — the watchdog and the operator own paused
    runs).
    """
    ws = Path(ws)
    now = now or datetime.now(timezone.utc)
    claims, _ok = _load_claims(ws)
    walls = [w for w in (_budget_wall(ws), _deadline_wall(ws, now)) if w]
    active, _stuck = _worker_faces(ws)
    # local-fix (owner ruling 2026-10-10): a FRESH waiting worker is ALIVE —
    # it parked per the WAIT contract precisely to await verification, and
    # the pre-fix count (in-progress only) misread that verify-wait window as
    # "returned unsettled", demanding settlement before the red-team verdict
    # existed (the exact order the contract forbids). FRESHNESS filters
    # zombie waiters: a killed worker leaves a waiting tail whose mtime ages
    # out of the window and must not absorb the guard forever.
    waiting_live = 0
    try:
        from _hooks_path import load_hooks_lib as _lhl
        _mod = _lhl()
        _cut = now - timedelta(minutes=10)
        waiting_live = sum(
            1 for s in _mod.iter_worker_states(ws)
            if s.get("status") == "waiting"
            and s.get("mtime") is not None and s["mtime"] >= _cut)
    except Exception:  # noqa: BLE001 — counting must not block the guard
        waiting_live = 0
    live = active + waiting_live
    free_slots = max(0, WORKER_CAP - live)
    depends_on = _deps_map(ws, claims)
    terminal = {str(c["id"]) for c in claims
                if c.get("id") and str(c.get("status")) in TERMINAL}
    superseded = {str(c["id"]) for c in claims
                  if c.get("id") and c.get("superseded_by")}

    actionable: list[dict] = []
    if not walls:
        # returned-worker faces first: an IN_PROGRESS claim with zero
        # live workers is a dispatch that came back unsettled — settling
        # it outranks new dispatches (the settle-then-dispatch order).
        if live == 0:
            actionable.extend(
                {"id": str(c["id"]), "why": WHY_RETURNED}
                for c in claims
                if c.get("id")
                and str(c.get("status")) in IN_PROGRESS_STATUSES)
        actionable.extend(
            {"id": str(c["id"]), "why": WHY_DISPATCHABLE}
            for c in claims
            if c.get("id")
            and str(c.get("status")) not in TERMINAL
            and str(c.get("status")) not in IN_PROGRESS_STATUSES
            and str(c.get("status")) not in SUSPENDED
            and _attempts_left(c)
            and free_slots > 0
            and _deps_satisfied(c, depends_on, terminal, superseded))
    return {"claims": actionable, "walls": walls,
            "active_workers": active, "free_slots": free_slots,
            "legal_sleep": not actionable}


def _attempts_left(claim: dict) -> bool:
    """promotion_attempts < 3 — the dead-letter band is not dispatchable
    (mark_dead owns the terminal write; dirty values read as 0, the
    per-claim tolerance convention)."""
    try:
        return int(claim.get("promotion_attempts", 0) or 0) < 3
    except (TypeError, ValueError):
        return True


def turn_exit_guidance(ws: Path, result: dict | None = None) -> str:
    """The next-decision guidance injected with a BLOCK decision. Names
    the actionable claims, the action per face, and — through the
    strategy seam — the current round strategy sections when a strategy
    object exists (absent object renders nothing)."""
    res = result if result is not None else actionable_set(ws)
    ws = Path(ws)
    lines: list[str] = ["WORKGUARD: turn exit refused — the DAG still has "
                        "actionable work (event-wakeup topology)."]
    returned = [c["id"] for c in res["claims"] if c["why"] == WHY_RETURNED]
    dispatchable = [c["id"] for c in res["claims"]
                    if c["why"] == WHY_DISPATCHABLE]
    if returned:
        lines.append(
            f"worker(s) returned for {', '.join(returned)} — settle the "
            f"results (verify facts, update claim-register) then re-dispatch "
            f"or PARK with a wake_condition.")
    if dispatchable:
        lines.append(
            f"dispatchable claims {', '.join(dispatchable)} — dispatch the "
            f"top-ranked action (priority_ratio) or PARK with a "
            f"wake_condition; do not idle with a free slot.")
    lines.append(
        "Exit becomes legal when the actionable set is empty (all "
        "PARKed/blocked/walled) — recompute by ending the turn again.")
    try:
        import strategy_sections
        sections = strategy_sections.render(ws)
        if sections:
            lines.append(sections)
    except Exception as exc:  # noqa: BLE001 — the seam must never break the guard
        warn("workguard_strategy", f"{type(exc).__name__}: {exc}")
    return "\n".join(lines)
