---
name: kong-agent-failure-modes-lifecycle
description: Lifecycle (F1-F6): dispatch / heartbeat / worker routing (split from failure-modes.md for progressive disclosure). Load when the user reports a specific failure-mode pattern (e.g. 笨/卡/不匹配) and the dispatcher needs the matching F-row + enforcement script.
metadata:
  type: reference
  parent: failure-modes.md
---

# Lifecycle (F1-F6): dispatch / heartbeat / worker routing

Failure modes covering the orchestrator's core dispatch loop:
  - F1: idling with slots free
  - F2: forgot the heartbeat (never self-schedules /loop)
  - F3: background monitor but doesn't ping (only pings last-dispatched worker)
  - F4: doesn't re-plan based on subagent return
  - F5: deadlock / zombie wait
  - F6: discards stage-specific agents, uses general-purpose


## Full F-row table (this domain only)

| ID | Symptom | Self-check question | Blocker |
|----|---------|---------------------|---------|
| F1 | Idles with slots free, never dispatches next claim | are you idling with slots free? (slots<3 and open_claims>0 -> dispatch now) | B1a |
| F2 | Never self-schedules /loop | did you schedule /loop? (>=1 worker in flight or >=1 OPEN claim -> heartbeat required) | B1a |
| F3 | Only pings last-dispatched worker | did you check ALL registered workers, not just last-dispatched? (for worker in registry, no short-circuit) | B1d |
| F4 | Doesn't re-plan based on subagent return | did you re-read worker output + re-run priority.py? (every worker return -> re-plan) | B1b |
| F5 | Dead-worker / zombie wait | did you cross-check worker_budget active_workers + TaskList? (dead worker = post_check missing + liveness gone) | B1c |
| F6 | Discards stage-specific agents, uses general-purpose | is this really a general-purpose dispatch? (claim matches stage agent -> use stage-specific) | (self-violation) |

## Run all enforcement gates (orchestrator /loop heartbeat)

```bash
python C:/Users/hr/.claude/skills/kunglao-agent/scripts/progress_report.py <ws> && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/stale_blocker_prune.py <ws> --dry-run && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/claim_expiry.py <ws> && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/plan_drift_detector.py <ws>
```
