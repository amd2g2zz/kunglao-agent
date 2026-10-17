# issue-689-settlement-fairness — cost, churn, budget, and outcome class in settlement

## Why

Settlement was unfair across worker sizes: the ladder receipt ignored
cost entirely (an offline spike measured the cost term as tie-breaking
power alone — Spearman 0.929 against the ladder ordering), dispatches
were never counted independently of the DLQ failure-strike counter (a
claim dispatched 7x with zero failures read 0 attempts, so the
flip-potential decay never decayed), `branch_budget` was parsed in the
envelope with zero consumers, and infra refusals (BLOCKED — the
measured noise source) booked into the strategy pools as if the
strategy had failed.

## What Changes

1. **The sorted observation face** — `scalar.round_credit` rows gain
   `r_sorted = r − SORT_COST_LAMBDA · cost` (additive-when-present; the
   banked `reward` never moves). Same output at higher cost ranks
   lower on r_sorted, settles identically on the receipt.
2. **The branch_budget hard constraint** — a dispatch dict may carry
   `branch_budget` + `usage`; an overrun books attributed waste
   (`budget_overrun` on the row, folded into `waste`, subtracted from
   `r`). Wall overrun normalizes at the hour scale; each extra retry
   books one waste unit.
3. **Dispatch counting** — `dead_letter.record_dispatch_count`
   increments an independent `dispatch_count` register field at the
   dispatch ALLOW tail; `priority_ratio.attempts_of` reads
   max(dispatch_count, promotion_attempts) (a failed dispatch counts
   once), `strikes_of` keeps the DLQ filter on the failure face, and
   the rank feed exposes both components.
4. **outcome_class** — `scalar.classify_outcome` maps act outcomes to
   strategy | infra | censored; the class rides `posterior-store/1`
   rows additively and `warm_pools` excludes infra rows (an
   environment refusal is not strategy evidence).

## Impact

- Affected code: `scripts/rlvr/scalar.py`, `scripts/rlvr/strategy_store.py`,
  `scripts/dead_letter.py`, `scripts/priority_ratio.py`,
  `hooks/dispatch_gate.py`
- Affected specs: sorted-reward-689, dispatch-count-689, outcome-class-689
- Compatible: every seam is additive-when-present; legacy rows,
  registers without `dispatch_count`, and store rows without
  `outcome_class` behave byte-identically.
