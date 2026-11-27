# Design

## Context

The dispatch gate hard-rejects dispatches every day (structural tool
surfaces, plan-first drift, budget/admission teeth) and the decision
machine never heard about any of them: the rejection printed, the
journal aborted the attempt, and decide() re-emitted the same verdict
on the next tick. The audit's stuck shape (`DISPATCH_VERIFIER` with
`partial_count=4, open_count=0, active_workers=0, dispatched_ids=[]`,
repeating 03:42-04:20) is exactly that — a decision the gate could not
act on, ticked in place. The learning loop closes only when a gate
REJECT transitions the machine. The two faces already exist in the
house: the ALLOW tail writes declaration rows (the strategic-declaration
change), and the machine consumes experience-family rows through lazy
rlvr leaves (the debt gate). The reject face mirrors both.

## Goals / Non-Goals

Goals:
- Every hard gate REJECT lands exactly one attributable
  `dispatch-reject/1` row (claim_ref, reason, ts) through ONE seam —
  the gate's rc=2 tail — regardless of the rejecting sink.
- The machine's decide() consumes the rows and CHANGES its decision:
  sub-max rejects PARK with a backoff note; same-claim same-reason
  rejects at `REJECT_RETRY_MAX` (pinned at 3) go terminal BLOCKED with
  the algebra's ATTEMPTED_EXHAUSTED word in the action.
- The audited stuck shape replays to a terminal decision within four
  decide() calls; no fourth DISPATCH_VERIFIER.
- Fail-open on both faces; the producer never changes the gate
  verdict, the consumer never manufactures feedback from a broken
  ledger.
- Quiet-by-scoping: live-claim register set + allow-after-reject
  recovery + no-other-move guard keep stale rows from parking a
  recovered, busy, or otherwise-dispatchable loop.

Non-Goals:
- No change to any gate verdict: every reject still exits rc=2
  byte-identically, guidance text untouched.
- No demoted (#801) reject writes a row: a demoted reject returns
  rc=0 and the dispatch PROCEEDS — it is not a state transition.
- No decision-machine writes: decide() stays pure-read (it appends its
  own snapshot ledger row and nothing else); the terminal decision
  carries the disposition WORD — settling the claim through the
  disposition producer remains the orchestrator's move (the producer
  owns the evidence gates).
- No extension of the seven-word disposition vocabulary; the terminal
  word is derived from the route-ledger gate with the documented
  sentinel degrade.
- No new telemetry event words; no new STATE_TABLE machinery beyond
  the two Events + two rows.

## Decisions

### D1. The seam is the gate's rc=2 tail (main()), not per-sink writers

Every hard reject exits `main()` with rc=2; that tail already owned the
reject's consequences (the journal-driven abort). The row write joins
it in its own fail-open envelope. The REASON face is captured where it
exists: the two shared reject helpers (the guidance tail and the
gate-error tail) stamp the sink identity, and the drift sink (which
exits 2 without a helper) stamps its own. Sinks that return rc=2
without a stamp degrade to a named default — the row lands either way.

### D2. A NEW experience stamp, not the `transition/1` vocabulary

The house transition row computes Φ faces and consumes a launch stash;
a reject has neither (the dispatch never started). Reusing
`transition/1` would make a rejected dispatch indistinguishable from
executed evidence for every consumer keyed on (dispatch_id,
action_type) — the orphan-launch sweep would read a rejected dispatch
as settled, and execution-evidence faces would read it as dispatched.
A separate registered stamp (`dispatch-reject/1`, NATIVE_SCHEMAS) keeps
every existing transition consumer byte-unchanged while the row stays
in the same experience family the machine already reads.

### D3. Two Events, one condition family (the #497 ladder-flavor shape)

`REJECT_SEEN` (sub-max backoff → PARK) and
`REJECT_RETRY_EXHAUSTED` (at-max terminal → BLOCKED) are two gradations
of one condition, probed as a pair at the SCHEDULE front. One event
with a data-dependent target state would break the (State, Event) ->
target table discipline; the ladder pair is the house precedent for
splitting gradations into probe-ordered events with static targets.
Escalation precedes the backoff in probe order.

### D4. PARK for the backoff flavor, BLOCKED for the terminal flavor

PARK is the designed legal-idle verdict (suspend on an external gate,
wake condition mandatory) — a gate REJECT IS an external gate refusing
the action, and the issue names park as a legal transition target.
BLOCKED for the terminal flavor: the loop cannot act and needs
orchestrator settlement (the disposition word rides the action); the
issue names BLOCKED the same way. SCHEDULE itself is not a verdict
state, so "stays in scheduling" lands as "stays resumable" (PARK is
wakeable; no dead-end).

### D5. Bounded counting: same claim + same reason, complete evidence

The retry count groups rows by (claim_ref, o.class) over the claim's
COMPLETE dispatch-reject row set — schema-filtered (bounded by this
workspace's own hard-reject history, never by the shared multi-schema
file) and window-stable, so a burst of newer rows can never window an
at-max claim out of its exhaustion evidence. The window bounds only
the declaration-row recovery read (whose latest-row face is
window-stable by construction — the newest row is always inside it).
Mixed reasons do not exhaust a claim (2 rejects for one reason + 1 for
another stay sub-max), and non-retryable reason classes (irreversible
refusals) never count — a refusal is not a retry failure.

### D6. Quiet rules are part of the contract, not an optimization

Three scoping rules keep the feedback honest:
1. live-claim set (non-terminal, non-suspended per the register) —
   settled history never fires;
2. allow-after-reject recovery (the declaration rows are the allow
   evidence) — a dispatch that flowed after the last reject silences
   the claim;
3. no-other-move guard (no dispatchable open work once the bounced
   claims are subtracted, no active workers) — a loop with another
   actionable move keeps its pre-reject verdicts; the feedback is a
   stuck-loop breaker, not a first-reject tax on healthy loops. The
   subtraction is load-bearing: a rejected dispatch's journal undo
   rolls its claim back to OPEN, so the bounced claim itself sits in
   the dispatchable set and would mask the stuck face forever.

## Risks / Trade-offs

- [Probe-order moves] Two structural pins move down (the 595 index pin,
  the debt-forcing precedence pin); both updated with their intent
  unchanged and the new precedence documented. The debt pin keeps its
  guarantee for every pre-existing BLOCKED flavor; the terminal reject
  flavor is the deliberate, documented exception (a claim the gate
  bounces MAX times cannot pay verification debt through dispatch).
- [Per-tick cost] Every SCHEDULE tick now reads the experience family
  (the schema-filtered reject rows — bounded by this workspace's own
  hard-reject history, not by the shared file size — plus the windowed
  declaration rows and a register read). The declaration window and
  the live-window cap keep the recovery face bounded; the reject
  evidence is intentionally complete (windowing it would let a burst
  of newer rows un-exhaust an at-max claim).
- [Anchor matrix] The decision output grows a conditional key only when
  reject rows exist; the frozen anchor cases carry none, so no re-pin.
- [PARK semantics] The backoff PARK is a new producer of the PARK
  verdict; the orchestrator contract (legal idle + wake condition in
  the action) is unchanged.

## Migration Plan

No migration: the stamp is born in the consolidated file (no legacy
rel), registered so liveness pre-seeds it at 0, and the first reject
in a live workspace starts the history. The 2026-11-05 stuck workspace
replays through the seeded fixture in the test suite.

## Open Questions

- None; the brief fixed the constant (3), the seam, and the two
  gradations.
