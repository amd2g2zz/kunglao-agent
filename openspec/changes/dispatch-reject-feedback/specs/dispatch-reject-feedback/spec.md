# Spec Delta

## Purpose

Defines the dispatch-gate reject feedback loop: every hard gate REJECT
is recorded as an attributable `dispatch-reject/1` row in the unified
experience ledger through ONE seam (the gate's rc=2 tail), and the
decision machine consumes those rows so a verdict whose dispatch the
gate keeps refusing transitions the state machine instead of repeating
forever — bounded backoff first, a terminal disposition decision at
the pinned retry max. A rejection that never became a state transition
is replaced by an attributable, bounded, recoverable feedback face.

## ADDED Requirements

### Requirement: Every hard gate reject lands exactly one attributable row

Each dispatch the gate hard-rejects (rc=2, any reason family) MUST
append exactly one `dispatch-reject/1` row to the unified experience
ledger through the gate's single rc=2 tail, carrying `claim_ref`,
`dispatch_id` (equal to `claim_ref`), `action_type` set to
`dispatch`, `o.status` set to `rejected`, the rejecting sink's
identity in `o.class`, the optional `detail` and `trace_id` faces, and
the identity `ts`. The row shape (key set) MUST be identical for every
reject reason; an un-stamped sink's row MUST degrade to a named
default reason, never skip the write. A demoted (rc=0) reject MUST NOT
write a row — the dispatch proceeds, so there is no transition to
record. A failed append MUST NOT change the gate verdict.

#### Scenario: A structural reject on a fresh claim

- **WHEN** a dispatch declaring a forbidden tool surface is hard-
  rejected on a claim with no prior rejects
- **THEN** exactly one row with `claim_ref` equal to the dispatched
  claim, `o.status` equal to `rejected`, and a calendar-valid `ts`
  lands in the ledger

#### Scenario: The plan-first family rides the same seam

- **WHEN** a dispatch is hard-rejected by the plan-first drift sink
- **THEN** the row's key set is identical to the structural family's
  row, with only the reason face (`o.class`) differing

#### Scenario: An allowed dispatch writes no reject row

- **WHEN** a dispatch passes every tooth (rc=0)
- **THEN** no `dispatch-reject/1` row lands for it, and no strategic
  declaration row is consumed by the reject face

#### Scenario: The append fails without changing the verdict

- **WHEN** the experience ledger cannot accept an append during a hard
  reject
- **THEN** the gate still exits rc=2 with the reject guidance intact
  and one loud warn on stderr, never a traceback

### Requirement: The decision machine transitions on reject feedback

The state machine MUST declare the dispatch-reject feedback pair as
SCHEDULE probes ordered BEFORE the verify-forcing flavors, with static
TRANSITIONS targets: the sub-max backoff flavor routes to PARK (the
action names the claim, the count, and the gate reason — the wake
condition), the at-max terminal flavor routes to BLOCKED with the
disposition algebra's route-ledger word (ATTEMPTED_EXHAUSTED) in the
action. `REJECT_RETRY_MAX` MUST be a named constant pinned at 3, and
the terminal boundary MUST be exact: a claim with MAX-1 same-reason
rejects is NOT terminal, a claim with MAX is. The terminal word MUST
be derived from the disposition vocabulary (consumed, never extended).

#### Scenario: A fresh reject changes the decision

- **WHEN** a live claim carries one recent same-reason reject and the
  loop has no other actionable move
- **THEN** decide() returns PARK (not the verify-forcing verdict) with
  the claim and reason in the action and the `dispatch_rejects` face
  attached

#### Scenario: The retry-max boundary

- **WHEN** a live claim carries MAX-1 same-reason rejects, the decision
  is the backoff verdict without the terminal word; when it carries
  MAX, the decision is BLOCKED with the terminal word in the action

#### Scenario: The first-dispatch bounce reaches terminal

- **WHEN** a claim the journal undo rolled back to OPEN carries MAX
  same-reason rejects, zero partial facts, and no other dispatchable
  work
- **THEN** decide() returns BLOCKED with the terminal word in the
  action — the bounced OPEN claim never masks the stuck face or
  re-emits the DISPATCH verdict once per tick

#### Scenario: An unparsed dispatch refusal lands a scoped row

- **WHEN** a structural or lane face hard-rejects a dispatch whose
  payload never parsed to a claim id, with a resolvable workspace
- **THEN** the row lands claim-scoped to the explicit unparsed marker
  (which the feedback face scopes out — the marker is never a live
  register claim)

#### Scenario: The stuck-state replay

- **WHEN** partial facts exist with zero open claims and zero active
  workers, and a live claim has reached the retry max
- **THEN** replaying decide() reaches the terminal BLOCKED decision
  within four calls, and no snapshot in the decision ledger shows the
  verify-forcing verdict

### Requirement: The feedback stays quiet for recovered and closed claims

The feedback MUST fire only for claims still live in the register
(non-terminal, non-suspended), only while the claim's last reject is
newer than its last ALLOWED dispatch (the declaration rows are the
allow evidence), only for RETRYABLE reason classes (an irreversible-
action refusal never increments the per-claim retry count), and only
when the loop has no other actionable move — no dispatchable open
claim once the bounced claims are subtracted, no active workers. The
at-max terminal face MUST be independent of the partial surface: an
at-max claim goes terminal whether or not partial facts exist. A
mixed-reason history MUST NOT exhaust a claim: the retry count groups
same claim + same reason over the claim's COMPLETE dispatch-reject row
set (schema-filtered, window-stable — a burst of newer rows must not
un-exhaust an at-max claim). A broken ledger MUST degrade the face
to empty with one warn — the machine keeps its pre-reject verdicts and
never raises.

#### Scenario: Settled history goes quiet

- **WHEN** a claim's register status is terminal or suspended
- **THEN** its reject rows classify into neither the active nor the
  exhausted set, and the machine's verdict is unaffected

#### Scenario: An allowed dispatch after the last reject recovers

- **WHEN** the claim carries a declaration row newer than its last
  reject row
- **THEN** the claim classifies into neither set and the machine
  returns its pre-reject verdict

#### Scenario: A broken ledger never sinks the machine

- **WHEN** the experience family is unreadable or the feedback face
  raises a layer error
- **THEN** decide() returns the pre-reject verdict, the
  `dispatch_rejects` key stays absent, and the failure surfaces as one
  warn
