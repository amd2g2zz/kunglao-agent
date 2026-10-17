# tasks — issue-690-step-grain

## 1. step-record/2 (the completion grain)

- [x] `scripts/rlvr/step_ledger.py`: STEP_SCHEMA_V2 + `build_step_grain_row`
  + `record_step_grain` + `read_step_grains` (hash-only whitelist,
  re-enforced at append)
- [x] posture note: #670's freeze wall graduates exactly one seam (the v2
  rows + read face are consumed by step_grain)

## 2. The settlement face (SubagentStop)

- [x] `scripts/rlvr/step_grain.py`: `step_id_for`, `aggregate_session_steps`,
  `pending_step` (launch-stash mapping, 1-F3 foreign envelopes skipped),
  `settle_step` (aggregate -> step-record/2 -> append_transition ->
  attributed-waste on wall_s overrun)
- [x] `scripts/rlvr/incremental_reward.py`: `record_launch` carries
  `branch_budget` additively
- [x] `hooks/round_closure.py`: settle face FIRST in the kernel
  (settle -> update -> decide), session_id threaded from the payload

## 3. The sync barrier + the branch act budget

- [x] `scripts/liveness_policy.py`: STEP_SETTLE_TTL_MINUTES (the
  fail-open stale line, rationale attached)
- [x] `hooks/worker_budget_gates.py`: `check_step_settled` (barrier face) +
  `check_branch_budget` (retries hard constraint)
- [x] `hooks/worker_budget_sinks.py`: barrier as FIRST battery gate;
  envelope branch_budget normalized via envelope_v2_defaults;
  `_open_step` at the approval point (record_launch + dispatch_count
  accrual); REJECT_FIXES guidance for both gates
- [x] `scripts/priority_ratio.py`: dispatch_count feed (absent when zero)

## 4. RED tests

- [x] `tests/test_step_grain_690.py`: SubagentStop settlement (incl.
  silent no-pending), barrier block/lift/stale + gate face, session
  aggregation + step_id determinism, wall_s overrun -> attributed-waste,
  retries exhaustion + independent accrual, rank-feed visibility

## 5. Review hardening (round-1 independent review findings)

- [x] CRITICAL — path traversal via worker-writable stash identity:
  `_launch_path` refuses non-token claim/action_type (ValueError ->
  fail-open warn + None in record_launch / append_transition);
  `pending_step` skips such stashes at the read boundary (RED test
  reproduces the deletion, then pins the wall)
- [x] HIGH — orphaned stash after a later-hook REJECT:
  `step_grain.cancel_step_open` (consumes the untyped stash, rolls
  dispatch_count back, idempotent, foreign envelopes intact) wired into
  dispatch_gate's rc=2 undo path; RED tests cover the unit face and the
  dispatch_gate wiring face

## 6. Verification

- [x] targeted suite green (`pytest tests/test_step_grain_690.py -n 2`)
- [x] ruff clean on the touched files
- [x] openspec validate issue-690-step-grain exit 0
- [x] comment-hygiene / formal-code lint baselines re-emitted
- [x] deploy manifest re-emitted (import-closure picks up step_grain)
