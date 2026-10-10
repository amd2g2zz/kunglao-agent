# evidence-credit-667 delta — issue-667-step-experience-ledger

## ADDED Requirements

### Requirement: Evidence items cite their producing step and carry the certification verdict

`record_evidence` SHALL append an `evidence-item/1` row carrying the
producing step's call id (step_ref), the claim reference, the artifact
sha, and the certification verdict (`certified`) computed upstream by
the fact-certification gate.

#### Scenario: the item names its producing step

- **WHEN** an evidence item is recorded for a step's artifact
- **THEN** the row's step_ref is that step's call_id and the artifact
  rides as its sha

### Requirement: CONFIRM requires certification; revocation targets the producing step

`amend` SHALL enforce the escrow lifecycle: escrow → confirm | revoke |
expire. A CONFIRM amendment SHALL be refused for an item whose
certification verdict is not certified (uncertified evidence can only
expire). A revoke SHALL reference the evidence item (the producing
step's evidence) and SHALL NOT touch the verifier act that confirmed.
Every refusal SHALL be None + ONE warn, never a raise.

#### Scenario: the farming scenario nets zero CONFIRMED credit

- **WHEN** evidence built from two junk files (uncertified by the fact-
  certification gate) is escrowed and a confirm is attempted
- **THEN** the confirm is refused with one warn and the ledger carries
  no CONFIRMED credit for it

#### Scenario: the lifecycle fixtures

- **WHEN** escrow → confirm runs on a certified item, escrow → revoke
  on another, and a third item ages past the TTL then `expire_pending`
  runs
- **THEN** the three amendments land exactly so (confirmed / revoked /
  expired) and the state machine refuses a second confirm on the
  revoked item

### Requirement: The amendment stream replays byte-identically

`replay_credit_ledger(ws)` SHALL re-derive the amendment stream from
the evidence items (escrow per item; confirm iff certified) and the
re-derivation SHALL be byte-identical to the recorded ledger for a
session whose amendments are exactly that pure function.

#### Scenario: a re-recorded session is byte-identical

- **WHEN** the same fixed session is recorded into two workspaces
- **THEN** the step ledgers and the derived credit ledgers are
  byte-identical, and `replay_credit_ledger` equals the recorded file
