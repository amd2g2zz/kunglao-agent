# -*- coding: utf-8 -*-
"""heartbeat.py - heartbeat register/verify/stop as verifiable file state.

Extracted from hook_activation.py (T-2 split) — the --heartbeat-on /
--heartbeat-check / --heartbeat-off jobs.

Issue #420 Phase 2: the liveness JUDGMENT CORE (evaluate_tick_continuity,
append_tick, the #830 durable sidecar faces, the #415.3 baseline reset)
lives in ``rlvr.liveness``; this module keeps the CLI faces (register /
mark / check / off) and re-exports the core so every existing importer —
hooks/worker_budget_sinks, heartbeat_loop_prompt, heartbeat_tick,
heartbeat_touch, hook_activation, convergence_check — keeps working
unchanged. The shared verdict is single-sourced in the package.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _hooks_path import load_module_by_path  # #863 Family B: loader delegation (#671 authority)

# A 5-min cron tick should refresh .heartbeat.json continuously; >35 min
# stale (5-min interval + jitter margin) means monitoring is NOT running.
# Value single-sourced in liveness_policy (issue 597, THE liveness-minutes
# source) — imported here directly (the adjudication names this file a
# consumer), and re-exported through rlvr.liveness (never redefined).
from liveness_policy import (CONTINUITY_WINDOW_HOURS,  # noqa: E402,F401 (#4 window)
                             CONTINUITY_WINDOW_TICKS,
                             STALE_MINUTES, TICK_INTERVAL_DEFAULT_MIN)
# The continuity core (issue #420 Phase 2): the shared verdict + the
# durable-sidecar faces live in rlvr.liveness; this adapter keeps the CLI
# faces and re-exports the core so every existing importer keeps working.
from rlvr.liveness import (  # noqa: E402,F401
    HEARTBEAT_LOG_NAME,
    TICK_HISTORY_CAP,
    TICK_HISTORY_KEY,
    _parse_hb_ts,  # hooks/heartbeat_touch.py dedups sidecar pulses through it
    append_tick,
    append_tick_log,
    evaluate_tick_continuity,
    gap_alarm,
    heartbeat_log_path,
    newest_sidecar_ts,
    reset_continuity_baseline,
)
from harness_common import utc_now_z as utc_now  # noqa: E402,F401 — #863 Family F: single source (was a local def)

# #461: the cron-registration marker. --heartbeat-on alone proves only that
# the FILE was written (init / manual chain both can do that); the marker
# flips to true only when the /loop prompt body itself executes (its first
# action runs `--heartbeat-on --loop-registered`) — the prompt body running
# is the one mechanical event that proves CronCreate accepted the
# registration. heartbeat_loop_prompt.py --verify HARD-fails while it is
# not true: a silently-failed cron registration was the 2026-08-19 v0.1.1
# field report ("monitoring never started", zero error surfaced).
LOOP_MARKER_KEY = "loop_registered"

__all__ = [
    # the continuity core (rlvr.liveness re-exports)
    "TICK_HISTORY_KEY", "TICK_HISTORY_CAP", "HEARTBEAT_LOG_NAME",
    "STALE_MINUTES", "CONTINUITY_WINDOW_HOURS", "CONTINUITY_WINDOW_TICKS",
    "TICK_INTERVAL_DEFAULT_MIN",
    "append_tick", "append_tick_log", "heartbeat_log_path",
    "newest_sidecar_ts", "gap_alarm", "evaluate_tick_continuity",
    "reset_continuity_baseline", "_parse_hb_ts",
    # the CLI faces (this module)
    "LOOP_MARKER_KEY", "heartbeat_register", "mark_loop_registered",
    "heartbeat_check", "heartbeat_off", "utc_now",
]


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
    # #830: registration appends to the durable sidecar - re-registering
    # after a cache deletion CANNOT reset the tick history (D3).
    append_tick_log(workspace, "register")
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
        datetime.fromisoformat(state.get("last_tick_ts", "").replace("Z", "+00:00"))
    except Exception as exc:
        print(f"HEARTBEAT DOWN: .heartbeat.json unreadable ({exc})", file=sys.stderr)
        return 1
    # #533 F-H1: check loop_registered marker
    if not state.get(LOOP_MARKER_KEY, False):
        print(f"HEARTBEAT LOOP NOT REGISTERED: {LOOP_MARKER_KEY}=false — cron registration not confirmed, run --loop-registered", file=sys.stderr)
        return 1

    # #754 E2: same continuous-tick standard as the dispatch gate and --verify.
    # #830: judge from the durable sidecar when present (cache is a cache).
    alive, detail = evaluate_tick_continuity(
        state, log_path=heartbeat_log_path(workspace))
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
            cg = load_module_by_path(
                "_cg_heartbeat",
                Path(__file__).resolve().parent / "completion_gate.py")
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
