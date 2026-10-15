# dispatch-count-689 delta — issue-689-settlement-fairness

## ADDED Requirements

### Requirement: Dispatches accrue an independent counter

`record_dispatch_count(workspace, claim_id)` SHALL increment the
claim's `dispatch_count` field only — never `promotion_attempts` (the
DLQ failure-strike counter). A missing claim SHALL return an explicit
`{"counted": false, reason}` no-op, and the writer SHALL never raise
into the dispatch path. The dispatch ALLOW tail SHALL invoke it
fail-open.

#### Scenario: dispatch accrues dispatch_count only

- **WHEN** a claim with `promotion_attempts: 0` is dispatched twice
- **THEN** its `dispatch_count` is 2 and its `promotion_attempts` is
  still 0

#### Scenario: a failure strikes separately

- **WHEN** a dispatched claim later fails
- **THEN** `promotion_attempts` increments and `dispatch_count` is
  unchanged — one failed dispatch is ONE attempt

### Requirement: attempts_of reads the attempt mass, the filter reads the strikes

`attempts_of(claim)` SHALL return `max(dispatch_count,
promotion_attempts)` (legacy registers without the field fall back to
the strikes). The candidate filter SHALL key on `strikes_of`
(`promotion_attempts`) so dispatch churn alone never evicts a claim
from the frontier. The flip-potential decay and the rank feed SHALL
see the attempt mass, with both components exposed.

#### Scenario: churn decays flip potential without evicting

- **WHEN** a claim carries `dispatch_count: 5` and
  `promotion_attempts: 0`
- **THEN** it remains dispatchable (`strikes_of < 3`) and its
  flip-potential feed reports the dispatch component
