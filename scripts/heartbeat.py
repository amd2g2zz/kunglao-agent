# -*- coding: utf-8 -*-
"""heartbeat.py - heartbeat register/verify/stop as verifiable file state.

Extracted from hook_activation.py (T-2 split) — the --heartbeat-on /
--heartbeat-check / --heartbeat-off jobs.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# A 5-min cron tick should refresh .heartbeat.json continuously; >35 min
# stale (5-min interval + jitter margin) means monitoring is NOT running.
# #597: value single-sourced in liveness_policy (THE liveness-minutes source).
from liveness_policy import STALE_MINUTES  # noqa: E402

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
    now = utc_now()
    state = {"started_ts": now, "interval_min": 5, "last_tick_ts": now,
             LOOP_MARKER_KEY: bool(loop_registered or was_registered)}
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
              f"(--heartbeat-on), then mark the loop (#461)", file=sys.stderr)
        return 1
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"FAIL: {path} unreadable ({exc}) — re-register with "
              f"--heartbeat-on (#461)", file=sys.stderr)
        return 1
    state[LOOP_MARKER_KEY] = True
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"OK: cron loop registration marked at {path} "
          f"({LOOP_MARKER_KEY}=true)")
    return 0


def heartbeat_check(workspace: Path) -> int:
    """Exit 0 = monitoring IS running; exit 1 = NOT running.

    Checks <ws>/runs/.heartbeat.json exists AND last_tick_ts is < 35 min old.
    Missing/stale means the orchestrator's 'monitoring started' claim is false.
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

    age = datetime.now(timezone.utc) - last
    if age > timedelta(minutes=STALE_MINUTES):
        print(f"HEARTBEAT STALE: last tick {state.get('last_tick_ts')} ({int(age.total_seconds()//60)} min ago > {STALE_MINUTES})", file=sys.stderr)
        return 1
    print(f"OK: heartbeat alive (started {state.get('started_ts')}, last tick {state.get('last_tick_ts')})")
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
