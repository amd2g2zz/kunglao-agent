# sorted-reward-689 delta — issue-689-settlement-fairness

## ADDED Requirements

### Requirement: Equal output at higher cost settles lower on the sorted face

`round_credit` SHALL accept an optional per-dispatch `cost`
(caller-normalized units) and, when present, emit `r_sorted = r −
SORT_COST_LAMBDA · cost` on the row and the settlement. The banked
`reward` SHALL remain the ladder value `r` — the cost term is an
ordering/observation field, never the receipt.

#### Scenario: same output, higher cost

- **WHEN** two dispatches settle identical cited artifacts and one
  carries a higher `cost`
- **THEN** both rows carry the same `r`, the higher-cost row's
  `r_sorted` is strictly lower, and both settlements bank the ladder
  `reward`

#### Scenario: no cost supplied

- **WHEN** a dispatch dict carries no `cost` key
- **THEN** its row and settlement carry no `r_sorted` key (legacy
  rows stay byte-identical)

### Requirement: branch_budget overruns book attributed waste

`round_credit` SHALL accept an optional per-dispatch `branch_budget`
and `usage` mapping; when both are present, an overrun (wall above
budget normalized at the hour scale; one waste unit per retry over
budget) SHALL add to that dispatch's attributed waste, subtract from
`r`, and ride the row/settlement as `budget_overrun`. A budget without
a usage (or the reverse) books nothing.

#### Scenario: wall and retry overrun

- **WHEN** a dispatch declares `branch_budget {wall_s: 100, retries:
  1}` and reports `usage {wall_s: 4600, retries: 3}`
- **THEN** its waste includes 1.25 (wall) + 2.0 (retries) = 3.25, its
  `r` is reduced by that amount, and the row carries
  `budget_overrun = 3.25`

#### Scenario: within budget

- **WHEN** a dispatch's usage is within its declared budget
- **THEN** it books no `budget_overrun` and its `waste` is unchanged
