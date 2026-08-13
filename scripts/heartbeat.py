# -*- coding: utf-8 -*-
"""heartbeat.py - heartbeat register/verify as verifiable file state.

Extracted from hook_activation.py (T-2 split) — the --heartbeat-on /
--heartbeat-check jobs.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# A 5-min cron tick should refresh .heartbeat.json continuously; >35 min
# stale (5-min interval + jitter margin) means monitoring is NOT running.
STALE_MINUTES = 35


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def heartbeat_register(workspace: Path) -> int:
    """Register the heartbeat as verifiable state (<ws>/runs/.heartbeat.json).

    Turns 'monitoring is running' from a self-claim into a checked file state.
    Every heartbeat tick refreshes `last_tick_ts`; heartbeat_check exits 1
    when the file is missing or stale.
    """
    state = {"started_ts": utc_now(), "interval_min": 5, "last_tick_ts": utc_now()}
    path = workspace / "runs" / ".heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"OK: heartbeat registered at {path} (interval 5m)")
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
    age = datetime.now(timezone.utc) - last
    if age > timedelta(minutes=STALE_MINUTES):
        print(f"HEARTBEAT STALE: last tick {state.get('last_tick_ts')} ({int(age.total_seconds()//60)} min ago > {STALE_MINUTES})", file=sys.stderr)
        return 1
    print(f"OK: heartbeat alive (started {state.get('started_ts')}, last tick {state.get('last_tick_ts')})")
    return 0
