# -*- coding: utf-8 -*-
"""rlvr/liveness.py — heartbeat continuity core (#754 E2 + #830 faces).

Issue #420 Phase 2: the liveness JUDGMENT CORE moved here from
scripts/heartbeat.py (which keeps the CLI faces — register / check /
off / mark-loop — as thin adapters calling this module). The shared
verdict ``evaluate_tick_continuity`` is single-sourced here so the three
consumers (hooks/worker_budget_sinks.check_heartbeat_alive, heartbeat.py
--heartbeat-check, heartbeat_loop_prompt --verify) can never drift apart.

Constants: scripts/liveness_policy.py stays THE liveness-minutes source
(#597 adjudication); this module re-exports, never redefines.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

# #597: value single-sourced in liveness_policy (THE liveness-minutes
# source); re-exported here, never redefined.
from liveness_policy import (CONTINUITY_WINDOW_HOURS,  # noqa: F401 (#4 window)
                             CONTINUITY_WINDOW_TICKS,
                             STALE_MINUTES,
                             TICK_INTERVAL_DEFAULT_MIN)
from harness_common import utc_now_z
from kunglao_log import iter_jsonl  # #863 Family K single source

TICK_HISTORY_KEY = "tick_history"
# Anti-bloat cap: history keeps at most the 12 most recent ticks inside the
# 35-min liveness window (12 x 5min cadence >> any real analysis session's
# renewal needs; a bounded list can never grow without limit).
TICK_HISTORY_CAP = 12

# #830: durable tick sidecar - runs/.heartbeat.log (JSONL, append-only)
HEARTBEAT_LOG_NAME = ".heartbeat.log"


def append_tick(state: dict, *, now: datetime | None = None) -> dict:
    """Append one tick to state[TICK_HISTORY_KEY] (NEW dict, no mutation).

    Housekeeping on every append: drop entries older than the STALE_MINUTES
    window (keeps any adjacent pair within one lifetime), then cap to the
    most recent TICK_HISTORY_CAP entries. Callers persist the returned dict.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:  # tolerate naive test clocks — treat as UTC
        moment = moment.replace(tzinfo=timezone.utc)
    base = state if isinstance(state, dict) else {}
    history = [t for t in (base.get(TICK_HISTORY_KEY) or []) if isinstance(t, str)]
    pruned = [t for t in history if _parse_hb_ts(t) is not None
              and moment - _parse_hb_ts(t) <= timedelta(minutes=STALE_MINUTES)]
    out = dict(base)
    out[TICK_HISTORY_KEY] = (pruned + [moment.strftime("%Y-%m-%dT%H:%M:%SZ")])[-TICK_HISTORY_CAP:]
    return out


def heartbeat_log_path(workspace: Path) -> Path:
    """Durable tick sidecar path: <ws>/runs/.heartbeat.log."""
    return Path(workspace) / "runs" / HEARTBEAT_LOG_NAME


def append_tick_log(workspace, actor: str = "tick") -> None:
    """#830: append one durable tick line {"ts","actor"} to
    runs/.heartbeat.log (JSONL, append-only).

    Dedicated sidecar, NOT the convergence ledger: (a) the incident itself
    deleted the ledger twice - anchoring liveness in it inherits the same
    weakness; (b) the kunglao event stream is TODAY-dated (midnight split)
    and its row schema is a cross-PR contract (#818 schema drift broke PR
    #836 CI) - a single-file sidecar keeps the liveness substrate
    contract-free and midnight-stable. Append-only discipline: writers only
    ever append; no rotation (growth ~288 lines/day at 5-min cadence).
    """
    log = heartbeat_log_path(workspace)
    log.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": utc_now_z(), "actor": str(actor)})
    with log.open("a", encoding="utf-8") as fh:
        fh.write(line + chr(10))


