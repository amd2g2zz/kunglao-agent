# Tasks

## 1. RED — the reject feedback contract

- [x] 1.1 Write `tests/test_decision_feedback_1005.py` RED: a hard gate
  reject (rc=2) on a fresh claim writes EXACTLY ONE `dispatch-reject/1`
  row into `runs/experience.jsonl` carrying `claim_ref`, `dispatch_id`,
  `action_type: "dispatch"`, `o.status: "rejected"` with the gate
  reason in `o.class`, and the identity `ts`; run it, watch it fail
- [x] 1.2 RED: the plan-first family rides the SAME seam — the row key
  set is byte-identical across reason families; a rejected dispatch
  writes no strategic declaration row; an allowed dispatch writes no
  reject row
- [x] 1.3 RED: one reject changes the next decide() output — PARK
  backoff naming claim + reason, never the repeated
  DISPATCH_VERIFIER-with-nothing-dispatched verdict; the boundary pins
  (MAX-1 rejects are not terminal, MAX are) and the constant pinned at
  3
- [x] 1.4 RED: the stuck-loop replay (three same-reason rejects,
  partial>0, open=0, workers=0) reaches the terminal BLOCKED decision
  (the disposition word in the action) within four decide() calls; the
  decision-ledger tail never shows a fourth DISPATCH_VERIFIER

## 2. The pure builder + readers + feedback face

- [x] 2.1 Add `scripts/rlvr/dispatch_reject.py`: `build_reject_row`
  (pure, full validation matrix), `append_reject` (append-only,
  revalidated, no dedupe), `reject_rows` (recent-window reader),
  `REJECT_RETRY_MAX` (named constant = 3), `EXHAUSTED_DISPOSITION`
  (derived from the disposition algebra's route-ledger gate, sentinel
  degrade)
- [x] 2.2 Add `feedback_face` (counts per claim+reason over the recent
  window, active/exhausted classification, live-claim register scoping,
  allow-after-reject recovery via the declaration rows, fail-open to
  the empty face with one warn)
- [x] 2.3 Register `dispatch-reject/1` in
  `consolidated_ledger.NATIVE_SCHEMAS` (a dead writer reads 0, never
  absent)

## 3. The dispatch seam (one tail, every reason)

- [x] 3.1 Add `_stamp_reject` + the reason-face stamps at the two
  shared reject helpers and the drift sink; stash the mission trace id
  for attribution
- [x] 3.2 Add `_log_dispatch_reject` (fail-open writer, the
  strategic-declaration posture) and call it at main()'s rc=2 tail in
  its own fail-open envelope (the journal undo keeps its own)
- [x] 3.3 Verify the gate-driven pins: exactly one row per reject,
  cross-family shape identity, no declaration row on a reject, no
  reject row on an allow, the append failure never changes rc=2

## 4. The decision machine

- [x] 4.1 Declare `Event.REJECT_SEEN` /
  `Event.REJECT_RETRY_EXHAUSTED`, the two predicates (the stuck-state
  guard: partial>0, opens==0, workers==0, live claim at max; the
  backoff guard: no unblocked open work, no active workers, live claim
  sub-max), the probe pair at the SCHEDULE front, and the two
  TRANSITIONS rows (PARK / terminal BLOCKED)
- [x] 4.2 Add the lazy `reject_face()` on the decision snapshot and the
  conditional `dispatch_rejects` output face (attached only when reject
  rows exist — no anchor re-pin)
- [x] 4.3 Update the two displaced structural pins with their intent
  unchanged (the 595 index pin; the debt-forcing precedence pin, whose
  guarantee now covers every pre-existing BLOCKED flavor with the
  terminal reject flavor as the documented exception)

## 5. Documentation + gates

- [x] 5.1 Open the openspec change `dispatch-reject-feedback`
  (proposal / design / tasks + the capability spec delta) and pass
  `openspec validate`
- [x] 5.2 Run the affected suites in ONE invocation (the new file, the
  probe-order pins, the decision-machine matrix, the dispatch-gate
  faces, the hygiene/lifecycle suites) plus
  `scripts/local_gate.py --skip-pytest` expecting ALL GREEN
