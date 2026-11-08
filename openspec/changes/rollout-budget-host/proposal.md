# Proposal

## Why

Workstream A (PR via the timer card) shipped the pure policy core —
`rlvr/rollout_timer.py` (arm/cancel/fire/learn + the bounded coefficient
table) — with zero production callers: the only importer was the
package facade, `deadline_stop_record` was dead code, and no dispatch
ever armed a timer. A policy with no host moves no data: the per-rollout
learned deadline existed as math, not as behavior. This change wires
the policy core into the workspace lifecycle (the timer card's
workstream B, host wiring) while the event-wake path (workstream C1)
and the monitor removal (C2+E) follow in their own slices.

## What Changes

- **The dispatch-commit arm face**: a committed dispatch arms its
  one-shot deadline timer through the new
  `rlvr/rollout_timer_host.py` (`arm_for_dispatch`) — rollout_id =
  the dispatch ledger id minted at the approval point, kind = the
  declared method family (fallback `claim`), difficulty = the
  workspace difficulty feed's tier (fail-closed `hard`). Fail-open
  telemetry: a timer trouble is one warn and never disturbs an
  approved dispatch. The wake contract (one-shot cron expression,
  deadline, graceful wrap-up prompt) publishes to
  `runs/rollout-timer-wake.json` for the orchestrator's CronCreate
  face.
- **The round-closure cancel + learn face**: the SubagentStop closure
  (hooks/round_closure) cancels the finished rollout's timer and
  learns its outcome from the run's actuals (settle receipt:
  duration_ms / wall_s, outcome). The host classifies early /
  on_time from the bounded table's own bands; a failed worker or a
  completion past its budget lands the honest no-update word
  (`aborted`). A deadline-fired rollout is CENSORED: cancel only,
  never learn.
- **The one-shot deadline wake face**: `deadline_wake_face` (and its
  CLI `scripts/rollout_timer_wake.py`) executes the cron wake: fire,
  record the settlement-facing deadline stop (`deadline_stop_record`'s
  FIRST production caller), cancel, learn the timeout. It NEVER
  starts a rollout — the published graceful-stop contract carries the
  wrap-up prompt and `may_start_rollout: false`.
- **The wake-state publish face**: the single-slot
  `runs/rollout-timer-wake.json` carries the armed wake contract or
  the graceful-stop contract; the round close clears the slot for its
  rollout. The durable truth stays in the telemetry ledger rows; the
  file is the orchestrator's publish surface.
- **Skill contract text**: a short rollout-timer block in the dispatch
  loop section (arm → CronCreate once → early finish CronDelete →
  deadline wake = wrap-up only). The old heartbeat/cron lines stay
  until the monitor-removal slice retires them with the consumer
  audit.

## Impact

- **Affected specs**: `openspec/changes/rollout-budget-host` (new
  capability spec: the rollout deadline timer's host wiring).
- **Affected code**:
  - `scripts/rlvr/rollout_timer_host.py` (new — the dumb host faces)
  - `scripts/rlvr/rollout_timer.py` (ONE addition: the `timer_state`
    public read face; no policy math touched)
  - `scripts/claims_store.py` (the commit arm, fail-open)
  - `hooks/round_closure.py` (the round-close face, own cage)
  - `scripts/rollout_timer_wake.py` (new CLI — the wake's executor)
  - `skills/kunglao-agent/SKILL.md` (the timer contract block)
  - `experiments/scheduler/coeff_sim.py` (the EXP-B1 harness, gate)
  - `tests/test_timer_host_wiring_1001.py` (the wiring pins)
  - `scripts/README.md` (the new CLI + the arm-face mention)
  - `deploy-manifest.yaml` (the scaffold closure grows with the new
    rlvr module)
- **Out of scope** (their own slices): the Stop-hook boundary
  (timer-not-due → allow / due → block — a follow-up noted for the
  openspec change), the event-driven wake path (FileChanged /
  events.jsonl watcher), the old monitor-stack removal, the liveness
  rewrite.
