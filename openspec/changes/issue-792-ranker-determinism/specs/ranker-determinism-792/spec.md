# ranker-determinism-792 delta — issue-792-ranker-determinism

## ADDED Requirements

### Requirement: same inputs produce a byte-identical ranking at any round

The M1 ranker SHALL be a pure function of (posterior ledger, claims,
weights): identical inputs SHALL produce byte-identical ranking output
(scores, order, feeds, view stats) at any round index. The ranker SHALL
NOT consume a round counter, wall clock, environment variable, or any
other hidden state. The rank_feeds event fingerprint SHALL pin the full
input face — claims hash, evidence-view hash, posterior hash, round —
so every ranking is recomputable from the event tail alone; the retired
`rng_base` field SHALL be recorded as null.

#### Scenario: static posteriors across advancing rounds rank identically

- **WHEN** the same register (linked and unlinked claims) is ranked at
  five advancing rounds against a static posterior ledger
- **THEN** all five rankings are byte-identical and every rank_feeds
  payload differs only inside `input_fingerprint.round`

#### Scenario: a runner verdict moves the value

- **WHEN** a linked case's posterior moves green (alpha 2 -> 6)
- **THEN** the linked claim's score rises at the same round — evidence,
  not the round axis, moves the rank

### Requirement: unlinked claims have no fabricated value

A claim whose `answers_question` matches no oracle case `target_pq`
SHLL carry no value: its case value SHALL be 0.0 (no prior draw), it
SHALL rank below every value-bearing claim, its in-band order SHALL be
the declared deterministic default (downstream_term, tier, worth), and
its `case_value` feed SHALL say
`unlinked — no value channel (arm oracle cases / set answers_question)`.

#### Scenario: unlinked noise cannot outrank the value face

- **WHEN** a claim linked to a positive-mean posterior is ranked with
  four oracle-unlinked claims
- **THEN** the linked claim ranks first and every unlinked row carries
  the unlinked hint in feeds

#### Scenario: a cold linked case folds the neutral prior mean

- **WHEN** an oracle case file exists but the posterior ledger has no
  entry for it
- **THEN** the claim's score is exactly 0.5 (the declared Beta(1,1)
  prior MEAN), never a random draw

### Requirement: linked value is monotone in posterior evidence

The linked value face SHALL be `Σ αᵢ/(αᵢ+βᵢ)` over linked case
posteriors. Score order SHALL follow posterior-mean order, and raising
alpha (holding beta) SHALL raise the score.

#### Scenario: score order follows posterior-mean order

- **WHEN** six claims link to cases with posterior means .10 through
  .85 and the register is ranked
- **THEN** the score list equals the mean list sorted descending, with
  no draw-induced inversion

### Requirement: exploration is a declared, labeled slot

Exploration SHALL exist only as the explicit `EXPLORE_EVERY_N_ROUNDS`
slot (default 0 = off). When enabled and the round hits the slot, the
best unlinked (or lowest-attempts) claim SHALL be promoted to the front
and labeled `exploration_arm` in feeds; value scores of all rows SHALL
be unchanged. The promoted arm SHALL never be conflated with the value
column.

#### Scenario: the slot promotes and labels without touching the value column

- **WHEN** the slot is enabled (every 2 rounds) and the register is
  ranked at round 4, then again with the slot off
- **THEN** the enabled run's top row is an unlinked claim carrying the
  `exploration_arm` feed, its score equals the plain run's score for
  the same claim, and no row in the plain run carries the label

### Requirement: a recorded deviation carries a positive propensity

The dispatch-gate reconciliation (`strategy_store.reconcile_declaration`)
SHALL record propensity > 0 for every deviating declaration: a declared
family inside the sampler's candidate set keeps its exact share; a
declared family outside the candidate set SHALL be recorded at
`DEVIATION_PROPENSITY_FLOOR / (total + DEVIATION_PROPENSITY_FLOOR)`
(the recorded-decision override channel's declared mass). The 0.0
recording (production: 6/16 deviation rows) SHALL NOT reappear.

#### Scenario: an out-of-support declaration replays with positive propensity

- **WHEN** the workspace history prior holds families A and C, and a
  dispatch declares registered family B (no history mass) that the
  sampler did not propose
- **THEN** the reconciliation view reports `deviates: true` with
  `propensity > 0`, and the `sample_deviation` event carries the same
  positive propensity

#### Scenario: an in-support declaration keeps its exact share

- **WHEN** the declared family is inside the sampler's candidate set
- **THEN** the recorded propensity equals its candidate weight share
  byte-identically (the floor never touches in-support arms)
