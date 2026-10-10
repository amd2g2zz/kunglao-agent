# issue-462-kernel-actuation — spec delta: kernel-actuation

## ADDED Requirements

### Requirement: Compose store adapter returns real learned data

The compose store seam SHALL return a store adapter over the landed
learned-state faces (q-cell observations + the settled ledger + the
DTS schedules): `method_lead` SHALL be a DTS draw over the workspace's
measured PROPOSAL channel — the two proposal faces (dispatch-source
rows + settled `method_family` signals), INTERSECTED with the #432
registered vocabulary (a retired token SHALL never ride the prior;
absent a readable registry the prior degrades unfiltered with a warn —
the #432 vocabulary gate remains the enforcement face) —
and outcome data SHALL NOT enter the prior,
`decayed_weight` SHALL be the γ ladder over the settled stream, and
`cell_count` SHALL count q-cell rows at the state signature. The
seam SHALL NOT silently degrade to a no-learned-content fallback in
any production path; a stale store import SHALL fail loudly.

#### Scenario: seeded workspace speaks

- **WHEN** a workspace holds settled rows declaring one family plus a
  banked q-cell row for it
- **THEN** load_store returns the real adapter, method_lead returns
  that family, and cell_count counts the rows at that signature

#### Scenario: stale import fails loudly

- **WHEN** the store import target disappears or load_store references
  a fallback store again
- **THEN** a tripwire test fails (load_store may never return
  IdentityStore or a nonexistent store face)

#### Scenario: proposals never outcomes

- **WHEN** the q-cell log holds dispatch rows for family A and
  settlement rows for family B only
- **THEN** the proposal prior counts A alone (settlement-source rows
  never skew P_LLM)

### Requirement: Settled round credits reach the Q-cell fold

Round-credit settlement SHALL bank each dispatch's settled ladder
value into the matching Q cell on the first SUCCESSFUL settlement: the
guard SHALL test settlement presence in the folded ledger row (a
record-then-fail retry still banks) and replays/amendments SHALL NOT
re-bank. Unmatched dispatches SHALL record no observation (the honest
gap — never a fabricated bucket); credits SHALL rail-clamp into [0,1]
at the append boundary.

#### Scenario: settle to fold

- **WHEN** a dispatch row exists for a settled dispatch and
  settle_round_credit runs
- **THEN** a settlement-source observation lands with the matching
  (signature, family) and non-None credit, and the fold carries real
  posterior mass

#### Scenario: retry after a failed first settle

- **WHEN** the identity row was recorded but the first settle failed
  and a later run settles successfully
- **THEN** that settlement banks the credit

#### Scenario: replay never double-banks

- **WHEN** settle_round_credit re-runs (duplicate or late-cite
  amendment)
- **THEN** no second settlement observation is appended

### Requirement: Dispatch envelopes carry kernel-sampled method families

Envelope synthesis SHALL sample the envelope's method_family via the
DTS draw when the run declares none: candidates SHALL be the eval
face's proposal channel — the q-cell DISPATCH declarations (outcome
rows excluded; the eval face reads no settled ledger) — INTERSECTED
with the registered vocabulary (a retired token SHALL never ride the
prior — the fail-closed vocabulary gate must not lockstep-reject the
workspace), else uniform over the registered set. A declared proposal SHALL win untampled. The sampled
family SHALL ride inside the v1 envelope AND the audit stream SHALL
record a method_family_recorded row carrying the sampler receipt. A
sampler failure SHALL leave the envelope undeclared and the dispatch
act SHALL still land.

#### Scenario: undeclared run samples

- **WHEN** a run declares no family and the dispatch act mints
- **THEN** the envelope carries a registered sampled family and the
  stream row carries the q-cell-sample/1 receipt

#### Scenario: sampler crash is fail-open

- **WHEN** the sampler raises during envelope synthesis
- **THEN** the envelope mints undeclared (byte-compatible) and the
  dispatch attempt/result rows still land

### Requirement: Strategy composed at decision events and the loop prompt renders it

The round-closure event SHALL compose and version ONE round-strategy
object per decision event (SubagentStop with a marker-resolved
workspace; tick = the machine-independent round axis; unchanged
content dedups by content_hash — at most one NEW object per event) and
SHALL emit the consumer-seam projection shaped `{schema, round,
sections:[{title, body}]}`. The
live loop-prompt seam SHALL render non-empty strategy sections when
the strategy speaks. A silent (lead-less) strategy SHALL render
NOTHING through the seam regardless of budget telemetry. The seam
SHALL be deterministic for the same strategy object and self-healing
(deleted or non-UTF-8-corrupt seams re-emit; a seam failure never
breaks the versioned write).

#### Scenario: loop prompt renders strategy content

- **WHEN** a speaking strategy is written and the strategy-seam
  consumers render
- **THEN** the rendered content is non-empty and carries the method
  lead; the workguard turn-exit guidance carries the sections

#### Scenario: cold silence is unconditional

- **WHEN** a below-threshold strategy is written on a workspace WITH
  budget telemetry
- **THEN** the seam file holds zero sections and the consumers render
  nothing

#### Scenario: injected content changes with evidence

- **WHEN** contradicting settled evidence lands between two decision
  events
- **THEN** the second injection visibly differs and cites the new
  ledger row

### Requirement: Production round closure drains the T2 queue

The production round-closure face SHALL build AND drain the T2
unblocking-value queue (not eval-only): the queue head is consumed at
round close and the drained remainder persists. Every kernel face at
the closure SHALL be fail-open (a kernel failure is one rate-limited
warn; the closure row still lands; the subagent's own stop path is
never disturbed).

#### Scenario: production closure drains

- **WHEN** a SubagentStop fires on a workspace with an open claim
- **THEN** runs/t2-queue.json persists with the drained head in
  dispatched/remaining shape

#### Scenario: compose-face failure isolates

- **WHEN** the compose write face fails at the closure
- **THEN** the T2 face still builds and drains, the closure row lands,
  and rc stays 0

### Requirement: Single decision source

The kernel SHALL remain the single strategy composer: no face outside
the compose single-point shall mint strategy content, and the DTS
envelope sampler's consumers SHALL be kernel faces only (the compose
store adapter on the production path; the dispatch-envelope synthesis
on the eval path). Envelope byte-shape compatibility for undeclared
or failed-sample runs SHALL be preserved.

#### Scenario: one composer

- **WHEN** any strategy-derived content reaches a consumer
- **THEN** its producer is compose (the tick ledger or its derived
  seam projection)
