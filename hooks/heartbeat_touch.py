#!/usr/bin/env python3
"""v1.9.36 — heartbeat touch hook (root-cause fix for '整个属于心跳的BUG').

Problem: heartbeat liveness depended on the ORCHESTRATOR processing the cron
/loop prompt and running `--renew`. Any busy/compacted/context-limited phase
skips the prompt -> last_tick_ts stops -> the 35-min mechanical gate in
worker_budget.py declares STALE -> every dispatch REJECTED -> slots can't be
refilled -> monitoring appears dead. The 'heartbeat stops' reports across
v1.9.12/13/18/25/26/28 were all this one root cause wearing different hats.

Fix: decouple liveness from cognition. This hook touches
`<ws>/runs/.heartbeat.json` (bumps activity_ts) on EVERY Bash/Read/Write/
Edit/Agent tool call — purely mechanical, zero thinking required. Any
tool activity = the session is alive = OBSERVABLE activity, NOT the heartbeat.
E2.3 semantic split: tick_ts (cron only, gates 35-min check) vs activity_ts (any tool, observation only). The cron
tick remains for its REAL job: reconcile/ping/verifier supervision (the
"what" — this hook proves "you're awake").

Trigger wiring: PreToolUse matcher=Bash (or any matcher covering tool use).
Registered by hook_activation.py --wire-up (v1.9.36).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> int:
    # Workspace discovery: cwd is the workspace root when running under
    # Claude (Bash hooks inherit the session cwd).
    ws = Path.cwd()
    for cand in [ws, ws.parent]:
        hb = cand / "runs" / ".heartbeat.json"
        if not hb.exists():
            continue
        try:
            data = json.loads(hb.read_text(encoding="utf-8"))
            data["activity_ts"] = utc_now()
            data.setdefault("last_tick_ts", data["activity_ts"])  # legacy readers
            hb.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return 0
        except Exception as exc:  # noqa: BLE001 — never break the tool call
            print(f"heartbeat_touch: heartbeat refresh failed ({exc})",
                  file=sys.stderr)
            return 0
    # No kunglao-agent workspace heartbeat file — nothing to touch, never block.
    return 0


if __name__ == "__main__":
    sys.exit(main())
