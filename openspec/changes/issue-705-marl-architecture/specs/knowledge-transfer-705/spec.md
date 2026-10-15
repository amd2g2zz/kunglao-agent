# knowledge-transfer-705 delta — issue-705-marl-architecture

## ADDED Requirements

### Requirement: A cold agent cell inherits peer evidence through the anchor

`cell_posterior` SHALL include capped peer mass (the leave-one-out
anchor) when an agent queries a family it has no local evidence for but
peers have banked evidence at the same family. The inheritance SHALL NOT
be a local-cell write — the querying agent's own cell stays empty.

#### Scenario: agent B's prior includes agent A's evidence

- **WHEN** agent `analyst` has banked 6 successes and 1 failure at
  `hypothesis-falsification` and agent `verifier` queries the same family
  at a signature it has never touched
- **THEN** the verifier's `(alpha, beta)` exceeds `(1, 1)` — inherited
  mass — and the verifier's cell remains empty in the fold

### Requirement: Negative knowledge is recorded at class level

`scripts/rlvr/marl.py` SHALL expose `signature_class(ws)` — a stable
digest over the workspace's mined structural feature tokens, never over
the instance signature or a case identity. `record_negative` SHALL
append one row keyed `(signature_class, agent_type, method_family)` to a
SHARED class-scoped store (so a different workspace of the same class
inherits the dead end); the workspace's absence of mined features SHALL
degrade to the inert `"unknown"` class, never a fabricated bucket.
Recording SHALL be fail-open: an unwritable store yields no row and
never raises.

#### Scenario: a failed tool chain is recorded under its class

- **WHEN** a workspace whose mined features digest to class `C` records a
  failed `hypothesis-falsification` chain by agent `analyst`
- **THEN** the shared negative store gains a row carrying class `C`,
  agent `analyst`, and family `hypothesis-falsification`

#### Scenario: another class does not see the record

- **WHEN** a workspace of a different mined class reads negative pools
  for the same family
- **THEN** the read returns no failure mass for that family

### Requirement: Negative knowledge discourages the arm through the posterior

`negative_pools` SHALL return duck-typed pools whose failure mass, when
threaded into `sample_method_family`, adds to the anchor face under the
same single SHRINK_CAP and produces an additive `negative_knowledge`
receipt block. Called as
`negative_pools(ws, families, *, agent_type=None, signature_class=None)`,
the pool SHALL raise the cell's posterior β (a dead end is a failure
pseudo-count — it never deletes the arm and never collapses it to zero
probability). Candidates with no negative rows SHALL ride a byte-
identical draw.

#### Scenario: a class-level dead end raises beta and rides the receipt

- **WHEN** a family has class-level negative mass recorded and is sampled
- **THEN** its receipt carries a `negative_knowledge` block and its
  posterior β is higher than the same cell read without the pool

### Requirement: Solution broadcast carries the method, never the answer

`broadcast_solution` SHALL append one `posterior-store/1` row through
the existing guarded store write face (holdout filter + fail-open
telemetry inherited). Called as
`broadcast_solution(ws, *, method_family, agent_type, claim, credit)`,
the row SHALL carry the method family, the agent type, the claim id, and
the credit. An optional `answer` kwarg SHALL be accepted and DELIBERATELY
DROPPED — the broadcast face is method-only by construction, so a
careless caller cannot leak the answer through it — and the claim's
answer text SHALL NOT appear in the row or anywhere in the store's
serialized form.

#### Scenario: a proven claim's method enters the shared posterior

- **WHEN** a claim is proven and `broadcast_solution` is called with its
  method family, the proving agent, the claim id, and the answer passed
  through the dropped `answer` kwarg
- **THEN** the store contains a row whose `method_family` is the method
  and the store's serialized form does not contain the answer literal
