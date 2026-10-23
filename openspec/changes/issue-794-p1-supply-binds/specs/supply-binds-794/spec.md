# supply-binds-794 delta — issue-794-p1-supply-binds

## ADDED Requirements

### Requirement: a minted claim carries a birth hypothesis

Every code-level claim mint path SHALL file exactly one OPEN hypothesis
linked to the newborn claim (split fan-out, obstacle promotion),
(claim_id == the new claim) carrying at least one non-empty candidate
(the claim's stated mechanism as H1), pq-bound when the claim answers
a primary question. Stub creation SHALL be idempotent by the
claim-stub marker and SHALL precede the register write (a failed stub
refuses the mint cleanly).

#### Scenario: split fan-out stubs every unit

- **WHEN** mint_split_claims fans a monolithic plan out into sub-claims
- **THEN** hypotheses/ holds one OPEN H-* per minted sub-claim id, each
  with a non-empty candidate and the pq body marker when the parent
  answers a question

#### Scenario: obstacle promotion stubs the new claim

- **WHEN** a failure record promotes an obstacle to a claim
- **THEN** hypotheses/ holds the newborn claim's OPEN stub before the
  register row lands

### Requirement: the sampler draw binds the dispatch

A deviating dispatch SHALL pass only as an explicit recorded decision
with a coherent propensity (> 0): the declared method family must
differ from the gate's own sampler draw only when the
`agent-reasoning:` line is present AND the family is inside the
policy's support. A silent deviation SHALL
REJECT with the sampled family named as the exit. A reasoned deviation
with propensity 0/absent SHALL REJECT with coherence guidance. The
off-registry other(...) escape SHALL keep its quarantine face.

#### Scenario: the 17/17 replay

- **WHEN** the prior holds only family A, the envelope declares family
  B, and no override reason is recorded
- **THEN** the dispatch REJECTS naming A, no usage row is written, and
  no sample_deviation event fires

#### Scenario: coherent override rides the record

- **WHEN** the deviation declares a family with positive policy support
  and carries the override reason
- **THEN** the dispatch passes, the usage row carries
  sampled_family/propensity/prior_source, and the sample_deviation
  event carries the reason and the positive propensity

### Requirement: no hypothesis-less dispatch

A register-recognized claim on a scaffolded-hypotheses workspace SHALL
NOT reach dispatch without at least one linked OPEN hypothesis holding
a non-empty candidate (claim_id map face, or the register row's
hypothesis_ref to an OPEN family). The face SHALL REJECT (exit 2) on
the readable-carrier case and SHALL fail open ONLY on an unreadable
carrier (WARN + trace). It SHALL stay asleep for pre-carrier
workspaces, unknown claims, and verifier-remediation dispatches.

#### Scenario: hypothesis-less claim rejected at the gate

- **WHEN** a scaffolded workspace dispatches a claim with no linked
  open hypothesis
- **THEN** the gate exits 2, the unified log carries
  hypothesis_supply_reject, and the guidance names the one-command fix

#### Scenario: carrier outage fails open

- **WHEN** the hypothesis carrier is unreadable
- **THEN** the dispatch proceeds with a
  hypothesis_supply_fail_open trace (outage tiering only)
