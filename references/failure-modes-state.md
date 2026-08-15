---
name: kunglao-agent-failure-modes-state
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
python scripts/progress_report.py <ws> && \
  python scripts/stale_blocker_prune.py <ws> --dry-run && \
  python scripts/claim_expiry.py <ws> && \
  python scripts/plan_drift_detector.py <ws>
```

## Implementation-Bug Class (S3 #132)

The F1-F18 taxonomy covers **LLM behavior failures** (idle, re-dispatch,
self-stamping). This section covers **script implementation bugs** discovered
during S3 hardening — distinct failure modes where the code itself is wrong.

### Patterns

| Bug Class | Example | Grep Pattern |
|---|---|---|
| Local state copy drift (TERMINAL 5-value) | F1: claim-status guard had local copy of 5-value list, diverged from canonical | `grep -rn "OPEN\|CLOSED\|DEFERRED" scripts/ --include="*.py" \| grep -v status_defs` |
| Read-modify-write race | F8: blind_gate read YAML, modified in memory, wrote back — concurrent workers could clobber | `grep -rn "yaml.load\|yaml.safe_load\|yaml.dump" scripts/ --include="*.py"` |
| Schema-output mismatch | F1/F2: script produced fields not in declared schema; consumers silently ignored extra fields | `grep -rn "json.dumps\|yaml.dump" scripts/ --include="*.py"` |
| Phantom entry | F8/#123: memory_capture existed in paused_hooks but not ALL_HOOKS — ghost reference (memory_capture itself was removed with the memory/ subsystem in #355; the incident pattern remains the lesson) | `grep -rn "ALL_HOOKS\|paused\|HARD_PAUSE" scripts/ --include="*.py"` |

### Checklist for Future Audits

1. **Single-source check**: every constant/enum has exactly one definition site; grep for duplicates
2. **Schema contract check**: script output fields match declared schema keys exactly
3. **Phantom reference check**: every hook/gate referenced in paused/active lists exists in the canonical registry
4. **Race condition check**: state files that undergo read-modify-write have no concurrent writer paths
