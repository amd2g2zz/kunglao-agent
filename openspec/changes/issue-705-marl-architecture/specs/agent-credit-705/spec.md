# agent-credit-705 delta — issue-705-marl-architecture

## ADDED Requirements

### Requirement: Settlement credit decomposes into solve and verification

`observe_settlement` SHALL accept a `credit_kind` of `"solve"` or
`"verification"`, called as
`observe_settlement(ws, dispatch_id, credit, *, phi_delta=None,
credit_kind="solve")`. The default SHALL be `"solve"` and SHALL be
bit-identical to the pre-#705 settlement path. The result dict SHALL
carry `beta_updated: bool` reporting whether the draw's posterior moved.

#### Scenario: the default is the legacy solve path

- **WHEN** `observe_settlement` is called with no `credit_kind`
- **THEN** the settlement row is appended exactly as before and
  `beta_updated` is `True`

### Requirement: Only solve credit is admissible to the Beta posterior

A settlement row carrying `credit_kind: "verification"` SHALL be
recorded (the audit trail shows the verification happened) but the fold
SHALL exclude it from success mass, failure mass, and `n_pending`.
Solve-credit rows SHALL fold exactly as before.

#### Scenario: solve credit moves the posterior

- **WHEN** a dispatch is settled with solve credit 1.0 and the cell is
  folded
- **THEN** the cell's alpha exceeds its pre-settlement value

#### Scenario: verification credit leaves the posterior untouched

- **WHEN** a dispatch is settled with verification credit 1.0 and the
  cell is folded
- **THEN** the cell's `(alpha, beta)` equals the pre-settlement value
  and `beta_updated` is `False`

### Requirement: The cross-task store warms only from solve credit

`strategy_store.warm_pools` SHALL exclude rows whose credit kind is
`"verification"` when building a family's warm anchor. A family whose
only cross-task evidence is verification credit SHALL warm-start from
nothing.

#### Scenario: a verification-only family warms nothing

- **WHEN** the cross-task store holds a single settled row for a family
  and that row carries `credit_kind: "verification"`
- **THEN** `warm_pools` returns no pool for that family
