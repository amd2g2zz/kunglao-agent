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

#### Scenario: applied and refused both leave rows

- **WHEN** one transition applies and one is refused
- **THEN** `runs/claims-provenance.jsonl` gains one row per face, each
  carrying outcome (applied / refused), actor, and the journal id

## ADDED Requirements

<!-- R2 additions (production-log panel 2026-10-23): verification
ordering, terminal idempotency, the dispatch-ledger keyed identity,
bounded missing-rollout audit. -->

### Requirement: Decisive success settlements reference their verification

`apply(event=settle_proven|settle_verified)` SHALL require a non-empty
`verification` reference and SHALL refuse when the referenced
verification timestamp postdates the mint
(`settlement-precedes-verification`). Each refusal SHALL land one
provenance row. Decisive FAIL settlements (settle_refuted,
settle_negative) claim nothing and are exempt. (Production basis: a
PROVEN settlement minted 03:41:02 while the L1 verifier REJECTed 9/9
through 03:41:52; the full verifier binding — calibration, oracle
registration, parser — is card #809, gated on this merge.)

#### Scenario: bare PROVEN mint refused

- **WHEN** apply(settle_proven) carries no verification reference
- **THEN** the transition is refused with reason
  settlement-without-verification, one provenance row lands, the
  register is unchanged

#### Scenario: verification that postdates the mint refused

- **WHEN** apply(settle_proven, verification=<ref>, verification_ts
  later than the mint) runs
- **THEN** the transition is refused with reason
  settlement-precedes-verification, one provenance row lands

#### Scenario: ordered verification applies

- **WHEN** apply(settle_proven, verification=<ref>, verification_ts
  earlier than the mint) runs
- **THEN** the transition applies and the claim is PROVEN

### Requirement: Terminal settlements are idempotent

A decisive settlement on an already-terminal claim SHALL be refused by
the matrix (terminal statuses carry no outgoing edges) and the
register SHALL be unchanged. (Production basis: the same claim settled
3x.)

#### Scenario: double settle refused

- **WHEN** apply(settle_proven) runs twice on the same claim
- **THEN** the second is refused (illegal-transition), exactly one
  applied provenance row exists, the register reads PROVEN

### Requirement: The dispatch ledger is the one keyed identity

Every dispatch SHALL mint ONE dispatch_id at the approval point and
land it on the append-only dispatch ledger
(`runs/dispatch-ledger.jsonl`, schema `dispatch-ledger/1`; rows
state=dispatched/committed/aborted). The q-cell pending dispatch row
SHALL carry the dispatch_id as a foreign key; the settle face SHALL
resolve the real dispatch id from the ledger. A terminal claim with
NO ledger row is a pre-#800 workspace — unsupported per the
no-backcompat ruling (2026-09-01): the settle face reports a loud
off-ledger gap and skips banking (counted in `off_ledger`), never
re-keys under the claim alias. (Production basis: arm/dispatch_id was
NULL on 100% of settlement rows.)

#### Scenario: mint, ledger, and foreign key

- **WHEN** a dispatch approves (begin→commit)
- **THEN** the ledger carries dispatched+committed rows with the SAME
  dispatch_id; the q-cell pending row matches by the real id;
  latest_committed_dispatch resolves it

#### Scenario: off-ledger terminal claim is a loud unsupported gap

- **WHEN** a terminal claim has no dispatch-ledger row
- **THEN** the settle face warns off_ledger, banks nothing under an
  alias, and reports the count; the audit treats the dispatch as
  unbanked

### Requirement: Missing rollouts are loud with bounded repetition

The settle tick SHALL run the missing-rollout audit: every COMMITTED
dispatch whose claim is TERMINAL and that has NO banked settlement row
matched by the REAL dispatch id (the pre-R2 claim alias is not
consulted — no-backcompat ruling) is a gap emitting ONE
`missing_rollout` event per gap. Repetition SHALL be bounded per
plan Standard 11: each gap carries a per-dispatch occurrence count;
the occurrence equal to MISSING_ROLLOUT_REPEAT_LIMIT escalates
(escalated=true — ownership transfer); occurrences beyond the limit
degrade to emit-silence while every pass still reports the gap in the
audit's return. An unreadable q-cell store SHALL skip the claim
fail-open (never a false alarm). (Production basis: C-005 dispatched
+ PROVEN with no settlement row and no warn; 540/593 verbatim-repeated
warns taught that repetition is not escalation.)

#### Scenario: the C-005 silent lie is loud

- **WHEN** a committed dispatch's claim goes PROVEN with no banked row
- **THEN** the audit reports the gap and exactly one missing_rollout
  event lands carrying claim + dispatch_id

#### Scenario: banked under the real dispatch id stays quiet

- **WHEN** the settlement banked under the real dispatch id
- **THEN** no gap is reported, no event fires

#### Scenario: an alias-banked row does not quiet the audit

- **WHEN** the settlement banked only under the pre-R2 claim id
- **THEN** the gap stands and is loud (the ledger id is the one key)

#### Scenario: in-flight dispatches owe nothing

- **WHEN** a committed dispatch's claim is still OPEN or IN_PROGRESS
- **THEN** no gap, no event

#### Scenario: repetition escalates then degrades

- **WHEN** the same gap persists across MISSING_ROLLOUT_REPEAT_LIMIT+2
  audit passes
- **THEN** events fire for occurrences 1..LIMIT with occurrence LIMIT
  marked escalated=true; no event fires beyond it; every pass still
  reports the gap
