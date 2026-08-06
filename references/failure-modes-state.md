---
name: kong-agent-failure-modes-state
description: State (F14-F18): plan-files / blockers / drift (split from failure-modes.md for progressive disclosure). Load when the user reports a specific failure-mode pattern (e.g. 笨/卡/不匹配) and the dispatcher needs the matching F-row + enforcement script.
metadata:
  type: reference
  parent: failure-modes.md
---

# State (F14-F18): plan-files / blockers / drift

Failure modes covering plan-state consistency:
  - F14: stale blocker 不清理 (closed-claim blocker still in active list)
  - F15: stale claim 不降权 (OPEN hours old, equal priority)
  - F16: 没 visual progress indicator
  - F17: plan ↔ reality drift (re-plan / decompose / abandon, files lag)
  - F18: state management overall (integrates F14-F17)


## Full F-row table (this domain only)

| ID | Symptom | Self-check question | Blocker |
|----|---------|---------------------|---------|
| F14 | Stale blockers not pruned | is this blocker still active? (closed claim -> stale_blocker_prune.py) | B1n |
| F15 | OPEN claims hours old, equal priority | is this claim STALE? (>24h no activity -> claim_expiry.py) | (priority demote) |
| F16 | No visual progress indicator | did you emit progress_report.py? (visual progress at each heartbeat) | - |
| F17 | Plan vs reality drift | is plan in sync with reality? (5 drift types -> plan_drift_detector.py) | B1o |
| F18 | State management overall | did you run F14-F17 heartbeat? (integrated state management) | - |

## Run all enforcement gates (orchestrator /loop heartbeat)

```bash
python C:/Users/hr/.claude/skills/kunglao-agent/scripts/progress_report.py <ws> && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/stale_blocker_prune.py <ws> --dry-run && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/claim_expiry.py <ws> && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/plan_drift_detector.py <ws>
```
