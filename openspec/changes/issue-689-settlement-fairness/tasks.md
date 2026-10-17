# tasks — issue-689-settlement-fairness

## 1. The sorted observation face + the budget constraint

- [x] `scripts/rlvr/scalar.py`: `SORT_COST_LAMBDA`, `r_sorted` on
  round-credit rows + settlement (additive-when-present; banked reward
  unchanged)
- [x] `scripts/rlvr/scalar.py`: `budget_overrun` (pure; wall at the
  hour scale, one unit per extra retry) folded into attributed waste
- [x] RED: `tests/test_settlement_fairness_689.py` —
  `test_higher_cost_same_output_settles_lower`,
  `test_ladder_receipt_unchanged_by_cost_term`,
  `test_budget_overrun_subtracts_from_r`

## 2. Dispatch counting

- [x] `scripts/dead_letter.py`: `record_dispatch_count` (independent
  field; explicit no-ops; never raises)
- [x] `hooks/dispatch_gate.py`: ALLOW-tail increment (fail-open)
- [x] `scripts/priority_ratio.py`: `dispatch_count_of` / `strikes_of` /
  `attempts_of` (max; legacy fallback); candidate filter on strikes;
  rank feed exposes both components
- [x] RED: `test_dispatch_count_separate_from_promotion_attempts`

## 3. outcome_class

- [x] `scripts/rlvr/scalar.py`: `classify_outcome` (strategy | infra |
  censored; conservative BLOCKED-only infra membership)
- [x] `scripts/rlvr/strategy_store.py`: `outcome_class` rides
  `posterior-store/1` rows additively; `warm_pools` excludes infra
- [x] RED: `test_infra_outcome_not_booked_as_strategy`

## 4. Verification

- [x] three spec deltas registered; `openspec validate
  issue-689-settlement-fairness` exit 0
- [x] focused suite green; neighbor suites green (priority_ratio,
  scalar_settlement, dead_letter/dlq, ws2_warm_start, decide anchors,
  dispatch_gate, worker_budget, absorb_settle, incremental_reward,
  round_credit_alignment)
- [x] comment + formal-code lints clean (baseline tightened
  56→55 on the partial clear)
- [x] deploy manifest re-emitted
