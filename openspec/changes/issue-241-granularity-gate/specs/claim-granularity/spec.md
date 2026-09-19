# claim-granularity delta — issue-241-granularity-gate

## ADDED Requirements

### Requirement: Plan-size gate (K = GRANULARITY_MAX_STEPS = 8)

The system SHALL read the worker-authored plan at the plan-check point
of the execution loop (NOT the first dispatch: post-#239 planning is the
worker's first act, so the gate arms on the approval-point anchor log
identically to plan-first) and SHALL REJECT a dispatch whose claim plan
enumerates more than GRANULARITY_MAX_STEPS (8) steps; padded or trivial
steps ("wait"/"check") SHALL count toward K. A plan with no enumerated
steps block SHALL NOT be size-gated (plan-content belongs to #294).

#### Scenario: monolithic 12-step plan rejected

- **WHEN** a claim with a prior approved dispatch carries a plan
  enumerating 12 steps across 3 mechanism families
- **THEN** the dispatch REJECTS with `REJECT granularity` and the
  message names the plan-size defect, the mint entrypoint, the parent
  claim, and the observed family→steps split

#### Scenario: K boundary

- **WHEN** a plan enumerates exactly 8 steps of one mechanism family
- **THEN** the gate passes
- **WHEN** a plan enumerates 9 steps of one mechanism family
- **THEN** the gate rejects with the plan-size defect

#### Scenario: heading-enumerated steps count

- **WHEN** a plan enumerates its steps as `## Step N` markdown headings
  (with or without a bare `steps:` label)
- **THEN** every heading step counts toward the step count and the
  domain-span classification — a heading-steps monolith REJECTS like any
  other enumeration format

#### Scenario: first dispatch not armed

- **WHEN** a claim has no prior approved dispatch (empty approval-point
  anchor log) and a monolithic plan file sits on disk
- **THEN** the granularity gate passes with the not-armed note
  (post-#239: the worker has authored no plan yet)

#### Scenario: single rejection rule

- **WHEN** a re-dispatch carries no plan on disk and no prompt
  reference
- **THEN** the granularity gate fail-opens (the plan-first gate owns the
  no-plan rejection)

### Requirement: Domain-span gate

The system SHALL classify plan steps into mechanism families and SHALL
REJECT when >= 2 distinct families hold >= GRANULARITY_MIN_FAMILY_STEPS
(2) steps each. The family table SHALL reuse the #234 mechanism-family
vocabulary where it fits (emulation, memory-imaging, dynamic-tracing,
static-unpacking); families outside it SHALL be labelled "(inferred)" in
the guidance. Unclassified steps SHALL NOT manufacture a span (they ride
the dominant classified family; an all-unclassified plan is size-only).

#### Scenario: span on an under-K plan

- **WHEN** an 8-step plan splits 4 static-unpacking + 4 dynamic-tracing
- **THEN** the gate rejects with the domain-span defect only (no
  plan-size defect)

#### Scenario: size-only on a single-family plan

- **WHEN** a 10-step plan classifies entirely as one family
- **THEN** the guidance carries plan-size only, no domain-span

### Requirement: Mechanical split guidance

A granularity REJECT SHALL carry mechanical guidance: the mint
entrypoint (`scripts/claim_granularity.py <ws> --split <C-NN>`), the
parent claim id, and the observed domain split (which steps belong to
which family). Every REJECT granularity SHALL also emit
hookSpecificOutput.additionalContext (#270 census: REJECT_NAMES,
REJECT_FIX_KEYWORDS).

#### Scenario: guidance is mechanical

- **WHEN** the granularity gate rejects a monolithic plan
- **THEN** the message names `--split`, the parent claim, and every
  observed family with its step numbers

#### Scenario: superseded parent is not re-split

- **WHEN** a dispatch is rejected on a parent whose register row carries
  `superseded_by`
- **THEN** the rejection names the successor sub-claims and carries NO
  split directive (re-running --split would be an idempotent no-op)

### Requirement: Split fan-out at creation time (rides #234)

The system SHALL provide `mint_split_claims(ws, claim_id)`: one OPEN
sub-claim per domain group (a group larger than K chunked into units of
<= K steps), origin `granularity-split`, `split_for` the parent, a real
claim_deps.yaml depends_on edge, the `domain_family` tag,
`answers_question` inherited, idempotent on the
(origin, split_for, domain_family, split_chunk) marker. Chunk ordering
SHALL be wired: chunk N+1 depends_on chunk N within the same domain
group (sequential within a domain, parallel across domains). The parent
SHALL be annotated `split_into` and marked SUPERSEDED
(`superseded_by` = sub ids); the ranking face SHALL treat a depends_on
parent carrying `superseded_by` as satisfying the dep gate (lineage
consult alongside the facts face), so the fan-out admits its sub-claims
in any workspace — including one whose facts index already carries a
terminal row. Guarded mints refuse explicitly (no register / parent not
found / no plan / no steps / within threshold).

#### Scenario: split-then-redispatch

- **WHEN** the split is minted for a monolithic claim and a sub-claim's
  worker-authored plan is under K and single-domain
- **THEN** the sub-claim's re-dispatch passes the granularity gate, the
  sub-claims are priority_ratio.is_open, and they rank in the Thompson
  pool

#### Scenario: split ranks in a settled workspace

- **WHEN** the split is minted in a workspace whose facts index already
  carries a terminal row citing an unrelated claim
- **THEN** the minted sub-claims still rank (the superseded_by consult,
  not the zero-rows register fallback, admits them)

#### Scenario: cross-chunk ordering

- **WHEN** a domain group exceeds K steps and chunks into N units
- **THEN** chunk 1 depends_on the parent only, and every later chunk
  depends_on the parent AND its predecessor chunk (sequential within the
  domain, parallel across domains)

#### Scenario: idempotent mint

- **WHEN** mint_split_claims runs twice on the same inputs
- **THEN** the second run returns {"minted": [], "refused": None} and
  the register is unchanged
