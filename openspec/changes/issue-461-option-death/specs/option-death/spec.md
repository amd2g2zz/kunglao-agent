# issue-461-option-death — spec delta: option-death

## ADDED Requirements

### Requirement: Option-death posterior over (obstacle-kind, method-family)

The termination estimator SHALL derive, per workspace, a Beta
posterior for every (obstacle-kind, method-family) cell that has at
least one obstacle/1 row: alpha = 1 + the count of structurally valid
obstacle rows of that (kind, family), beta = 1 + the family's
γ-discounted success mass from the q-cell fold under the shipped DTS
default schedule. Death evidence SHALL be obstacle rows only — an
ATTRIBUTED failure (an intervention probe pinned the cause); a
timeout, a settled failure, or any cause-free failure SHALL contribute
nothing to any cell's alpha. Alive evidence SHALL be outcome
correlation (settled success mass), not narration. The estimator SHALL
be a pure function of the obstacle registry and the q-cell observation
log (no new persistent store, no write path) and its receipt document
SHALL be deterministic: sorted cells, no wall-clock field, corrupt or
absent inputs degrading to the empty report without raising.

#### Scenario: repeated attributed failures cross the threshold

- **WHEN** a family has zero γ-discounted success mass and its
  (kind, family) cell accumulates one, then a second, structurally
  valid obstacle row of the same kind
- **THEN** the cell posterior mean is 2/3 (alive) after the first row
  and exactly 3/4 (dead, at threshold) after the second

#### Scenario: different causes different posteriors

- **WHEN** two workspaces each hold one obstacle row for the same
  family, one of kind detection_trigger and one of encryption_layer
- **THEN** the report holds two distinct cells with distinct
  posteriors, and neither workspace's cell sees the other's death
  count

#### Scenario: cause-free failures never terminate

- **WHEN** a workspace holds settled failure observations (credit 0)
  for a family and no obstacle rows
- **THEN** the family's verdict is not dead and its posterior mean
  never exceeds the base prior's ceiling (no death evidence exists)

#### Scenario: alive evidence revives

- **WHEN** a cell has crossed the threshold and the family then banks
  settled success mass
- **THEN** the cell posterior mean falls with the alive mass and the
  verdict flips back to alive once the mean drops below the threshold

#### Scenario: determinism of the receipt

- **WHEN** the report face runs twice on the same workspace state
- **THEN** the two receipt documents are byte-identical (sorted cells,
  no timestamp, deterministic fold)

### Requirement: Termination decision face at the current signature

The decision face `option_dead` / `verdicts` SHALL declare a family
dead iff at least one obstacle-kind PRESENT in the current state
signature's ob= segment carries a cell whose posterior mean is ≥
DEATH_THRESHOLD (0.75, a policy constant never tuned at runtime). The
verdict SHALL be state-conditioned: kinds absent from the snapshot's
obstacle pattern cannot trigger their cells (within a live workspace
every registry kind is always present — ob= is cumulative — so this
clause is the foreign-snapshot guard, and the live in-workspace floor
is family-global; the operative in-workspace discriminator is the
family-level alive mass). A family with no cells SHALL receive the
base cell Beta(1, 1 + alive_mass) — structurally never dead without
death evidence. When the obstacle registry holds zero rows, `verdicts`
SHALL return an empty mapping (callers thread no death kwarg at all,
so day-one receipts are byte-identical, not only the draws). The
verdict SHALL carry weight_multiplier = ARM_FLOOR (0.1) iff dead, else
1.0. No gate, dispatch, or settlement face SHALL read this module as
an enforcement input; the sampler seam is its only actuation surface,
and the budget forced-closure SHALL remain the safety bound,
unchanged.

#### Scenario: state conditioning

- **WHEN** the registry holds a threshold-crossed cell for a kind, and
  the decision is queried with a snapshot whose obstacle pattern omits
  that kind
- **THEN** that kind's cells do not count and the family is not dead
  under that snapshot

#### Scenario: no cells never dead

- **WHEN** a family has no obstacle rows and any amount of settled
  success mass
- **THEN** its verdict is alive and carries weight_multiplier 1.0

#### Scenario: zero-registry verdicts stay empty

- **WHEN** the workspace's obstacle registry holds no rows
- **THEN** verdicts returns an empty mapping and no death kwarg is
  threaded (receipts byte-identical to the pre-change kernel)

#### Scenario: policy constants pinned

- **WHEN** the module constants are read
- **THEN** DEATH_THRESHOLD is 0.75 and ARM_FLOOR is 0.1 (documented
  policy constants — changing them follows the ADR-001 governance
  pattern, never runtime self-tuning)

