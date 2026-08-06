#### 6-pre. Anti-forgetting protocol (v1.8.2) — the four failure modes observed in practice
---

# Kong-agent failure modes (F1-F18) - INDEX

The 18 failure modes are split into 3 domain files (progressive disclosure):

| Domain | F-rows | File |
|---|---|---|
| Lifecycle (dispatch / heartbeat / stage agents) | F1-F6 | [`failure-modes-lifecycle.md`](failure-modes-lifecycle.md) |
| Monitoring (worker help / self-doubt / state discipline) | F7-F13 | [`failure-modes-monitoring.md`](failure-modes-monitoring.md) |
| State (plan-files / blockers / drift) | F14-F18 | [`failure-modes-state.md`](failure-modes-state.md) |

## When to load which

- User reports dispatch issues (stuck, idle, re-issuing) -> load `failure-modes-lifecycle.md`
- User reports worker-level problems (false PROVEN, ignored help, backtrack needed) -> load `failure-modes-monitoring.md`
- User reports plan/status/progress issues (stale blockers, drifted plan) -> load `failure-modes-state.md`

## Summary table (all 18 rows)

| ID | Symptom | Domain | Self-check question | Blocker |
|----|---------|--------|---------------------|---------|
| F1 | Idles with slots free, never dispatches next claim | are you idling with slots free? (slots<3 and open_claims>0 -> dispatch now) | - | B1a |
| F2 | Never self-schedules /loop | did you schedule /loop? (>=1 worker in flight or >=1 OPEN claim -> heartbeat required) | - | B1a |
| F3 | Only pings last-dispatched worker | did you check ALL registered workers, not just last-dispatched? (for worker in registry, no short-circuit) | - | B1d |
| F4 | Doesn't re-plan based on subagent return | did you re-read worker output + re-run priority.py? (every worker return -> re-plan) | - | B1b |
| F5 | Dead-worker / zombie wait | did you cross-check worker_budget active_workers + TaskList? (dead worker = post_check missing + liveness gone) | - | B1c |
| F6 | Discards stage-specific agents, uses general-purpose | is this really a general-purpose dispatch? (claim matches stage agent -> use stage-specific) | - | (self-violation) |
| F7 | Orchestrator ignores worker help_request | has the worker been waiting >5 min without your response? (active_intervention.py gate) | - | B1d |
| F8 | Self-confident false PROVEN | verifier_id != worker_id? (no self-stamp; F-8 anti-pattern) | - | B1g |
| F9 | Cost warning interrupts workflow | are you at tier=advisory / pause_non_essential / HARD_PAUSE? (cost_gate.py output) | - | B1h |
| F10 | Hook noise (all hooks always on) | did you check is_active() before running? (hook_activation.py) | - | B1i |
| F11 | Stuck worker doesn't backtrack | did you require ## backtrack section? (stuck > 20 min -> backtrack_gate.py) | - | B1j |
| F12 | Workers do repeat work, no reuse | did you cite existing fact or justify fresh? (reuse_gate.py) | - | B1k |
| F13 | Orchestrator fan-wen (should I dispatch?) | are you about to ask user? (NO - see F-13: just decide) | - | B1k (self-redirect) |
| F14 | Stale blockers not pruned | is this blocker still active? (closed claim -> stale_blocker_prune.py) | - | B1n |
| F15 | OPEN claims hours old, equal priority | is this claim STALE? (>24h no activity -> claim_expiry.py) | - | (priority demote) |
| F16 | No visual progress indicator | did you emit progress_report.py? (visual progress at each heartbeat) | - | - |
| F17 | Plan vs reality drift | is plan in sync with reality? (5 drift types -> plan_drift_detector.py) | - | B1o |
| F18 | State management overall | did you run F14-F17 heartbeat? (integrated state management) | - | - |

## Run all enforcement gates (orchestrator /loop heartbeat)

```bash
python C:/Users/hr/.claude/skills/kunglao-agent/scripts/progress_report.py <ws> && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/stale_blocker_prune.py <ws> --dry-run && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/claim_expiry.py <ws> && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/plan_drift_detector.py <ws>
```
