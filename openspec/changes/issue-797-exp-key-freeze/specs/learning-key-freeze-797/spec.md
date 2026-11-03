# learning-key-freeze-797 delta — issue-797-exp-key-freeze

## ADDED Requirements

### Requirement: The learning key is frozen at task open

The learning channel SHALL freeze the task's cell key at task open in a
mint-once doc `runs/learning-key.json` (schema `learning-key/1`)
carrying the task anchor (`task_signature`) and per-family frozen keys.
The anchor SHALL be snapped once (mint-on-read: the first consumer of
the learning channel opens the task) and SHALL NOT move for the task's
life regardless of workspace state drift. A corrupt doc SHALL read as
not-frozen (the honest fact) and the next read SHALL re-open the task
exactly once (one fresh snap at the corruption boundary), never crash
the recording face. The freeze faces SHALL be fail-open telemetry:
they never turn a dispatch ALLOW into anything else.

#### Scenario: the anchor survives a mid-task state change

- **WHEN** the task anchor is snapped on a bare workspace and facts
  then settle (the snapshot's facts/phase dims move)
- **THEN** `task_signature` returns the SAME anchor and every
  `record_dispatch_observation` row in the task carries that one
  signature_hash

#### Scenario: the undeclared-dispatch honest gap mints nothing

- **WHEN** a dispatch declares no method family (the honest gap path)
- **THEN** no learning-key doc is created

### Requirement: The frozen key is family-repeatable across runs

The per-family frozen key SHALL be `q_cells.arm_key` over STRUCTURAL
dispatch dims only (family | recipe | verif | tier [| agent]) — zero
state-derived material — so two synthetic runs of the same-family task
freeze the IDENTICAL key string, and evidence recorded under the frozen
key in different runs accumulates in one fold (the family aggregate
pools both runs' mass). Re-freezing the same family in the same task
SHALL return the original mint-once entry unchanged (different dims and
state drift included) — frozen means frozen.

#### Scenario: two synthetic runs, same-family task

- **WHEN** `freeze_task_key` runs for `static-symbolic` in two fresh
  workspaces
- **THEN** both frozen keys equal
  `static-symbolic|facts_snapshot|none|0` and a fold over one settled
  row from each run pools both runs' mass in the family aggregate

#### Scenario: re-freeze after drift is immutable

- **WHEN** the family is re-frozen after the workspace state changed
  and with different recipe/verif/tier/agent dims
- **THEN** the result carries `created: false` and the original key and
  opened_ts

### Requirement: other-escapes never freeze a learning key

The freeze boundary SHALL refuse a bare `other` token and any
`other(<one-line>)` free-text escape with a ValueError and SHALL write
nothing (the issue-797 panel quarantine: they fragment cells without
learning value). An empty family token SHALL be refused the same way.

#### Scenario: an other() escape is refused

- **WHEN** `freeze_task_key` is called with `other(hotpatch the jsvmp)`
- **THEN** a ValueError is raised and no learning-key doc exists

### Requirement: The dispatch recording face consumes the frozen anchor with a bit-identical legacy path

`record_dispatch_observation` SHALL resolve the row signature through
the frozen task anchor when a frozen doc exists, and through the fresh
per-dispatch state-signature computation otherwise. The no-doc path
SHALL be byte-identical to the pre-change row (lazy consult, fail-open
on any freeze-face failure).

#### Scenario: dispatch rows share one signature across a state change

- **WHEN** two dispatches are recorded in one task with workspace state
  changed between them
- **THEN** both rows carry the same frozen anchor signature_hash

### Requirement: The fingerprint churn rate is measured, with an all-new churn loud and warn-free

The module SHALL provide a pure churn metric over per-run fingerprint
sequences — a fingerprint is NEW when never seen in any earlier run or
earlier in the same run, REUSED otherwise, churn = new / (new + reused)
— and a ledger face reading the experience file's dispatch rows as one
run. churn=1.0 SHALL read verdict `all-new` (the production shape:
loud, structured); a run introducing zero new fingerprints SHALL read
`frozen`; mixed SHALL read `accumulating`; no fingerprints SHALL read
`no-data`. The faces SHALL add ZERO warn() telemetry points (Standard
11) and an unreadable ledger SHALL report the honest gap (a `reason`
field — an unreadable read is a different fact from an empty one).

#### Scenario: the production pathology reads all-new

- **WHEN** three dispatch rows carry three distinct fingerprints (the
  pq-01 shape)
- **THEN** the report reads churn 1.0, verdict `all-new`, distinct 3

#### Scenario: cross-run reuse reads accumulating

- **WHEN** run A sees fingerprints [a, b] and run B sees [a, c]
- **THEN** the report reads new 3, reused 1, churn 0.75, verdict
  `accumulating`

#### Scenario: an unreadable ledger is the honest gap

- **WHEN** the experience ledger rel is not a regular file
- **THEN** the report reads verdict `no-data` with a `reason` set
