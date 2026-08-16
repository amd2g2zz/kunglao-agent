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

Output: the prompt to pass to `/loop <interval> <prompt>` (or CronCreate).
The prompt's FIRST action is `hook_activation.py <ws> --heartbeat-on`
(registration is born with the loop), then per-tick monitoring (reconcile /
status poll / smart ping / convergence / renew). Since v1.9.29 (issue #237)
the convergence decision is a COMMAND, not a suggestion: DISPATCH must dispatch
priority.py #1, BLOCKED must self-recover/reactivate, DEFERRED must check
reactivation — no action in a tick = idle fault. CONVERGED only after
§6.3 checklist + handoff-check PASS, then `--heartbeat-off` stops the loop
(guarded: unconverged teardown is rejected).

Pure stdlib. Exit 0.
"""
from __future__ import annotations

import sys
from pathlib import Path


def build_prompt(ws: str, interval: str = "5m") -> str:
    skill_dir = Path(__file__).resolve().parent.parent  # kunglao-agent/ (scripts/ -> root)
    h = str(skill_dir / "scripts" / "hook_activation.py")
    tk = str(skill_dir / "scripts" / "heartbeat_tick.py")
    cc = str(skill_dir / "scripts" / "convergence_check.py")
    return f"""/loop {interval} kunglao-agent heartbeat (self-registration + monitoring + verification in one):

[Startup action — run once on the loop's first trigger]
python {h} {ws} --heartbeat-on   # register the heartbeat (writes runs/.heartbeat.json) — monitoring is file state from here on

[Per-tick monitoring (5-minute interval)]
0. python {tk} {ws}              # v1.9.38 one-command tick: selfcheck + reconcile + renew + heartbeat-check
                                 # (all mechanical steps folded into 1 command; manual handling only when exit=1)
1. Read the runs/.heartbeat-tick.json report: exit=0 → only cognitive steps remain (ping active workers / handle finished workers)
2. Smart-ping every active worker (§6.1a): SendMessage "[ping HH:MM] step? stuck? eta?"
   → append structured replies to runs/.ping-log.jsonl
   (isolation boundary #88: no agent teams; the orchestrator→worker SendMessage ping is the sanctioned channel,
    workers never message each other)
3. python {cc} {ws} decision → imperative execution (every decision MUST produce a convergence-advancing action; no action = idle fault):
   DISPATCH   → MUST dispatch priority.py #1, no idling allowed
   BLOCKED    → MUST self-recover (resolve / stale_blocker_prune) or reactivate the failed claim
   DEFERRED   → MUST check whether reactivation is possible (e.g. VM reachable again → restore the claim and dispatch)
   SATURATED  → MUST poll all active workers (no idle waiting)
   CONVERGED  → run the §6.3 checklist (5 items) + independent verification (blind_gate sign-off spot-check
              + kunglao-verify.py L1 re-run) + handoff-check PASS first
              → then python {h} {ws} --heartbeat-off stops the heartbeat (no cleanup before convergence — deletion breaks dispatch)
4. Finished worker → verify facts → merge to master → update claim-register + _INDEX
5. Record notes with malware-veri-notes per §6.2; at the end of every tick you MUST be able to state "what this round advanced" (fill it into
   runs/.heartbeat-tick.json's action_taken; an empty field = idle fault)"""


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {Path(sys.argv[0]).name} <workspace> [--interval 5m]", file=sys.stderr)
        return 2
    ws = sys.argv[1]
    interval = "5m"
    if "--interval" in sys.argv:
        i = sys.argv.index("--interval")
        if i + 1 < len(sys.argv):
            interval = sys.argv[i + 1]
    print(build_prompt(ws, interval))
    return 0


if __name__ == "__main__":
    sys.exit(main())