def reset_continuity_baseline(workspace: Path, *, force: bool = False,
                              max_age_hours: int = 24) -> dict:
    """#415.3: gated continuity-baseline reset for VERIFIED FRESH DEPLOYS.

    Deploy-day reality: a durable cron registered MID-SESSION does not fire
    until the next Claude Code session, so the sidecar's only rows are
    hook/register entries and the registration tick ages past the stale
    line — "wait a day" must not be the only recovery. This face rotates
    the sidecar (runs/.heartbeat.log -> .heartbeat.log.reset-<ts>) and
    rebuilds tick_history from one fresh registration tick, so continuity
    re-arms from NOW.

    Gate (fail-closed by default):
      - any REAL tick row (actor="tick") in the sidecar -> REFUSE: real
        cron ticks prove the loop fired; a stall then means a REAL dead
        cron and the re-arm chain is the remedy, not a reset.
      - the existing heartbeat state older than max_age_hours -> REFUSE
        (only a fresh deploy may reset).

    Returns {"status": "reset"|"refused", "reason"?, "rotated_to"?}.
    """
    import time as _time
    log = heartbeat_log_path(workspace)
    real_ticks = 0
    if log.exists():
        for obj in iter_jsonl(
                log.read_text(encoding="utf-8",
                              errors="replace").splitlines()):
            if isinstance(obj, dict) and str(obj.get("actor")) == "tick":
                real_ticks += 1
    if real_ticks and not force:
        return {"status": "refused",
                "reason": f"{real_ticks} real tick row(s) present — the cron "
                          f"has fired; a stall is REAL, use the re-arm "
                          f"chain (heartbeat_tick.py <ws>), not a reset"}
    state_path = workspace / "runs" / ".heartbeat.json"
    if not state_path.is_file():
        return {"status": "refused", "reason": "no heartbeat state — "
                "nothing to reset (register first)"}
    try:
        age_s = _time.time() - state_path.stat().st_mtime
    except OSError as exc:
        return {"status": "refused", "reason": f"state unreadable: {exc}"}
    if age_s > max_age_hours * 3600 and not force:
        return {"status": "refused",
                "reason": f"heartbeat state is {int(age_s // 3600)}h old — "
                          f"only a fresh deploy (<{max_age_hours}h) may "
                          f"reset; use the re-arm chain instead"}
    stamp = _time.strftime("%Y%m%dT%H%M%SZ", _time.gmtime())
    rotated_to = None
    if log.exists():
        rotated = workspace / "runs" / f".heartbeat.log.reset-{stamp}"
        log.replace(rotated)
        rotated_to = rotated.name
    now_z = utc_now_z()
    state = {"ts": now_z, "interval_min": TICK_INTERVAL_DEFAULT_MIN,
             "tick_history": [now_z],
             "continuity_baseline_reset": now_z}
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False)
                          + "\n", encoding="utf-8")
    return {"status": "reset", "rotated_to": rotated_to}


def newest_sidecar_ts(workspace) -> str | None:
    """#618: newest durable tick ts from runs/.heartbeat.log (JSONL sidecar,
    #830). None when the sidecar is absent/unreadable — the caller decides
    whether absence means anything (registration check's job, not ours)."""
    log = heartbeat_log_path(workspace)
    if not log.exists():
        return None
    last = None
    try:
        with log.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = line
    except OSError:
        return None
    if not last:
        return None
    try:
        ts = json.loads(last).get("ts")
        return str(ts) if ts else None
    except json.JSONDecodeError:
        return None


def gap_alarm(workspace, *, threshold_minutes: int | None = None,
              now: datetime | None = None) -> dict:
    """#618/#795: dead-window alarm off the durable sidecar.

    Returns {alarm, gap_min, newest_ts}:
      alarm=None  — no sidecar / unparseable (absence of a heartbeat face is
                    NOT deadness; that verdict belongs to the registration
                    check. Never a false positive here.)
      alarm=bool  — newest tick age > threshold (default STALE_MINUTES=35)
    """
    newest = newest_sidecar_ts(workspace)
    if newest is None:
        return {"alarm": None, "gap_min": None, "newest_ts": None}
    ts = _parse_hb_ts(newest)
    if ts is None:
        return {"alarm": None, "gap_min": None, "newest_ts": newest}
    moment = now or datetime.now(timezone.utc)
    threshold = threshold_minutes or STALE_MINUTES
    gap_min = (moment - ts).total_seconds() / 60.0
    return {"alarm": gap_min > threshold, "gap_min": round(gap_min, 2),
            "newest_ts": newest}


