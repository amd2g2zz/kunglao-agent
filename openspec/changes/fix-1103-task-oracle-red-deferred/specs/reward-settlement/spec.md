# reward-settlement delta — fix-1103-task-oracle-red-deferred

## ADDED Requirements

### Requirement: task failure settlement matches the real failure path

A task-kind rollout row SHALL settle SETTLED_RED under `task/oracle-red`
when its machine signals carry `oracle_verdict=fail` AND
`claim_terminal` in [NEGATIVE, REFUTED, DEFERRED]. DEFERRED SHALL be an
accepted claim terminal for the red rule: the real failure path defers
the claim (NEGATIVE/REFUTED never occur in recorded data).

#### Scenario: deferred claim with a failed oracle settles red

- **WHEN** `classify` receives a task row with
  `claim_terminal=DEFERRED` and `oracle_verdict=fail`
- **THEN** the settlement is band SETTLED_RED, rule_id `task/oracle-red`,
  reward 0.0

#### Scenario: deferred claim without a failed oracle stays neutral

- **WHEN** `classify` receives a task row with
  `claim_terminal=DEFERRED` and no `oracle_verdict` signal
- **THEN** no red rule matches and the row settles NEUTRAL under
  `task/pending`

### Requirement: every band still needs two distinct machine signals

The rules table SHALL keep the multi-signal anti-pollution floor: every
rule requires at least two distinct signal types, and adding DEFERRED to
`task/oracle-red` SHALL NOT weaken that floor.

#### Scenario: the red rule keeps its dual-signal shape

- **WHEN** the `task/oracle-red` rule is loaded from the rules table
- **THEN** its requires predicates name both `oracle_verdict` and
  `claim_terminal`, and no rule matches on a single signal

### Requirement: settlement values and polarity are unchanged by the version bump

The rules file version rises to 5, and the bump SHALL change no reward
value and no polarity: SETTLED_RED remains reward 0.0 on the negative
polarity face, and every settled row SHALL carry rule_id plus
`evidence_refs` naming the signals that settled it.

#### Scenario: a red settlement carries its audit trail

- **WHEN** a task row settles SETTLED_RED via `task/oracle-red`
- **THEN** reward is 0.0 with negative polarity and `evidence_refs`
  contains a ref for the claim_terminal signal AND a ref for the
  oracle_verdict signal
