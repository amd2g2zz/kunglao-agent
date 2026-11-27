# Proposal

## Why

The 2026-11-05 workspace audit (issue-1005) measured the loop acting
but never closing on the decision face: `runs/.convergence_ledger.jsonl`
03:42-04:20 shows repeated `DISPATCH_VERIFIER` decisions with
`partial_count=4, open_count=0, active_workers=0, dispatched_ids=[]` —
the decision repeats while no dispatch happens, because the
dispatch-gate rejection never became a state transition. A verdict the
gate refuses at dispatch time was re-emitted forever: the loop ticked
in place, and a state with partial facts and zero open claims never
reached a terminal decision (verifier dispatch, SURRENDER, or
ATTEMPTED_EXHAUSTED).

## What Changes

- **The gate reject writes a transition row (the S8 face)**: the
  dispatch gate's rc=2 tail — the one point every hard reject exits
  through — appends one `dispatch-reject/1` row into the unified
  experience ledger (`runs/experience.jsonl`, via the consolidated
  family append) carrying the house transition-row vocabulary:
  `claim_ref` / `dispatch_id` attribution, `action_type: "dispatch"`,
  `o.status: "rejected"` with the gate reason in `o.class`, the
  optional `detail` / `trace_id` faces, and the identity `ts`. The row
  shape is identical for every reject reason (granularity, plan-first,
  budget, structural): ONE seam, not per-reason copies. The reason face
  comes from the rejecting sink's identity, stamped at the two shared
  reject helpers plus the drift sink; an un-stamped structural face
  degrades to a named default — the row still lands, never silent.
- **The decision machine gains the feedback pair**: `convergence_check`
  declares `Event.REJECT_SEEN` (backoff flavor) and
  `Event.REJECT_RETRY_EXHAUSTED` (terminal flavor) as a probe pair at
  the FRONT of the SCHEDULE probe list (the insert-before-saturation
  shape: the verdict whose dispatch the gate keeps refusing must never
  mask the feedback), with two TRANSITIONS rows — the backoff routes to
  PARK (the #634 legal-idle face; the action IS the wake condition:
  fix the gate reason or re-anchor, then re-decide), the exhaustion
  routes to terminal BLOCKED whose action names the disposition
  algebra's route-ledger word (ATTEMPTED_EXHAUSTED, consumed — never a
  new vocabulary entry).
- **Bounded retries, pinned constant**: repeated rejects of the SAME
  claim for the SAME reason reaching `REJECT_RETRY_MAX` (a named
  policy constant, pinned at 3 in `rlvr.dispatch_reject`) go terminal;
  sub-max rejects stay in the schedulable backoff flavor. The boundary
  is pinned (2 rejects are not terminal, 3 are). Non-retryable reason
  classes (irreversible-action refusals) land rows for the audit but
  never count — a refusal is not a retry failure.
- **The stuck-state guard**: the feedback fires only when the loop has
  no OTHER actionable move — no dispatchable open claim once the
  bounced claims are subtracted (a rejected dispatch's journal undo
  rolls its claim back to OPEN, so the bounced claim itself would
  otherwise mask the stuck face forever), no active workers — and the
  at-max terminal face is independent of the partial surface (an at-max
  OPEN claim with zero partial facts goes terminal exactly like the
  audited partial-only shape). The audited replay (three same-reason
  rejects over a partial-only, worker-less surface) reaches a terminal
  decision within four decide() calls — the ledger tail shows the
  reject rows and the terminal decision, never a fourth
  DISPATCH_VERIFIER.
- **Quiet-by-scoping**: the feedback fires only for claims still live
  in the register (settled/terminal/suspended history goes quiet) and
  only while the pipeline is still bouncing (an ALLOWED dispatch after
  the last reject — a newer declaration row — recovers the claim), and
  only when the loop has no other move (dispatchable open work other
  than the bounced claims, or in-flight workers, keep the pre-reject
  verdicts). Stale reject rows can never park a recovered or finished
  loop.
- **Pure-read consumer**: convergence_check reads rows (via
  `rlvr.dispatch_reject.feedback_face`), never hooks; the read face is
  fail-open — a broken ledger degrades to the empty face with one warn
  and the machine keeps its pre-reject verdicts.
- **Fail-open producer**: the gate tail's row write never raises into
  the gate (one warn posture, the strategic-declaration writer's
  shape); a failed append never changes the rc=2 verdict.

## Capabilities

### New Capabilities
- `dispatch-reject-feedback`: the dispatch-gate reject feedback loop —
  one appended `dispatch-reject/1` row per hard reject (reason-attributed,
  shape-stable across reasons), the decision machine's backoff/terminal
  feedback pair with the pinned retry max and the stuck-state guard,
  and the quiet-by-scoping rules (live-claim set, allow-after-reject
  recovery) that keep stale history from parking a recovered loop.

### Modified Capabilities
- None (no pre-existing spec store; the PARK verdict and the
  disposition vocabulary this change builds on are defined by existing
  machine/algebra behavior and are consumed here, never extended).

## Impact

- `hooks/dispatch_gate.py` — one new fail-open writer at the rc=2 tail
  (`_log_dispatch_reject`), the reason-face stamps at the two shared
  reject helpers and the drift sink, and the mission-trace stash for
  attribution; no gate VERDICT changes (every reject still exits rc=2
  byte-identically).
- `scripts/rlvr/dispatch_reject.py` (new) — the pure row builder + the
  append face + the reject-row reader + the feedback face (counts,
  active/exhausted classification, live-claim scoping, allow-after-
  reject recovery) + the derived terminal disposition word.
- `scripts/rlvr/consolidated_ledger.py` — the stamp registered in
  NATIVE_SCHEMAS (a dead writer reads 0, never absent).
- `scripts/convergence_check.py` — two Events, two predicates, two
  probe slots at the SCHEDULE front, two TRANSITIONS rows (PARK / 
  terminal BLOCKED), the lazy reject face on the decision snapshot, and
  the conditional `dispatch_rejects` output face (attached only when
  reject rows exist — the frozen anchor matrix stays valid without a
  re-pin).
- Tests: `tests/test_decision_feedback_1005.py` (new) plus the probe-
  order pins (the 595 index pin and the debt-forcing precedence pin
  move down, their intent unchanged) and the affected dispatch-gate /
  decision-machine suites.
- Telemetry: none new (the row rides the registered
  `dispatch-reject/1` stamp; no new event words).