def _parse_hb_ts(value):
    """Parse an ISO-Z heartbeat timestamp -> aware datetime | None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate_tick_continuity(state: dict, *,
                             now: datetime | None = None,
                             stale_minutes: int = STALE_MINUTES,
                             log_path=None,
                             window_ticks: int = CONTINUITY_WINDOW_TICKS,
                             window_hours: int = CONTINUITY_WINDOW_HOURS
                             ) -> tuple[bool, str]:
    """#754 E2: THE liveness verdict shared by gate / check / verify.

    Alive requires ALL of:
      1. tick_history carries >= 2 parseable ticks (a lone registration tick,
         however fresh, is the #754 blind spot);
      2. every adjacent gap INSIDE THE WINDOW <= 2 * interval_min (interval
         read from the file, default 5min — one missed tick is jitter, two
         is a dead cron);
      3. the newest tick <= stale_minutes old (the pre-existing 35-min line).

    #4 sliding window: the verdict reads only RECENT ticks — among the last
    window_ticks OR within the last window_hours (defaults in liveness_policy,
    sized to the 5-min cadence). History outside the window is NOT deleted —
    the durable sidecar stays append-only — it just stops participating, so
    one mid-life stall (laptop asleep over a weekend) ages out instead of
    re-rejecting the workspace forever. Aged-out stalls are counted and
    surfaced in the detail text: no silent history rewriting.

    STRICT legacy handling (adjudicated): files WITHOUT tick_history REJECT —
    that format-shape IS the incident file, and a compatibility pass would
    preserve exactly the blind spot being closed. The detail text teaches the
    one-action fix (run a real touch/tick to start the history).
    """
    moment = now or datetime.now(timezone.utc)
    # r1-F1 (#754 review): fail-closed parity with the old unreadable-file
    # path — anything that cannot be interpreted is a REJECT, never an
    # exception escaping through the dispatch-gate pre_check.
    if not isinstance(state, dict):
        return (False,
                "heartbeat state unreadable (not an object) - re-register "
                "with hook_activation.py <ws> --heartbeat-on")
    raw = state.get(TICK_HISTORY_KEY)
    # #830: the durable tick sidecar is authoritative when it carries
    # parseable ticks. Deleting/tampering the .heartbeat.json cache cannot
    # erase history: the old ticks stay in the sidecar, so deletion cannot
    # hide the cadence gap around the incident (D2/D3).
    durable = []
    skipped_non_tick = 0
    if log_path is not None:
        lp = Path(log_path)
        if lp.exists():
            for obj in iter_jsonl(
                    lp.read_text(encoding="utf-8",
                                 errors="replace").splitlines()):
                if isinstance(obj, dict):
                    # #415: ONLY real cron/main-flow tick rows count for
                    # continuity. The sidecar is a shared append-only
                    # substrate: hook-event pulses (actor="hook",
                    # heartbeat_touch) and registration markers
                    # (actor="register") are a DIFFERENT stream — counting
                    # them made deploy-day quiet gaps look like dead crons
                    # for ~24h (owner live run, 51job). Unknown/absent
                    # actors from legacy rows keep the old inclusive read.
                    actor = str(obj.get("actor") or "tick")
                    if actor in ("hook", "register"):
                        skipped_non_tick += 1
                        continue
                    ts = _parse_hb_ts(obj.get("ts"))
                    if ts is not None:
                        durable.append(ts)
    durable_source = bool(durable)
    durable_prefix = "durable log: " if durable_source else ""
    if durable_source:
        stamps = sorted(durable)
    else:
        if not isinstance(raw, list) or not raw:
            return (False, durable_prefix +
                    "no tick_history (pre-#754 single-tick state, the 35-min blind "
                    "spot shape) - build it with ONE real tick now: python "
                    "<skill>/scripts/heartbeat_touch.py <ws> (only heartbeat_tick.py "
                    "<ws>), then re-dispatch")
        stamps = sorted(ts for ts in (_parse_hb_ts(v) for v in raw if isinstance(v, str))
                        if ts is not None)
    if len(stamps) < 2:
        return (False, durable_prefix +
                "single tick only (registration-time tick, cron never fired again) "
                "- wait for the SECOND tick (<= 2x interval) or check the /loop cron "
                f"is alive; tick_history={raw}")
    try:
        interval = float(state.get("interval_min") or TICK_INTERVAL_DEFAULT_MIN)
        # r1-F1: NaN/inf would silently disable every gap comparison below
        # (NaN comparisons are always False) — force back to the default.
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        interval = float(TICK_INTERVAL_DEFAULT_MIN)
    max_gap = timedelta(minutes=2 * interval)
    # #4: sliding window over the sorted history — union of "recent N ticks"
    # and "recent M hours". The tick-count bound caps the scan for slow
    # cadences; the age bound guarantees any stall ages out within ~a day.
    n = max(1, int(window_ticks))
    cutoff = moment - timedelta(hours=max(0, int(window_hours)))
    window = [t for i, t in enumerate(stamps)
              if i >= len(stamps) - n or t >= cutoff]
    in_window = set(window)
    # Stalls (oversized adjacent gaps) that no longer participate: the pair
    # is not fully inside the window, so the gap loop below never sees it.
    # Counted here so the verdict can surface them — no silent rewriting.
    aged_out = sum(1 for prev, nxt in zip(stamps, stamps[1:])
                   if nxt - prev > max_gap
                   and (prev not in in_window or nxt not in in_window))
    aged_note = (f"; window: last {len(window)} ticks (older history excluded: "
                 f"{aged_out} stall(s) aged out)") if aged_out else ""
    for prev, nxt in zip(window, window[1:]):
        gap = nxt - prev
        if gap > max_gap:
            return (False, durable_prefix +
                    f"cadence GAP between adjacent ticks ({int(gap.total_seconds()//60)} min "
                    f"> {int(2 * interval)} min = 2x{interval:g}m): "
                    f"{prev.strftime('%Y-%m-%dT%H:%M:%SZ')} -> "
                    f"{nxt.strftime('%Y-%m-%dT%H:%M:%SZ')} - the cron stalled mid-life; re-arm with "
                    "heartbeat_tick.py <ws> or re-register the /loop" + aged_note)
    age = moment - stamps[-1]
    if age > timedelta(minutes=stale_minutes):
        return (False, durable_prefix +
                f"heartbeat STALE (last tick {int(age.total_seconds()//60)} min ago > "
                f"{stale_minutes}) - continuous-tick history present but the loop died"
                + aged_note)
    return (True, durable_prefix +
            f"continuous ticks OK ({len(window)} in window, latest "
            f"{stamps[-1].strftime('%Y-%m-%dT%H:%M:%SZ')}, cadence <= "
            f"{int(2 * interval)}m)" + aged_note)
