# progress-coupling-740 delta — issue-740-progress-coupling

## ADDED Requirements

### Requirement: The round-close runs on input change

The round-close face SHALL compute the queue's input signature —
(claim_id, status, stalled, priority) per entry, excluding time
projections — and SHALL skip both the persist and the emit when the
signature equals the persisted one. A stall-floor crossing, a register
change, or a drain consumption SHALL rebuild and emit exactly once.

#### Scenario: the treadmill is dead

- **WHEN** N consecutive round-closes run over an unchanged register
  within the stall window
- **THEN** exactly one t2_queue_built emit fires (the first) and the
  persisted queue file is byte-identical

#### Scenario: a stall-floor crossing rebuilds

- **WHEN** the clock crosses the stall floor for a claim (no evidence
  change)
- **THEN** the priority class flips, the signature changes, and one
  rebuild+emit fires — the crossing is a real queue-shape change

#### Scenario: the drain keeps its semantics

- **WHEN** a drain consumes the head and the next round-close runs
- **THEN** one rebuild fires (the consumed signature is gone) and the
  pre-existing full-queue rebuild semantics are preserved exactly
