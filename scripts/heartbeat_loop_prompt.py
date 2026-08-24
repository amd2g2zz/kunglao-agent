#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""heartbeat_loop_prompt.py — v1.9.26: generate the FULL /loop heartbeat prompt.

Why: the heartbeat must be BORN registered. The orchestrator used to create
the /loop cron, THEN remember to run --heartbeat-on — a two-step dance that
failed (orchestrator claimed monitoring started without registering it,
v1.9.25 lesson). This script emits ONE self-contained /loop prompt that
CARRIES the registration + monitoring + verification contract, so a single
`/loop 5m <prompt>` starts everything at once.

Usage:
    python scripts/heartbeat_loop_prompt.py <workspace> [--interval 5m]
    python scripts/heartbeat_loop_prompt.py <workspace> --verify

Output: the prompt to pass to `/loop <interval> <prompt>` (or CronCreate).
The prompt's FIRST action is `hook_activation.py <ws> --heartbeat-on
--loop-registered` (registration is born with the loop AND marked — the
prompt body executing is the proof CronCreate accepted it, #461), then
per-tick monitoring (reconcile / status poll / smart ping / convergence /
renew). Since v1.9.29 (issue #237) the convergence decision is a COMMAND,
not a suggestion: DISPATCH must dispatch priority_ratio.py #1, BLOCKED must
self-recover/reactivate, DEFERRED must check reactivation — no action in
a tick = idle fault. CONVERGED only after §6.3 checklist + handoff-check
PASS, then `--heartbeat-off` stops the loop (guarded: unconverged teardown
is rejected).

--verify (#461, HARD): the caller-side cron-registration acceptance check.
Reads the loop marker in <ws>/runs/.heartbeat.json (loop_registered);
missing file / absent / false marker -> exit 1 + stderr guidance (how to
register, what still failing means) — NEVER a silent RC 0. Run it right
after attempting CronCreate / /loop, and before the first dispatch.

Pure stdlib. Exit 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def build_prompt(ws: str, interval: str = "5m") -> str:
    skill_dir = Path(__file__).resolve().parent.parent  # kunglao-agent/ (scripts/ -> root)
    h = str(skill_dir / "scripts" / "hook_activation.py")
    tk = str(skill_dir / "scripts" / "heartbeat_tick.py")
    cc = str(skill_dir / "scripts" / "convergence_check.py")
    return f"""/loop {interval} kunglao-agent heartbeat (self-registration + monitoring + verification in one):

[Startup action — run once on the loop's first trigger]
python {h} {ws} --heartbeat-on --loop-registered   # register runs/.heartbeat.json AND mark loop_registered=true (#461) — this prompt body executing is the proof CronCreate accepted it

[Per-tick monitoring (5-minute interval)]
0. python {tk} {ws}              # v1.9.38 one-command tick: selfcheck + reconcile + renew + heartbeat-check + oracle-check
                                 # (all mechanical steps folded into 1 command; manual handling only when exit=1)
                                 # oracle_registered=false in the report → run the Phase 0 task-oracle.yaml backfill now
1. Read the runs/.heartbeat-tick.json report: exit=0 → only cognitive steps remain (ping active workers / handle finished workers)
2. Smart-ping every active worker (§6.1a): SendMessage "[ping HH:MM] step? stuck? eta?"
   → append structured replies to runs/.ping-log.jsonl
   (isolation boundary #88: no agent teams; the orchestrator→worker SendMessage ping is the sanctioned channel,
    workers never message each other)
3. python {cc} {ws} --json → read the decision field, imperative execution (every decision MUST produce a convergence-advancing action; no action = idle fault):
   DISPATCH   → MUST dispatch priority_ratio.py #1, no idling allowed
   BLOCKED    → MUST self-recover (resolve / stale_blocker_prune) or reactivate the failed claim
   DEFERRED   → MUST check whether reactivation is possible (e.g. VM reachable again → restore the claim and dispatch)
   SATURATED  → MUST poll all active workers (no idle waiting)
   CONVERGED  → run the §6.3 checklist (5 items) + independent verification (blind_gate sign-off spot-check
              + kunglao-verify.py L1 re-run) + handoff-check PASS first
              → then python {h} {ws} --heartbeat-off stops the heartbeat (no cleanup before convergence — deletion breaks dispatch)
4. Finished worker → verify facts → merge to master → update claim-register + _INDEX
5. Record notes with malware-veri-notes per §6.2; at the end of every tick you MUST be able to state "what this round advanced" (fill it into
   runs/.heartbeat-tick.json's action_taken; an empty field = idle fault)"""


def verify_loop(ws: str) -> int:
    """#461 HARD: prove the cron loop is registered — non-zero + stderr
    guidance when it is not (never silent).

    The loop marker (loop_registered) flips true only when the /loop prompt
    body itself executes (its first action passes --loop-registered) — a
    heartbeat FILE written by init / --heartbeat-on proves nothing about
    the cron. This is the caller-side acceptance check after attempting
    CronCreate / /loop.
    """
    hb = Path(ws) / "runs" / ".heartbeat.json"
    if not hb.exists():
        print("HEARTBEAT UNREGISTERED (HARD, #461): no "
              f"{hb} — monitoring was never started. Fix: run "
              "hook_activation.py <ws> --heartbeat-on, then register the "
              "cron below.", file=sys.stderr)
        return 1
    try:
        data = json.loads(hb.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"HEARTBEAT UNREADABLE (HARD, #461): {hb}: {exc} — "
              "re-register with --heartbeat-on.", file=sys.stderr)
        return 1
    if not data.get("loop_registered"):
        print(
            "CRON NOT REGISTERED (HARD, #461): runs/.heartbeat.json exists "
            "but loop_registered is not true — the /loop heartbeat cron was "
            "never created (or never fired). Monitoring is NOT running and "
            "proceeding silently is forbidden. Fix NOW: re-run "
            "heartbeat_loop_prompt.py <ws> and pass its output to "
            "CronCreate */5 * * * * (or /loop 5m <prompt>); the loop's "
            "first action marks loop_registered=true. Re-run this --verify "
            "after the first tick (<= one interval); still failing then "
            "means the CronCreate itself failed — re-create the cron.",
            file=sys.stderr)
        return 1
    print(f"OK: cron loop registered (loop_registered=true, started "
          f"{data.get('started_ts')})")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {Path(sys.argv[0]).name} <workspace> [--interval 5m] [--verify]", file=sys.stderr)
        return 2
    ws = sys.argv[1]
    if "--verify" in sys.argv[2:]:
        return verify_loop(ws)
    interval = "5m"
    if "--interval" in sys.argv:
        i = sys.argv.index("--interval")
        if i + 1 < len(sys.argv):
            interval = sys.argv[i + 1]
    print(build_prompt(ws, interval))
    return 0


if __name__ == "__main__":
    sys.exit(main())
