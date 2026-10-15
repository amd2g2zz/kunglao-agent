# Spec Delta — the planning tier (issue #684)

## ADDED Requirements

### Requirement: The action registry SHALL carry a policy tier of settleable candidate-set controls

The action registry SHALL register a `policy` level with exactly six
actions: `mint_arm`, `split_claim`, `supersede`, `park`, `rewire_deps`,
`replan`. Each entry SHALL carry the standard registry metadata (cost,
precondition, proof-power, consumer, ΔV-estimator signature stub,
unimplemented) and SHALL be marked `settleable`. Each entry SHALL
REUSE its underlying mechanism by reference (hypothesis-arm minting,
the granularity split fan-out, SUPERSEDED replacement semantics, the
DEFERRED + wake_condition machinery, the claim_deps edge machinery,
plan-drift re-derivation) — the tier makes existing mechanisms
choosable, never rebuilds them. `replan` SHALL live at the policy tier
only (no orchestration-level duplicate). Registry rank output SHALL
remain byte-equivalent under default weights (the frozen capture stays
green).

#### Scenario: the policy tier is complete and replan is not duplicated

- **WHEN** the registry is loaded
- **THEN** the policy level holds exactly {mint_arm, split_claim,
  supersede, park, rewire_deps, replan}, every policy entry has
  `settleable` true and an unimplemented estimator stub, and
  `orchestration.replan` is absent

#### Scenario: default-weight ranking is unchanged

- **WHEN** priority_ratio ranks the frozen fixture under default weights
- **THEN** the output matches the pre-change frozen capture exactly

### Requirement: plan_segment SHALL be a worker-domain verb

`operator.plan_segment` SHALL name the worker as its consumer (plan
authorship under the plan-first contract) and SHALL NOT be settleable.
Its precondition SHALL scope it to sequencing the worker's own plan
steps; it SHALL never be a candidate-set change (that is the policy
tier's exclusive role).

#### Scenario: plan_segment organizes the worker's plan, not the economy

- **WHEN** the `operator.plan_segment` spec is read
- **THEN** its consumer begins with "worker", its `settleable` flag is
  false, and its proof-power remains organizational (zero)

### Requirement: Settleable planning actions SHALL be recorded with their producing step and propensity

`scripts/planning_actions.py` SHALL provide a record face that appends
one schema-stamped `planning-action/1` row per settleable action to
`runs/planning-actions.jsonl`, carrying the action name, the producing
`step_ref`, an optional `claim_ref`, and the optional sampling
`propensity` (float in [0, 1]). The face SHALL consult the registry:
an action that is not settleable SHALL be refused (None + one warn)
and SHALL write nothing. An empty `step_ref` and an illegal propensity
SHALL likewise be refused at the boundary. The module SHALL provide a
read face returning the recorded rows. All refusals SHALL be fail-open
(explicit None + one warn trace, never an exception into the caller).

#### Scenario: a mint_arm record carries propensity and producing step

- **WHEN** `record(ws, "policy.mint_arm", step_ref="call-42",
  claim_ref="C-7", propensity=0.3)` succeeds
- **THEN** the ledger holds one planning-action/1 row with action
  `policy.mint_arm`, step_ref `call-42`, claim_ref `C-7`, propensity
  0.3

#### Scenario: a worker verb is refused and writes nothing

- **WHEN** `record(ws, "operator.observe", step_ref="call-1")` is called
- **THEN** the result is None and the ledger is unchanged (no row)

#### Scenario: an illegal propensity is refused at the boundary

- **WHEN** `record` is called with propensity 1.5 or -0.1
- **THEN** the result is None and no row is written

### Requirement: A recorded planning action SHALL be revocable against its producing step

The module SHALL provide a revoke face: given a recorded action id it
SHALL append one `planning-revoke/1` row naming the action id, the
reason, and the action's PRODUCING `step_ref` — resolved from the
ledger, never caller-supplied. An unknown id SHALL be refused. A
second revoke of the same action SHALL be refused (one revoke per
action). Both refusals SHALL be fail-open (None + one warn). A revoke
SHALL never edit or delete the original action row (append-only).

#### Scenario: supersede is revoked against the step that proposed it

- **WHEN** a `policy.supersede` action recorded with step_ref
  `call-7` is revoked
- **THEN** the revoke row names the action id, step_ref `call-7`
  (the producing step), and the given reason; a second revoke of the
  same id returns None

#### Scenario: an unknown action id is refused

- **WHEN** `revoke(ws, "no-such-id")` is called
- **THEN** the result is None and no revoke row is written
