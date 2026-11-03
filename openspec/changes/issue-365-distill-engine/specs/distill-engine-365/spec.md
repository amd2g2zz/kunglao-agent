# issue-365-distill-engine — delta spec (distill-engine-365)

References the #365 binding rulings (2026-09-23) and the #806 axioms
(A1 output-centric reward, A2 single-model law, A3 growth = derived views,
A4 trust = the reward channel, A5 zero-human).

## ADDED Requirements

### Requirement: A distill item is a pool episode with an additive distill block (A2)

The StandardDistillItem schema `distill-item/1` SHALL be the additive
`distill` block of an `episode/1` pool document with fields:
`source_strategy` ∈ {self, hybrid}; `source_refs` (non-empty list of
source references); `collection_ts` (UTC-Z string); `content`
(`{branch_table, verdict_algebra, pseudocode_groups}` — the methodology
skeleton; at least one component non-empty); `scoring`
(`{generality, self_inspiring, methodology, novelty, total, assessor}` —
numbers in [0,1], assessor a non-empty identity string); `epistemic_class`
∈ {evidence-derived, community-claim, external-derived}; `lineage`
(`{supersedes, superseded_by}` — id strings or empty); `optimization_rounds`
(a non-negative int). The lint SHALL be fail-closed: a block failing any
field rule raises with the offending field named. Items land through the
P1 pool write gate UNMODIFIED; the engine creates NO other storage.

#### Scenario: a well-formed item block validates

- **WHEN** a distill block carries every field with legal values
- **THEN** the lint returns the block and the item rides
  `episode_pool.write_episode` like any episode

#### Scenario: a schema-less item does not exist

- **WHEN** a collection result carries an empty source_refs list, an
  unknown epistemic class, or a scoring total outside [0,1]
- **THEN** the lint refuses with the offending field named and no pool
  write is attempted

### Requirement: 0-1 scoring records every dimension (ruling 4)

Scoring SHALL weight generality 0.3, self-inspiring 0.25,
methodology-shape 0.25, novelty 0.2. The mechanical dimensions SHALL be
computed (decision-rule lint surviving value-stripping; branch-table/
algebra density; recall-delta vs existing pool refs); the model-judged
dimension SHALL ride an injected assessor with the rubric (mechanical
unseen-class proxy only as a labeled `mechanical-proxy` fallback). Every
score result SHALL record all four per-dimension values plus the total and
the assessor identity — never a bare total. An item scoring below the
threshold SHALL be abandoned with a `distill-rollout/1` row at reward 0.01
carrying the reason; the pool is untouched.

#### Scenario: dimension extremes score at the extremes

- **WHEN** a fully case-specific item (every rule names a case token) with
  an empty methodology skeleton, scoring novel-0, is scored
- **THEN** generality, methodology, novelty are 0.0 and the total cannot
  exceed the self-inspiring weight

- **WHEN** an item whose every rule is value-stripped, skeleton at cap,
  no overlap with known refs, judged fully self-inspiring, is scored
- **THEN** all four dimensions are 1.0 and the total is 1.0

#### Scenario: below-threshold abandons with a 0.01 row

- **WHEN** an item's total score is under the threshold
- **THEN** no pool write occurs and a `distill-rollout/1` row records
  reward 0.01 with the abandon reason

### Requirement: The hybrid collection is a research loop, not one-shot (ruling 2)

The hybrid strategy SHALL collect through a hypothesis-driven loop:
hypothesis → search ACTION → SNR gate (a round is fertile iff its results
carry novel-increment over the known corpus) → next hypothesis, capped at
MAX_ROUNDS rounds with per-stage budget caps. Two CONSECUTIVE barren
rounds SHALL abandon the collection (with reason). The search action SHALL
be injectable; the module SHALL perform no network IO of its own (tests
inject a mock). The self strategy SHALL run the SAME downstream pipeline
(clean → schema → score → write gate → rollout row) with no search.

#### Scenario: barren rounds abandon with reason

- **WHEN** two consecutive search rounds return results with zero
  novel-increment over the known corpus
- **THEN** the loop abandons with a barren reason and a 0.01 rollout row

#### Scenario: budget caps are enforced

- **WHEN** the loop reaches MAX_ROUNDS without convergence
- **THEN** the loop stops with the budget reason and no further search
  call is made

#### Scenario: self strategy produces items from a real synthetic workspace

- **WHEN** `--strategy self` runs over a workspace holding a D-gate-passing
  note, a fact, a lesson, and env-state
- **THEN** items are produced through the shared pipeline and scored

### Requirement: distill_rollout settlement rows carry the graded spectrum (ruling 3)

The engine SHALL append `distill-rollout/1` rows (item id, strategy,
score, product card path or abandoned, reward, ts) through the
consolidated settlement family and SHALL register the `distill_rollout`
word in event_taxonomy.EMIT_ACTIONS. Consumption settlement SHALL pay the
bands: consumed+helped 0.5-1.0, consumed-neutral 0.1-0.5, never-consumed
0.01, adverse 0.0. An adverse ruling SHALL require a detour-evidence
reference. Reward history SHALL fold into per-strategy priors.

#### Scenario: every reward band lands in its range

- **WHEN** consumption outcomes (helped/neutral/never/adverse) settle
- **THEN** each reward lands inside its band and the band is recorded

#### Scenario: adverse without evidence is refused

- **WHEN** an adverse settlement carries no detour-evidence reference
- **THEN** the settlement refuses (the 0 face is evidence-gated)

### Requirement: 3-strike optimize-then-remove (ruling 5)

A low-scoring item SHALL be re-scored up to 3 optimization rounds (retrigger
description / recontent / recoverage). A passing round re-admits. All 3
exhausted still below threshold SHALL remove the item from the library
surfaces: the playbook view and recall contexts skip `distill_removed`
items (read-side composition; the P1 faces stay unmodified), while the
document stays on disk and the rollout history stays in the ledger.

#### Scenario: exhaustion removes from surfaces, history archives

- **WHEN** an item fails 3 re-scored optimization rounds
- **THEN** the removal stamp is written, the playbook view no longer
  admits its fragments, and its rollout rows remain readable in the ledger

### Requirement: The D-gate lints the three questions

A runtime note SHALL pass the D-gate only when it carries the three
sections (why this plan order / situation→next-action branches / hidden
reasoning), each present AND non-trivial. `--strategy self` SHALL consume
only lint-passing notes as sources.

#### Scenario: three-question pass/fail

- **WHEN** a note carries all three non-trivial sections it passes; a note
  missing a section or carrying a stub section fails

### Requirement: Conflicts are flagged, never silently resolved

Before landing, the engine SHALL compute recall top-k similarity against
existing pool items; a similarity at or above the conflict threshold SHALL
force an explicit `lineage.supersedes` declaration or refuse the landing.
An `external-derived` item SHALL never supersede an `evidence-derived`
one (the lineage wall).

#### Scenario: a would-be silent overwrite is refused

- **WHEN** a new item is near-identical to an existing ref and declares no
  supersedes
- **THEN** the landing is refused as a conflict and the attempt is flagged

#### Scenario: external-derived never overrides verified

- **WHEN** an external-derived item declares supersedes on an
  evidence-derived item
- **THEN** the lineage wall refuses the supersedence
