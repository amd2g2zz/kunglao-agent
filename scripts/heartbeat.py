# -*- coding: utf-8 -*-
"""heartbeat.py - heartbeat register/verify/stop as verifiable file state.

Extracted from hook_activation.py (T-2 split) — the --heartbeat-on /
--heartbeat-check / --heartbeat-off jobs.
"""
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# A 5-min cron tick should refresh .heartbeat.json continuously; >35 min
# stale (5-min interval + jitter margin) means monitoring is NOT running.
# #597: value single-sourced in liveness_policy (THE liveness-minutes source).
from liveness_policy import STALE_MINUTES, TICK_INTERVAL_DEFAULT_MIN  # noqa: E402

# #461: the cron-registration marker. --heartbeat-on alone proves only that
# the FILE was written (init / manual chain both can do that); the marker
# flips to true only when the /loop prompt body itself executes (its first
# action runs `--heartbeat-on --loop-registered`) — the prompt body running
# is the one mechanical event that proves CronCreate accepted the
# registration. heartbeat_loop_prompt.py --verify HARD-fails while it is
# not true: a silently-failed cron registration was the 2026-08-19 v0.1.1
# field report ("monitoring never started", zero error surfaced).
LOOP_MARKER_KEY = "loop_registered"


# ===========================================================================
# #754 E2: continuous-tick liveness — THE shared judgment function
# ===========================================================================
# The live-run field incident (#754): last_tick_ts == started_ts for the whole
# session life (the cron never fired even once after registration), yet
# check_heartbeat_alive passed inside its 35-min window because a SINGLE
# registration tick was enough to claim liveness. Blind spot. Liveness is now
# CONTINUITY-based and single-sourced here; three consumers share this exact
# function so they can never drift apart:
#   - hooks/worker_budget_sinks.check_heartbeat_alive (the dispatch gate)
#   - scripts/heartbeat.py heartbeat_check (--heartbeat-check)
#   - scripts/heartbeat_loop_prompt.verify_loop (--verify, #609 freshness)
TICK_HISTORY_KEY = "tick_history"
# Anti-bloat cap: history keeps at most the 12 most recent ticks inside the
# 35-min liveness window (12 x 5min cadence >> any real analysis session's
# renewal needs; a bounded list can never grow without limit).
TICK_HISTORY_CAP = 12


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
                             stale_minutes: int = STALE_MINUTES) -> tuple[bool, str]:
    """#754 E2: THE liveness verdict shared by gate / check / verify.

    Alive requires ALL of:
      1. tick_history carries >= 2 parseable ticks (a lone registration tick,
         however fresh, is the #754 blind spot);
      2. every adjacent gap <= 2 * interval_min (interval read from the file,
         default 5min — one missed tick is jitter, two is a dead cron);
      3. the newest tick <= stale_minutes old (the pre-existing 35-min line).

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
    if not isinstance(raw, list) or not raw:
        return (False,
                "no tick_history (pre-#754 single-tick state, the 35-min blind "
                "spot shape) - build it with ONE real tick now: python "
                "<skill>/scripts/heartbeat_touch.py <ws> (or heartbeat_tick.py "
                "<ws>), then re-dispatch")
    stamps = sorted(ts for ts in (_parse_hb_ts(v) for v in raw if isinstance(v, str))
                    if ts is not None)
    if len(stamps) < 2:
        return (False,
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
    for prev, nxt in zip(stamps, stamps[1:]):
        gap = nxt - prev
        if gap > max_gap:
            return (False,
                    f"cadence GAP between adjacent ticks ({int(gap.total_seconds()//60)} min "
                    f"> {int(2 * interval)} min = 2x{interval:g}m): "
                    f"{prev.strftime('%Y-%m-%dT%H:%M:%SZ')} -> "
                    f"{nxt.strftime('%Y-%m-%dT%H:%M:%SZ')} - the cron stalled mid-life; re-arm with "
                    "heartbeat_tick.py <ws> or re-register the /loop")
    age = moment - stamps[-1]
    if age > timedelta(minutes=stale_minutes):
        return (False,
                f"heartbeat STALE (last tick {int(age.total_seconds()//60)} min ago > "
                f"{stale_minutes}) - continuous-tick history present but the loop died")
    return (True,
            f"continuous ticks OK ({len(stamps)} in window, latest "
            f"{stamps[-1].strftime('%Y-%m-%dT%H:%M:%SZ')}, cadence <= "
            f"{int(2 * interval)}m)")

# #461: the cron-registration marker. --heartbeat-on alone proves only that
# the FILE was written (init / manual chain both can do that); the marker
# flips to true only when the /loop prompt body itself executes (its first
# action runs `--heartbeat-on --loop-registered`) — the prompt body running
# is the one mechanical event that proves CronCreate accepted the
# registration. heartbeat_loop_prompt.py --verify HARD-fails while it is
# not true: a silently-failed cron registration was the 2026-08-19 v0.1.1
# field report ("monitoring never started", zero error surfaced).
LOOP_MARKER_KEY = "loop_registered"


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def heartbeat_register(workspace: Path, loop_registered: bool = False) -> int:
    """Register the heartbeat as verifiable state (<ws>/runs/.heartbeat.json).

    Turns 'monitoring is running' from a self-claim into a checked file state.
    Every heartbeat tick refreshes `last_tick_ts`; heartbeat_check exits 1
    when the file is missing or stale.

    #461: a re-register must NOT silently erase a proven cron registration —
    an existing loop_registered=true survives (only --heartbeat-off deletes
    the file, and a fresh loop must re-prove itself). loop_registered=True
    is set by the /loop prompt's first action (--loop-registered), never by
    a bare --heartbeat-on: file existence is not registration.
    """
    path = workspace / "runs" / ".heartbeat.json"
    was_registered = False
    if path.exists():
        try:
            was_registered = bool(
                json.loads(path.read_text(encoding="utf-8")).get(LOOP_MARKER_KEY))
        except (json.JSONDecodeError, OSError):
            was_registered = False
    # #754 E2: registration IS the first tick of the history window. A re-register
    # resets the list to the single fresh entry (no stale-history pollution across
    # lifetimes); continuity rebuilds itself within one interval via renew ticks.
    moment = datetime.now(timezone.utc)
    state = append_tick(
        {"started_ts": utc_now(), "interval_min": 5,
         "last_tick_ts": utc_now(),
         LOOP_MARKER_KEY: bool(loop_registered or was_registered)},
        now=moment)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"OK: heartbeat registered at {path} (interval 5m)")
    return 0


def mark_loop_registered(workspace: Path) -> int:
    """#461: mark the cron loop registration (loop_registered=true).

    Called with `hook_activation.py <ws> --loop-registered` by the /loop
    prompt's first action — the prompt body executing IS the proof that
    CronCreate accepted it. Requires an existing heartbeat file (register
    first with --heartbeat-on); never fabricates one.
    """
    path = workspace / "runs" / ".heartbeat.json"
    if not path.exists():
        print(f"FAIL: no {path} — register the heartbeat first "
              f"(--heartbeat-on), then mark the loop", file=sys.stderr)
        return 1
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"FAIL: {path} unreadable ({exc}) — re-register with "
              f"--heartbeat-on", file=sys.stderr)
        return 1
    state[LOOP_MARKER_KEY] = True
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"OK: cron loop registration marked at {path} "
          f"({LOOP_MARKER_KEY}=true)")
    return 0


def heartbeat_check(workspace: Path) -> int:
    """Exit 0 = monitoring IS running; exit 1 = NOT running.

    Checks <ws>/runs/.heartbeat.json exists AND the #754 continuous-tick
    verdict is ALIVE (>=2 ticks, adjacent gaps <= 2x interval_min, newest
    <= 35 min old). Missing/stale/non-continuous means the orchestrator's
    'monitoring started' claim is false.
    """
    path = workspace / "runs" / ".heartbeat.json"
    if not path.exists():
        print("HEARTBEAT DOWN: no .heartbeat.json — monitoring was never started", file=sys.stderr)
        return 1
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        last = datetime.fromisoformat(state.get("last_tick_ts", "").replace("Z", "+00:00"))
    except Exception as exc:
        print(f"HEARTBEAT DOWN: .heartbeat.json unreadable ({exc})", file=sys.stderr)
        return 1
    # #533 F-H1: check loop_registered marker
    if not state.get(LOOP_MARKER_KEY, False):
        print(f"HEARTBEAT LOOP NOT REGISTERED: {LOOP_MARKER_KEY}=false — cron registration not confirmed, run --loop-registered", file=sys.stderr)
        return 1

    # #754 E2: same continuous-tick standard as the dispatch gate and --verify.
    alive, detail = evaluate_tick_continuity(state)
    if not alive:
        print(f"HEARTBEAT NOT CONTINUOUS: {detail}", file=sys.stderr)
        return 1
    print(f"OK: heartbeat alive (started {state.get('started_ts')}, "
          f"last tick {state.get('last_tick_ts')}; {detail})")
    return 0


def heartbeat_off(workspace: Path, force: bool = False) -> int:
    """STOP the heartbeat — guarded teardown (issue #237 dual-constraint).

    The heartbeat is a DISPATCH GATE credential: hooks gate dispatch on it
    (check_heartbeat_alive), so deleting it while claims are still open breaks
    the analysis. But leaving it running after CONVERGED makes the 5-min cron
    wake the LLM forever and burn tokens with nothing to converge. The guard:
    convergence_check.py must return CONVERGED (exit 0) before the credential
    may be removed; `force=True` is the explicit operator override (--force).
    """
    if not force:
        cc = Path(__file__).resolve().parent / "convergence_check.py"
        try:
            r = subprocess.run(
                [sys.executable, str(cc), str(workspace)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120,
            )
            converged = r.returncode == 0
        except Exception:
            converged = False
        if not converged:
            print("Not converged — teardown forbidden: the heartbeat is the dispatch "
                  "gate credential; deleting it breaks analysis (dispatch would be "
                  "rejected by check_heartbeat_alive). Dispatch/reactivate to "
                  "CONVERGED (confirmed by convergence_check.py) first, or pass "
                  "explicit --force.",
                  file=sys.stderr)
            return 1
        # #717 criterion 2: the completion oracle must ALSO be closed. The
        # sample-incident-01 0.1.2 incident tore the heartbeat down on convergence
        # alone while the Stop gate slept — five OC items + a bad-YAML
        # oracle sailed through because convergence_check never reads
        # task-oracle.yaml. Both judges must agree: convergence (claims
        # resolved) AND judge() exit 0 (user's pre-registered items closed).
        oracle_path = workspace / "task-oracle.yaml"
        if not oracle_path.exists():
            print("Oracle missing — teardown forbidden: an oracle-anchored "
                  "workspace cannot stop monitoring without task-oracle.yaml "
                  "(unanchored run? --force is the operator override).",
                  file=sys.stderr)
            return 1
        try:
            import yaml  # noqa: PLC0415 — optional dependency, gate-local use
            oracle = yaml.safe_load(
                oracle_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — unreadable = refuse
            print(f"Oracle unreadable ({type(exc).__name__}) — teardown "
                  "forbidden: a corrupted oracle cannot be judged; repair "
                  "task-oracle.yaml or pass explicit --force.",
                  file=sys.stderr)
            return 1
        try:
            spec = importlib.util.spec_from_file_location(
                "_cg_heartbeat", Path(__file__).resolve().parent / "completion_gate.py")
            cg = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cg)
            oracle_code, oracle_reason = cg.judge(oracle)
        except Exception as exc:  # noqa: BLE001 — judge failure = refuse
            print(f"Completion gate judge failed ({type(exc).__name__}) — "
                  "teardown forbidden; pass explicit --force to override.",
                  file=sys.stderr)
            return 1
        if oracle_code != 0:
            print(f"Oracle not closed (exit {oracle_code}: {oracle_reason}) — "
                  "teardown forbidden: convergence_check resolves CLAIMS, but "
                  "the user's pre-registered open_items/deferrals are judged "
                  "by the completion gate; close or user-defer them, or pass "
                  "explicit --force.",
                  file=sys.stderr)
            return 1
    path = workspace / "runs" / ".heartbeat.json"
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        print(f"FAIL: cannot remove {path} ({exc})", file=sys.stderr)
        return 1
    print("Convergence complete, heartbeat stopped; to restart use --heartbeat-on")
    return 0
