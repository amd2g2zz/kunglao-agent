# Spec Delta

## Purpose

Defines the host wiring of the per-rollout learned deadline timer: a
committed dispatch arms a one-shot deadline, a finished rollout's round
close cancels the timer and learns the outcome, the one-shot cron wake
executes a deterministic graceful-stop closure, and deadline stops are
censored from strategic learning. The policy math (bounds, factors,
clamps) stays owned by the pure core; the host faces only move data.

## ADDED Requirements

### Requirement: A committed dispatch arms its one-shot deadline timer

Every committed dispatch MUST arm exactly one `rollout-timer/1` timer
row whose rollout_id is the dispatch ledger id, whose kind is the
declared method family (fallback `claim`) and whose difficulty is the
workspace difficulty feed's tier (fail-closed `hard`). The arm MUST
publish the wake contract (one-shot cron off the :00/:30 early-fire
window, deadline, wrap-up prompt, `may_start_rollout: false`) to its
rollout_id-keyed entry in the per-rollout wake map
`runs/rollout-timer-wake.json`. The arm face is fail-open telemetry: a
timer failure MUST NOT disturb an approved dispatch. An uncommitted
intent (aborted, recovered, or a failed commit step) MUST arm nothing,
and the post-commit recovery of a COMMITTED journal MUST cancel the
armed timer (cancel-only, no learn — the dispatch never happened).

#### Scenario: Dispatch commit arms the timer

- **WHEN** a dispatch transaction commits (the register flips the
  claim to in-progress)
- **THEN** exactly one armed `rollout-timer/1` row exists with the
  dispatch ledger id as rollout_id, and the wake map's entry carries
  a one-shot cron whose minute is off :00 and :30

#### Scenario: Aborted intent arms nothing

- **WHEN** a dispatch intent is aborted, or a commit step fails and
  the transaction rolls back
- **THEN** no timer row exists and no wake contract was published

#### Scenario: Recover-after-commit discards the timer

- **WHEN** recovery inverts a COMMITTED journal (owner pid dead or
  journal stale before confirm)
- **THEN** the armed timer ends canceled with no budget row written,
  and the register flip is undone

#### Scenario: Cold start budget

- **WHEN** a family has no comparable history
- **THEN** the timer's base estimate is the 30-minute cold-start
  default and the coefficient starts at 1.0

### Requirement: The round close cancels and learns the finished rollout

The round-closure face MUST cancel the finished rollout's timer and
MUST learn its outcome from the run's actuals (the settle receipt's
duration, the bounded table's outcome words), writing one
`rollout-budget/1` audit row per learn carrying coeff_before,
coeff_after, budget, actual, outcome, and reason. A failed worker or a
completion past its budget MUST land the honest no-update word
(`aborted`), never a stretched classification. The wake slot for the
finished rollout MUST be cleared. A claim with no timer (a pre-timer
dispatch) MUST stay a silent no-op.

#### Scenario: Early finish learns a shrink

- **WHEN** a rollout completes at or below 0.6 x its budget
- **THEN** the timer is canceled, the wake slot clears, and the audit
  row records outcome `early` with the coefficient shrunk by the early
  factor

#### Scenario: Failed worker lands no update

- **WHEN** the settled step's outcome is a dispatch failure word
- **THEN** the timer is canceled and the audit row records outcome
  `aborted` with `updated: false`

### Requirement: Deadline-fired rollouts are censored from learning

The round close of a deadline-fired rollout MUST cancel the timer
(post-settlement cleanup) and MUST NOT learn — the deadline stop is
excluded from strategic learning. The fired rows carry
`stop_reason: deadline` and the exclusion marker; the seven-word
disposition vocabulary MUST NOT be extended, and the stop reason MUST
stay outside the closed outcome vocabulary. The median's duration feed
MUST count observed completions only (a timeout's recorded duration is
right-censored at its budget and never enters the family median).

#### Scenario: Late finish after a fired deadline

- **WHEN** a rollout completes after its deadline already fired and
  the wrap-up ran
- **THEN** the round close cancels the timer, writes no new budget
  row beyond the wake's timeout audit, and reports the rollout as
  censored

### Requirement: The one-shot deadline wake executes the graceful stop

The deadline wake MUST fire the timer (a pre-deadline, canceled, or
unknown wake is refused, never force-fired), record the
settlement-facing deadline stop (`deadline_stop_record`'s output with
`stop_reason: deadline` and the strategic exclusion marker), cancel the
timer, learn the timeout, and publish the graceful-stop contract. It
MUST NOT start a rollout. The wrap-up prompt MUST carry GRACEFUL_STEPS
in order and MUST NOT authorize a new rollout.

#### Scenario: The wake fires and learns the timeout

- **WHEN** the one-shot cron wakes at the learned deadline
- **THEN** the timer row flips fired with `stop_reason: deadline`, the
  timeout audit row applies the timeout factor, the timer ends
  canceled, and the receipt JSON carries the stop record and the
  graceful-stop contract

#### Scenario: The wake refuses a not-yet-due timer

- **WHEN** the wake runs well before the deadline (beyond the
  scheduler's early-fire tolerance)
- **THEN** nothing fires, the timer stays armed, and no audit row is
  written

### Requirement: One global coefficient chain until the bucket split

The learned coefficient MUST stay ONE global chain across difficulty
buckets: every update's coeff_before equals the previous update's
coeff_after, and the host MUST NOT pre-empt the bucket split while a
bucket is under its sample floor (the split itself is a later
activation).

#### Scenario: No bucket split under the sample floor

- **WHEN** a bucket reaches the sample threshold but the split
  activation has not landed
- **THEN** a new timer still arms with the single global coefficient
  chain, carrying the bucket key for the future split
