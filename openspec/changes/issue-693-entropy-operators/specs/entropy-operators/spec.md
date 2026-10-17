# entropy-operators delta — issue-693-entropy-operators

## ADDED Requirements

### Requirement: A non-degenerate hypothesis distribution moves entropy while the score stays gated

The entropy face SHALL observe nonzero ΔH whenever the frontier PQ
categorical (`scripts/entropy_face.py` over
`posteriors.PQCategorical`) is non-degenerate and an update arrives
(elimination or evidence). Per ADR-001 the entropy term SHALL NOT
enter any priority score: two workspaces identical except the
degeneracy of their PQ ledger SHALL rank claims byte-identically, and
the entropy face SHALL report the nonzero `h_bits` for the
non-degenerate one (observable-only until the ADR-001 re-entry gate
supplies real-ledger evidence).

#### Scenario: elimination on a non-degenerate categorical buys information

- **WHEN** a two-candidate PQ categorical at equal mass undergoes one
  `update_eliminate`
- **THEN** entropy drops from 1 bit to 0 (ΔH > 0), and a
  single-candidate (degenerate) categorical stays at H = 0

#### Scenario: entropy is observable, never priced

- **WHEN** priority ranking runs over two workspaces whose only
  difference is a degenerate vs a non-degenerate PQ ledger
- **THEN** scores and claim order are identical, while
  `entropy_face.face()` reports the non-degenerate workspace's
  `h_bits` > 0 with its `h_pq` identifier

### Requirement: Invariant pruning rejects impossible candidates before an attempt is spent

The search path SHALL check candidate predictions against invariants
observed on disk (captured output length, loop bounds, input
alignment) BEFORE dispatching an attempt. A prediction that
contradicts an observation SHALL reject the candidate with a reason
naming the invariant, the prediction, and the observation. The
contradiction rule SHALL be per-key: fixed-property invariants
(output length, input alignment) contradict on any difference; the
loop-bound invariant SHALL be a one-sided lower bound (a required
minimum BELOW the observation contradicts; predicting more stays
inconclusive). A dimension the candidate does not predict SHALL be
inconclusive (never a rejection); a malformed candidate row SHALL
survive with a canonical warn (pruning removes impossibilities only —
unknown is not impossible).

#### Scenario: a 32-byte-output candidate dies against a 16-byte capture

- **WHEN** the observed output length is 16 and a candidate predicts
  32
- **THEN** the prune rejects that candidate pre-attempt with a reason
  naming `output_len`, and candidates predicting 16 (or predicting
  nothing about length) survive in input order

### Requirement: A recorded mismatch narrows the search to a named layer and sub-space

A mismatch SHALL be refined CEGAR-shaped by its evidence structure:
no reference constant family matched -> the `family` layer with the
constant-diff sub-space; a family matched but the known-answer test
failed -> the `primitive` layer scoped to that family's core variants;
both confirmed but the digest still mismatches -> the `composition`
layer scoped to assembly orders (padding, concatenation, encoding)
without re-litigating the family. Refinements SHALL mint as OPEN
hypotheses at their named layer (closed vocabulary: family, primitive,
composition); minting at an unknown layer SHALL raise.

#### Scenario: family-confirmed pipeline mismatch localizes to composition

- **WHEN** constant-set diff matches MD5 and the KAT passes but
  `md5(plaintext) != captured`
- **THEN** the refinement names layer `composition` with an MD5-
  assembly sub-space, and the minted hypothesis is open at that layer
  (the family is not refuted)

### Requirement: Termination accounting keys (kind, family, layer)

Layer-scoped death accounting SHALL key cells on the triple
`(kind, family, layer)` so a composition-layer failure never piles
onto a primitive-layer cell. Families without a layer attribution
SHALL land in an explicit `unscoped` bucket (honest absence). Rows
missing kind or method_family SHALL be skipped with a canonical warn,
never fabricating a cell.

#### Scenario: same family, two layers, distinct cells

- **WHEN** two failure rows for one family carry different attributed
  layers
- **THEN** the accounting reports two distinct cells, and an
  unattributed family's row lands in `unscoped`

### Requirement: The covering matrix enumerates the search space through the one t-way implementation

The search face SHALL enumerate t-way covering combinations over
declared transformation domains by delegating to
`replay_equivalence.required_combos` (one enumeration implementation,
two consumers: verification coverage and search enumeration). Each
combination SHALL decode back to the declared domain member values.
An empty variable set SHALL yield an empty matrix; a non-positive
strength SHALL raise.

#### Scenario: a 2x2 domain at strength 2 is the full product

- **WHEN** `covering_matrix` runs over two variables with two values
  each at strength 2
- **THEN** it returns the four combinations with values equal to the
  declared members (not their canonical encodings)

### Requirement: Reference hash constant tables separate reference from mutated mechanically

The system SHALL expose reference constant tables for MD5, SHA-1,
SHA-256, and SM3 (IV plus round constants per their public standard
definitions) through a single read face, and the constant-set diff
SHALL mechanically classify an observed word set: the matching family
(maximum matched words; zero matches anywhere -> no family), whether
the observed set IS the reference table (`exact`), and the sorted
missing/extra word lists. A mutated variant SHALL still identify its
family while failing `exact`.

#### Scenario: one mutated round constant separates from the reference

- **WHEN** the reference MD5 table is observed with exactly one
  T-table word bit-flipped
- **THEN** the diff classifies family `md5`, `exact` false, missing
  the original word, extra the flipped word — and the unmutated table
  classifies `exact` true with empty diffs

#### Scenario: the shipped tables reproduce their standard digests

- **WHEN** each family's compact re-implementation runs with the
  module's own IV + round-constant words over empty / abc / multi-block
  / 256-byte vectors
- **THEN** every digest matches `hashlib` (SM3: the standard's
  published known-answer vector), and a genuine SHA-1 constant set —
  all FIVE IV registers — classifies `exact` true
