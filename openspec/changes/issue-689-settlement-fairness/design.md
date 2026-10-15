# design — issue-689-settlement-fairness

## D1 — the cost term is an observation face, never the receipt

The S3 spike measured the cost term as tie-breaking power alone
(Spearman 0.929 against the ladder ordering). So cost enters as
`r_sorted = r_ladder − SORT_COST_LAMBDA · cost` — a companion field on
the round-credit row and settlement, never a mutation of `reward`. The
Q-cell bank still banks `r`. Same output at higher cost ranks lower on
r_sorted, settles identically on the receipt. The cost input is the
caller's normalized units; the token/hour scale constants live with the
transition ledger (`COST_TOKENS_DIV` / `COST_SECONDS_DIV`), cross-linked
by comment per the DLQ_ATTEMPTS precedent.

## D2 — branch_budget overruns are attributed waste in ladder units

`budget_overrun(branch_budget, usage)` is pure: wall overrun
normalizes at the hour scale (one wasted wall-hour = one waste unit,
the same unit as the ladder); each retry over the declared budget
books one waste unit. Both dimensions must be measured — a budget
without a usage (or the reverse) books nothing (the honest gap). The
overrun folds into the dispatch's waste (subtracted from `r`) and rides
the row as `budget_overrun` for audit. Additive-when-present: a
dispatch dict without the budget/usage pair is byte-identical to
before.

## D3 — dispatch counting is independent of failure strikes

`promotion_attempts` is the DLQ failure-strike counter (dead_letter's
must-ask lane keys on it). Dispatch churn was invisible: a claim
dispatched 7x with zero failures read 0 attempts, so the
flip-potential decay never decayed. `record_dispatch_count` increments
an independent `dispatch_count` register field at the dispatch ALLOW
tail (the one face every real dispatch passes); a failure strikes
`promotion_attempts` separately at completion. `attempts_of` reads
max(dispatch_count, promotion_attempts) — a failed dispatch is ONE
attempt (the strike is a quality signal inside it, never a second
attempt). The candidate filter moves to `strikes_of` (the DLQ face —
dispatch churn alone never evicts a claim from the frontier). The rank
feed exposes both components.

## D4 — outcome_class separates infra refusals from strategy evidence

`classify_outcome` maps TIMEOUT → censored, BLOCKED → infra,
everything else → strategy. Conservative membership: only BLOCKED
classifies infra — a crashed or failed act still carries strategy
signal, a refused act carries none. The class rides `posterior-store/1`
rows additively; `warm_pools` excludes infra rows so an environment
refusal never contributes mass to a warm strategy pool.

## D5 — every seam is additive-when-present

The byte-identity posture of the settlement surfaces is preserved
throughout: `r_sorted`, `budget_overrun`, `dispatch_count`, and
`outcome_class` all ride only when the caller supplied the inputs.
Legacy rows, registers, and stores behave identically.