### Requirement: DTS sampler consults termination at a floor (floor-not-delete)

`q_cells.sample_method_family` SHALL accept an optional duck-typed
death mapping {family → verdict} and, when present, multiply each
candidate family's sampling weight by that family's verdict
weight_multiplier — a dead option is DEMOTED to floor weight, never
removed from the action space, so it remains samplable and revivable
by new alive evidence (the PARK pattern: suspension, not terminal).
The sampler module SHALL NOT import the termination or obstacles
modules under any import form (the verdict mapping is duck-typed; the
import-direction wall). Absence of the mapping, an empty mapping, or
a multiplier of 1.0 SHALL leave the sampler's DRAW byte-identical to
the pre-change kernel (fail-open; a non-numeric or out-of-range
multiplier degrades to 1.0 with the receipt carrying the effective
multiplier actually applied). The per-candidate receipt SHALL gain an
additive death block (dead, p_dead, effective multiplier) only when a
verdict for that family was supplied. BOTH production sampler hosts
SHALL thread the verdicts fail-open — `rlvr.strategy_store.method_lead`
(the advisory compose lead) AND `scripts/e2e/checkpoints._sample_envelope_family`
(the envelope sampler, the action-selection site banked at the ALLOW
tail): any failure yields no kwarg and the pre-change draw.

#### Scenario: floor demotion with survival

- **WHEN** the sampler draws with a verdict mapping marking one family
  dead
- **THEN** that family's weight is its prior × theta × ARM_FLOOR
  (nonzero — still samplable), the receipt carries its death block,
  and the other candidates are unchanged

#### Scenario: byte identity absent verdicts

- **WHEN** the same store, prior, and rng are sampled with death=None
  and with an empty mapping
- **THEN** both receipts are byte-identical to the pre-change kernel's
  receipt for the same inputs

#### Scenario: import wall holds

- **WHEN** the q_cells source is scanned over every import form
- **THEN** neither rlvr.termination nor rlvr.obstacles appears (the
  sampler is attribution-blind; verdicts are data, not imports)

#### Scenario: seam fails open

- **WHEN** verdict computation raises for any reason at either sampler
  host (strategy_store or the envelope sampler)
- **THEN** the host proceeds with no death kwarg and returns the
  pre-change draw

#### Scenario: the envelope host threads verdicts

- **WHEN** scripts/e2e/checkpoints._sample_envelope_family sources are
  inspected
- **THEN** the verdict threading block sits beside the feature-prior
  kwargs with the same fail-open shape (the action-selection site is
  wired, not just the advisory lead)

### Requirement: EX-6 trap replay A/B experiment

The trap experiment SHALL be a declared-synthetic Monte Carlo replay
of the EX-4 five-step trap trajectory (registered families; the four
failing families deterministically fail with their trajectory kinds
when tried; the breakthrough family succeeds when tried) over three
arms: A the decay-only kernel, B attribution-recording + termination
consultation, and C a cause-free control (termination consulted,
attribution skipped). The replay SHALL run through the real faces
(obstacles.record with probe artifacts, q_cells dispatch and
settlement observation rows, q_cells.sample_method_family, the
termination verdicts) on persistent per-arm workspaces, SHALL record
its non-real faces (a declared uniform P_LLM over the five families —
both production hosts measure the proposal channel; a deterministic
truth-table environment), SHALL disclose the fragmentation asymmetry
(attribution advances ob= per failure, so B's ordinary DTS demotion is
weaker than A's for the same failure count — B's advantage comes from
the termination floor, measured on a conservative baseline), SHALL be
deterministic (byte-identical committed results: fixed ts on every
recorded row, aggregates only — never raw rows or temp paths), and
SHALL record per-arm breakthrough-within-budget rate,
acts-to-breakthrough, wasted acts on dead families, the dead-cell
inventory, and the learning halves. B SHALL reach the breakthrough
family at least as often as A; C SHALL report zero dead cells
(cause-free never terminates).

#### Scenario: dead families terminate under attribution

- **WHEN** arm B's trap families accumulate repeated attributed
  failures across episodes
- **THEN** their (kind, family) cells cross the threshold, are
  floored out of the sampling mass, and the breakthrough family is
  reached

#### Scenario: the breakthrough family stays alive

- **WHEN** the experiment ends
- **THEN** crypto-core-identification holds no dead verdict in any arm

#### Scenario: the cause-free control stays at zero deaths

- **WHEN** arm C's failures record no obstacle rows
- **THEN** its termination report holds zero dead cells and its
  metrics track arm A (the negative control)

#### Scenario: determinism

- **WHEN** the experiment runs twice
- **THEN** the result documents are byte-identical (fixed seeds, real
  faces, temp paths stripped)
