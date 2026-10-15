# Spec Delta — issue-719-distill-action

## ADDED Requirements

### Requirement: The action registry SHALL expose online distillation as a selectable orchestration action

The action registry SHALL register `orchestration.distill` at the
orchestration level (alongside `osint` — both are workspace capability
acquisition) with cost 5, a non-empty precondition that reads as
availability OR policy initiative ("the shelf has no viable candidate
for the task at hand OR the policy decides proactive capability
acquisition"), proof-power and consumer metadata in the standard shape,
an unimplemented ΔV-estimator signature stub, and `settleable` false
(distillation changes the tool shelf, never the claim economy's
candidate set). Its `references` SHALL name
`scripts/online_distill.py` and `runs/distill-budget.json` — the
budgeted act is REUSED, never rebuilt. The registry count SHALL be 24
(9 + 6 + 6 + 3) and the claim-category table and default-weight rank
output SHALL remain byte-identical (the frozen capture stays green).
The precondition SHALL NOT read as a firing rule: no trigger
condition ("if shelf thin then distill") may appear anywhere in the
entry — the policy learns WHEN distillation is worth its cost.

#### Scenario: distill is selectable with full metadata

- **WHEN** the registry is loaded and `orchestration.distill` is read
- **THEN** its level is `orchestration`, its cost is 5, its
  precondition / proof-power / consumer are non-empty, its estimator
  stub is unimplemented, its `settleable` flag is false, its
  references name `online_distill` and `distill-budget`, and the
  registry holds exactly 24 actions

#### Scenario: the precondition is availability, not a trigger rule

- **WHEN** the distill entry's precondition is inspected
- **THEN** it states shelf-has-no-viable-candidate OR policy-decides-
  proactive-acquisition, and contains no conditional firing rule

#### Scenario: default-weight ranking is unchanged

- **WHEN** priority_ratio ranks the frozen fixture under default
  weights
- **THEN** the output matches the pre-change frozen capture exactly
  and `DEFAULT_ACTION_WEIGHTS["orchestration.distill"]` is 1.0

### Requirement: Policy distill actuation SHALL ride the existing budget guards

The policy's `distill` choice SHALL reserve ONE budgeted distillation
act through online_distill's existing budget guards
(`online_distill.reserve_act` over `runs/distill-budget.json`): the
per-run act cap, the duplicate-token refusal, the fail-closed corrupt
ledger, and the never-loosen clamp (a stored budget above the engine
ceiling clamps down to `DISTILL_ACTS_PER_RUN`; smaller stored budgets
are honored). The restraint ruling (蒸馏频率不许增) SHALL hold as the
budget cap and NEVER as a rule refusing the action outright. One
actuation returns the engine's attempt receipt or None; a refusal
SHALL be diagnosable through `online_distill.refuse_reason` (cap
exhausted, duplicate token, or unreadable ledger). The reserved act's
scan / retrieve / oracle / land halves stay on the engine's existing
faces — the policy face is the budget linkage only.

#### Scenario: actuation reserves within the per-run cap

- **WHEN** the policy actuates distill on a fresh workspace twice with
  distinct tokens and `DISTILL_ACTS_PER_RUN` is 2
- **THEN** both calls return attempt receipts, `per_run_used` is 2,
  and a third distinct token is refused as `per_run_act_budget_exhausted`

#### Scenario: a corrupt ledger fails closed

- **WHEN** `runs/distill-budget.json` is unreadable and the policy
  actuates distill
- **THEN** the actuation returns None and the refusal reason is
  `budget_ledger_unreadable` — corruption never opens the gate

#### Scenario: a stored budget cannot loosen the ceiling

- **WHEN** the ledger stores `per_run_budget: 99` and the policy
  actuates repeatedly
- **THEN** the clamp holds at `DISTILL_ACTS_PER_RUN` and the act after
  the cap is refused — the policy action cannot buy extra frequency

### Requirement: The reactive shelf-miss path SHALL remain ungated by policy selection

The reactive marker path SHALL remain ungated by policy selection:
shelf-miss marker scan in `online_distill.scan_triggers`, auto-fired
from the e2e tick step `checkpoints._maybe_distill` and the production
closure hook, continues to reserve its budgeted act with NO policy
selection involved. Adding the policy action SHALL be purely additive:
the marker path is defense-in-depth, not a policy choice, and the
policy face is never a precondition on it.

#### Scenario: a marker still auto-fires without policy selection

- **WHEN** a worker status file carries `shelf-miss: crypto:decode
  sample=bins/blob.bin` and the trigger scan runs with no action_space
  involvement
- **THEN** one `shelf-miss` trigger is returned and its budgeted act
  reserves successfully on the reactive path alone

#### Scenario: the tick step still owns the auto-fire

- **WHEN** the e2e checkpoints module is inspected
- **THEN** `_maybe_distill` is still invoked from the tick path and its
  first act is the engine's marker scan
