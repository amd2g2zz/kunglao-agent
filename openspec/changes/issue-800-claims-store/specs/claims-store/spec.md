# claims-store delta — issue-800-claims-store

## ADDED Requirements

### Requirement: The legal-transition matrix is the only mutation path

claims_store SHALL declare `LEGAL_TRANSITIONS` (status × event →
status) with DEFAULT-DENY for every undeclared pair, and SHALL be the
only module performing semantic claim-status writes for the dispatch
lifecycle. Terminal statuses (status_defs.TERMINAL) SHALL carry no
outgoing edges. Every undeclared transition SHALL be refused at the
store and recorded.

#### Scenario: PROVEN → IN_PROGRESS is refused with a provenance row

- **WHEN** `apply(claim in PROVEN, event=dispatch)` runs
- **THEN** the register is byte-unchanged, the result is refused, and
  `runs/claims-provenance.jsonl` gains one `outcome=refused` row
  naming claim, event, from, to, reason

#### Scenario: PARK without a wake condition is refused

- **WHEN** `apply(event=park)` carries no `wake_condition`
- **THEN** the transition is refused (status_defs carrier-consistency
  rule (f)) with a provenance row

### Requirement: The dispatch approval commits atomically

The dispatch approval+flip+step-open sequence SHALL commit through a
journalled transaction: intent journal before the first write,
per-step journal marks, ONE atomic register rewrite (status +
evidence_tier_attempted + dispatch_count), per-file tmp+rename. The
chosen mechanism is the intent journal + verify (issue option B).

#### Scenario: SIGKILL between mutator steps leaves no partial state

- **WHEN** the committing process is SIGKILLed after step 1 of 3
- **THEN** the next store open recovers the journal: the claim stays
  OPEN, the anchor tail row is gone, the stash is absent,
  dispatch_count is unchanged, and one `outcome=recovered` provenance
  row lands

#### Scenario: a rejected dispatch aborts deterministically

- **WHEN** the gate chain rejects after the approval point committed
- **THEN** abort inverts exactly the applied steps from the journal
  and the #623/#624 faces replay green: no anchor row, claim OPEN, no
  stash, dispatch_count not charged

### Requirement: In-flight claims are not dispatchable

`apply(event=dispatch)` SHALL refuse any from-status other than OPEN.

#### Scenario: double dispatch refused

- **WHEN** a claim already IN_PROGRESS is dispatched again
- **THEN** the store refuses with a provenance row; the frontier sees
  the honest in-flight marker

### Requirement: The rc=2 compensation saga is deleted

dispatch_gate SHALL NOT contain `undo_dispatch_anchor`,
`reopen_claim_no_worker`, or `cancel_step_open`; its rc=2 face is one
journal-driven abort and its rc=0 face confirms the journal.

#### Scenario: grep-clean

- **WHEN** the dispatch_gate source is scanned for the three saga
  names
- **THEN** none appears

### Requirement: Provenance for every transition

Every applied, refused, aborted, and recovered transition SHALL append
one `claims-provenance/1` row (ts, claim, event, from, to, actor,
outcome, reason, journal id).
