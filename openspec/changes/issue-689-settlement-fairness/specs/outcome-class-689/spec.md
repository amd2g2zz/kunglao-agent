# outcome-class-689 delta — issue-689-settlement-fairness

## ADDED Requirements

### Requirement: Act outcomes classify into strategy, infra, or censored

`classify_outcome(o_status)` SHALL map TIMEOUT to `censored`,
BLOCKED to `infra`, and every other outcome to `strategy`. The
membership SHALL be conservative: only BLOCKED classifies infra (a
crashed or failed act still carries strategy signal; a refused act
carries none).

#### Scenario: the vocabulary

- **WHEN** the classifier reads BLOCKED, TIMEOUT, and DISPATCHED
- **THEN** it returns infra, censored, and strategy respectively

### Requirement: infra outcomes never warm a strategy pool

`append_store_row` SHALL carry an optional `outcome_class` additively
(absent when not supplied — legacy rows stay byte-identical).
`warm_pools` SHALL exclude rows whose `outcome_class` is `infra` so an
environment refusal contributes no mass to a warm strategy pool.

#### Scenario: the infra refusal is invisible to the pool

- **WHEN** a store carries one infra row (credit 0.0) and one strategy
  row (credit 1.0) for the same family, and another workspace reads
  the warm pool
- **THEN** the pool counts exactly one contributing row (the strategy
  row)
