# credit-amendment-731 delta — issue-731-credit-amendment

## ADDED Requirements

### Requirement: A corrected ledger amends the bank

The system SHALL provide an amendment path from the settled ledger
value to the Q-cell bank: when a dispatch's settled ledger value
differs from the mass already banked for it, the settle pass SHALL
append exactly one signed `credit_amendment` row moving the cumulative
mass to the ledger's value, and SHALL NOT rewrite or retract any
existing row.

#### Scenario: the late-cite correction reaches the posterior

- **WHEN** a dispatch is settled and banked at reward r, the ledger is
  later corrected to r' (r' ≠ r), and the settle pass re-runs
- **THEN** one `credit_amendment` row is appended carrying
  Δsuccess = target − effective and Δfailure = −Δsuccess-shaped mass,
  and the fold's cumulative (success, failure) for the dispatch's cell
  equals the band-aware target of r'

#### Scenario: the missed bank is repaired

- **WHEN** the ledger shows a settled dispatch but no settlement-source
  row exists in the observation log (the first bank failed)
- **THEN** the next settle pass performs the full first bank (the
  #712 residual branch included) rather than a delta

#### Scenario: the replay is a no-op

- **WHEN** an already-settled dispatch re-runs with an unchanged
  ledger value and a current bank
- **THEN** no row is appended and the pass reports nothing under
  `amended`

### Requirement: Amendments fold verbatim

A `credit_amendment` row SHALL fold exactly like a `step_calibration`
row: signed Δsuccess (row `credit`) and Δfailure (row `failure_delta`)
applied verbatim, outside the band and the tiebreak, excluded from the
γ EMA, admitted to the Beta posterior. The two signed kinds SHALL be
named once (`SIGNED_CREDIT_KINDS`) and every kind check SHALL read that
definition.

#### Scenario: a negative delta claws back

- **WHEN** a `credit_amendment` row carries credit = −0.4,
  failure_delta = 0.4
- **THEN** the cell's cumulative success drops by the row's weighted
  0.4 and failure rises by 0.4, and the γ schedule's EMA is unchanged
  by the row

#### Scenario: the boundary takes the signed credit

- **WHEN** the append boundary validates a `credit_amendment` row
- **THEN** a negative finite credit is accepted (no [0,1] clamp),
  `failure_delta` is legal, and every other kind keeps its existing
  clamp discipline

### Requirement: The amendment lands in the original cell

`amend_settlement` SHALL resolve the cell identity strongest-first:
the pending dispatch row, then the latest banked settlement row for
the dispatch identity, else the honest gap (no row, no fabrication).

#### Scenario: a pruned dispatch row does not orphan a correction

- **WHEN** the dispatch-time row is absent but banked settlement rows
  exist for the dispatch
- **THEN** the amendment lands using the banked row's
  signature/method_family/arm_key identity

#### Scenario: nothing banked means nothing to amend

- **WHEN** no pending dispatch row and no banked settlement row exist
- **THEN** the amendment writes nothing and reports the honest gap

### Requirement: Amendment rows are source-blind to ad-hoc readers

Amendment rows SHALL carry `source: "credit-amendment"` — distinct
from `"settlement"` — so every reader keying on the settlement source
(the e2e repeat-failure feed, the proposal/level priors, warm pools)
never sees a correction. Only the fold's signed branch, the effective
mass read, and the two named defensive fixes consume them.

#### Scenario: the repeat-failure feed ignores a clawback

- **WHEN** a `credit_amendment` row with negative credit lands and the
  e2e repeat-failure face counts prior same-family settlement failures
- **THEN** the amendment row is not counted (its source differs)

#### Scenario: the OPE propensity survives a clawback

- **WHEN** the observation log holds accumulated negative
  `credit_amendment` rows and `mc_propensity` draws its Beta
- **THEN** the Beta parameters are floored at the +1.0 prior and the
  draw never raises

#### Scenario: a correction is not a new observation

- **WHEN** `cell_count` counts rows at a signature that carries an
  amendment row
- **THEN** the amendment row is excluded from the count
