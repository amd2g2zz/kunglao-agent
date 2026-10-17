# dispatch-telemetry-740 delta — issue-740-face4-dispatch-telemetry

## ADDED Requirements

### Requirement: The completion row closes the dispatch loop

A worker stop SHALL emit its `lifecycle_completed` row enriched with
claim / duration_ms / exit (0 settled, 1 blocked) and the
attempt_id/step_id/outcome binding in the detail — so verify loops
close on evidence instead of re-discussion.

#### Scenario: the four fields ride the row

- **WHEN** a dispatched claim's worker stops and the step settles
- **THEN** the lifecycle_completed row carries claim, duration_ms,
  exit=0, and the detail binds attempt_id/step_id/outcome

#### Scenario: a blocked settle exits one

- **WHEN** the settle outcome is blocked
- **THEN** the row's exit is 1

### Requirement: A non-worker stop stays silent

A SubagentStop with no settle receipt SHALL NOT emit the completion
row.

#### Scenario: the non-worker stop is silent

- **WHEN** the round-closure hook runs with no pending step
- **THEN** no lifecycle_completed row lands

### Requirement: The telemetry is additive

The settle receipt's telemetry keys SHALL be additive — the ledger
whitelists and the step-record/2 schema are untouched.

#### Scenario: whitelists untouched

- **WHEN** the step settles
- **THEN** the step-ledger whitelist accepts the row exactly as before
