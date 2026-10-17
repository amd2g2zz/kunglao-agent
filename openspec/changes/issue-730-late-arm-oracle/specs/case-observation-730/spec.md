# case-observation-730 delta — issue-730-late-arm-oracle

## ADDED Requirements

### Requirement: The late-arm amendment observes pairs the fresh leg can never reach

The system SHALL provide a sweep that observes every pair
`(oracle case, decisive-terminal claim)` whose claim's `answers_question`
equals the case's `target_pq`, whenever that pair has not already been
observed — so a case armed AFTER its claims settled still observes them.
A decisive-terminal claim SHALL be one whose register status is in
`{PROVEN, VERIFIED}` (pass) or `{NEGATIVE, REFUTED}` (fail). Every other
terminal status SHALL record nothing.

The sweep SHALL write only ARMED cases — a doc carrying all of
`channel`, `hypothesis_ref`, `update_map`, `expected.evidence_refs` and
`mutations`. The arming fields are the acceptance net's own definition of
"a complete, deliberate question-linkage": a doc with a bare
`target_pq` is a stub nobody committed to, and observing against it would
move a posterior on the strength of a placeholder.

Arming is NOT runner-loadability, and this delta does not claim it is.
The arming shape and the runner's loader disagree on the `expected` field
(a mapping with `evidence_refs` vs a non-empty list of entries), so a doc
can be armed-but-not-loadable or loadable-but-not-armed. That mismatch is
a pre-existing defect in the arming definition and is tracked separately;
the observation legs key on the ARMING definition. Retired cases SHALL be
skipped by both legs, mirroring the loader: a case retired out of the
acceptance net must not keep collecting observations.

#### Scenario: a case armed after its claims settled observes them

- **WHEN** a claim settles PROVEN or REFUTED with no case armed, and an
  armed case targeting that question appears afterwards
- **THEN** the next settle pass records one observation for that pair and
  `runs/posteriors.yaml` exists carrying the moved posterior

#### Scenario: the amendment writes no unarmed case

- **WHEN** the only case targeting a settled claim's question is a thin
  (unarmed) doc
- **THEN** the amendment records no observation for it and creates no
  posterior ledger row for it

#### Scenario: a retired case collects no observations

- **WHEN** a case doc carries `status: retired` (out of the acceptance
  net, skipped by the runner's loader)
- **THEN** neither leg records an observation against it

#### Scenario: no fabricated bucket

- **WHEN** a terminal claim has no `answers_question`, its question has
  no linked case, or its status is terminal but not decisive
- **THEN** no observation is recorded by either leg

### Requirement: Each pair is observed exactly once, on either leg

Both observation legs SHALL dedup on the pair `(case_id, claim_id)`, so a
duplicate case id, a duplicate claim, or a second leg reaching the same
pair collapses to one observation. The fresh leg SHALL observe the claims
a pass banks; the amendment SHALL observe the back-fill. Each leg's
observation SHALL carry a `source` of `fresh` or `late-arm` accordingly.

The FRESH leg SHALL keep its existing link — `target_pq` alone, without
the arming filter. Tightening it is a separate behaviour change with its
own blast radius and is not part of this delta.

#### Scenario: arming before settlement

- **WHEN** the case is already armed when the claim settles
- **THEN** the fresh leg records the observation exactly once, and the
  amendment that runs after it records nothing for that pair

#### Scenario: a retry pass cannot re-observe

- **WHEN** a later pass banks a claim an earlier amendment already
  observed
- **THEN** that pair is not observed again and every posterior parameter
  is unchanged

#### Scenario: a re-run amends nothing

- **WHEN** the amendment runs again over unchanged data
- **THEN** it reports zero observations, appends no row, and leaves every
  posterior parameter unchanged

### Requirement: Observations are auditable ledger rows and are their own dedup record

Each observation SHALL append one row to `runs/experience.jsonl` carrying
the schema stamp `case-observation/1` and the fields `ts`, `case_id`,
`claim_id`, `passed`, `source`. The set of already-observed pairs SHALL be
derived from those rows alone; no separate bookkeeping structure SHALL
exist.

#### Scenario: a re-run amends nothing

- **WHEN** the amendment runs again over unchanged data
- **THEN** it reports zero observations, appends no row, and leaves every
  posterior parameter unchanged

#### Scenario: the row names its provenance

- **WHEN** an observation is recorded by the sweep rather than by the
  fresh leg
- **THEN** its row carries `source` = `late-arm` (the fresh leg writes
  `fresh`), so the two legs are distinguishable after the fact

### Requirement: The new schema is visible to the liveness face

A schema born in the consolidated file, with no legacy rel to derive it
from, SHALL be registered so `liveness()` reports its count — pre-seeded
at zero. A dead writer SHALL read dead, never absent.

#### Scenario: a schema with no rows reads zero

- **WHEN** `liveness()` runs on a workspace holding no
  `case-observation/1` rows
- **THEN** the key `experience:case-observation/1` is present and equals 0

### Requirement: The observation legs fail open

A failure inside either observation leg SHALL be reported as a counted
error field plus ONE warn, and SHALL NOT raise into the settle pass.

#### Scenario: a broken write never kills the tick

- **WHEN** the observation write fails
- **THEN** the pass completes, the result carries
  `case_observations_error`, and no exception propagates
