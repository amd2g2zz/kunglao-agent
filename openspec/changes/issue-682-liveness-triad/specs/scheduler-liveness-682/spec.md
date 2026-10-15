# scheduler-liveness-682 delta — issue-682-liveness-triad

## ADDED Requirements

### Requirement: the cadence advisor counts only FRESH in-progress workers

`cadence_advisor.active_workers` SHALL exclude every in-progress
worker-status file whose mtime is older than 10 minutes
(`WORKER_FRESH_MIN`, the workguard `waiting_live` rule), so a killed
worker's stale status tail can never count as load or pin the advised
interval at `FLOOR_MIN`.

#### Scenario: a stale in-progress tail does not make the advisor busy

- **WHEN** the advisor evaluates with a worker-status file whose last
  status token is `in-progress` and whose mtime is 30 minutes old
- **THEN** `active_workers` excludes it, `sources.workers` is empty, and
  a due evaluation moves the recommendation UP from the current interval
  with a `quiet` reason

#### Scenario: a fresh in-progress worker still pins busy

- **WHEN** the advisor evaluates with an in-progress status file whose
  mtime is inside the 10-minute window
- **THEN** the worker is counted in `sources.workers` and the reason is
  `busy`

### Requirement: tool activity never writes the tick signal

`hooks/heartbeat_touch.py` SHALL write only `activity_ts` (the
observation stream); it SHALL NOT create `last_tick_ts` on a state that
lacks it, nor advance an existing `last_tick_ts`. The tick signal is
written by the cron's renew/registration tick only.

#### Scenario: a touch on a reset-shaped state leaves last_tick_ts absent

- **WHEN** a tool call runs the touch hook against a heartbeat state
  that carries `tick_history` but no `last_tick_ts`
- **THEN** the rewritten state carries a fresh `activity_ts` and still
  carries no `last_tick_ts`

#### Scenario: a touch never advances an existing last_tick_ts

- **WHEN** a tool call runs the touch hook against a heartbeat state
  whose `last_tick_ts` predates the call by two hours
- **THEN** the rewritten state's `last_tick_ts` is unchanged

#### Scenario: the dispatch gate stays continuity-based

- **WHEN** `check_heartbeat_alive` evaluates a heartbeat whose
  `last_tick_ts` is fresh but which carries no tick history (and no
  durable tick rows)
- **THEN** the verdict is REJECT (the authority is
  `evaluate_tick_continuity`, never the `last_tick_ts` field)

### Requirement: WORKGUARD shares the dispatch gate's liveness verdict

`workguard.actionable_set` SHALL report a `liveness` wall and an empty
actionable set (legal sleep) while
`worker_budget_sinks.check_heartbeat_alive` would REJECT a dispatch for
the workspace (dead heartbeat) — the two schedulers SHALL NOT each
demand the other's precondition. The wall SHALL be absent when the
gate's verdict is alive, when the gate's state file is absent (its skip
semantics), or on any read/load failure (fail-open, one canonical warn).

#### Scenario: stale heartbeat plus open claim is legal sleep, not a deadlock

- **WHEN** a workspace has an OPEN claim and a heartbeat whose newest
  tick is two hours old (the gate REJECTs dispatches)
- **THEN** `actionable_set` returns no actionable claims, `legal_sleep`
  is true, and `walls` carries the `liveness` wall naming the repair

#### Scenario: a live heartbeat never walls the DAG

- **WHEN** a workspace has an OPEN claim and a continuous heartbeat
  (two on-cadence ticks, newest fresh)
- **THEN** the claim is dispatchable and no `liveness` wall appears
