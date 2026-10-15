# issue-690-step-grain — settlement at subagent completion

## Why

Issue #690 (measured on C-005): settlement fired only at claim-terminal
and oracle-case-run — never at subagent completion. One claim spanned
~4 hours between dispatch and PROVEN with ZERO posterior movement;
`runs/transitions.jsonl` was empty in production because
`incremental_reward.append_transition` had no plugin-path caller;
`promotion_attempts` read 0 across 7 dispatches; the dispatch envelope's
`branch_budget` was parsed (#539) with zero consumers. The grain was
wrong: a subagent completion IS one RL step — a 7-act worker and a
1-act worker settled alike, and failures left nothing behind unless
promoted to a REFUTED claim.

## What Changes

1. **step-record/2 — the completion grain** (`scripts/rlvr/step_ledger.py`)
   — one hash-only row per subagent completion carrying `claim_ref`
   (mapped from the dispatch-launch stash) and a deterministic `step_id`
   (session, ordinal). The per-tool-call step-record/1 rows stay shadow
   telemetry; they now AGGREGATE into the completion grain instead of
   being the grain.
2. **SubagentStop is the settlement point** (`scripts/rlvr/step_grain.py`,
   hosted by `hooks/round_closure.py`) — `settle_step` aggregates the
   session's tool-call rows, closes the transition via
   `append_transition` (the missing production caller), and runs FIRST
   in the closure kernel (settle -> update -> decide: compose always
   reads post-settlement state). No pending step = silent no-op.
3. **The sync barrier** (`worker_budget_gates.check_step_settled`, wired
   as the FIRST pre_check battery gate) — zero dispatches issued while a
   prior step is unsettled. Fail-open+warn: a pending step older than
   `liveness_policy.STEP_SETTLE_TTL_MINUTES` (crashed stop) admits with
   ONE warn instead of deadlocking the loop.
4. **branch_budget as a hard constraint** — `wall_s` is priced at settle
   (overrun lands in `runs/attributed-waste.jsonl`,
   `attributed-waste/1`); `retries` bounds the claim's next dispatch
   (`check_branch_budget`); and `dispatch_count` accrues INDEPENDENTLY
   of `promotion_attempts` at every approved dispatch, surfaced in the
   rank feed (absent when zero — legacy feeds stay byte-identical).

## Non-goals

- Parallel fine-grained claims inside MAX_WORKERS (issue proposal #4) —
  this card bounds dispatch churn first; concurrency is the next card.
- Changing Φ, the reward coefficients, or the credit admission rule
  (#667's escrow rule is untouched).
- Worker-contract prompt changes (single-purpose report discipline).
