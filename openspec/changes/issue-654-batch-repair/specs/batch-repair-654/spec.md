# batch-repair-654 delta — issue-654-batch-repair

## ADDED Requirements

### Requirement: The launch-stash namespace carries a schema wall (1-F3)

`record_launch` SHALL stamp `schema: "dispatch-launch/1"` into every
stash doc, and `append_transition` SHALL refuse (return None with ONE
warn, leaving the stash file intact) any stash doc that carries a
foreign `schema` value or any `status` field. Legacy stashes carrying
neither field SHALL settle unchanged.

#### Scenario: the parked orchestrator envelope is never consumed

- **WHEN** a doc carrying `status: PARKED_NOT_LAUNCHED` and a wake plan
  sits at the typed stash path and `append_transition` fires
- **THEN** the settle returns None with one warn naming the wall and
  the file (wake plan included) still exists

#### Scenario: legacy in-flight stashes keep working

- **WHEN** a stash doc without `schema` and without `status` exists
  (a pre-change launch)
- **THEN** `append_transition` settles it exactly as before

### Requirement: Obstacles carry an invalidation face (1-F9)

`obstacles.record` SHALL accept an optional `env_key`;
`obstacles.retract(ws, obstacle_id, reason)` SHALL write `retracted:
true` + `retracted_ts` + `retracted_reason` into the row file;
`sweep_stale_obstacles(ws)` SHALL retract `missing_env_entry` rows
whose `env_key` maps to a `pass` entry in `runs/env-state.json`; and
`read()`/`face()` SHALL exclude retracted rows.

#### Scenario: a repaired env entry stops feeding the state signature

- **WHEN** an obstacle row `kind=missing_env_entry` carries
  `env_key: adb` and env-state now reports `adb: pass`
- **THEN** the sweep retracts the row with the repair as the reason and
  `face()` no longer counts it

#### Scenario: history is preserved

- **WHEN** the sweep retracts a row
- **THEN** the row file still exists on disk with the retraction
  marker, and unkeyed rows are never retracted by the sweep

### Requirement: Obstacle probe certification is re-checked at read time (4-L6)

`read()` SHALL re-run the probe-marker check on a cited artifact that
still exists and SHALL exclude a present-but-markerless row (ONE warn);
an absent artifact SHALL keep the row (the history posture).

#### Scenario: a rewritten artifact loses certification

- **WHEN** a row's cited artifact still exists but no longer carries a
  probe-execution marker
- **THEN** `read()` excludes the row and emits one warn

#### Scenario: cleaned-up artifacts keep the row

- **WHEN** a row's cited artifact no longer exists
- **THEN** `read()` keeps the row unchanged

### Requirement: Scaffold-aimed prediction discriminators are refused (4-L5)

`prediction_ledger.register` SHALL refuse (None + ONE warn) a
discriminator whose token set intersects `MANDATED_CHECKER_MARKERS`
(the checker's engine-parsed `verdict:` frontmatter line).

#### Scenario: a discriminator aimed at the mandated verdict line dies

- **WHEN** `register` is called with discriminator `verdict:`
- **THEN** the call returns None with a warn naming the scaffold-aim
  and no row lands

### Requirement: Prediction rows carry authorship and unattributed rows cannot settle (5-F4)

`register` SHALL require a non-empty `actor` and stamp
`registered_by` into the row; `settle`/`settle_matching` SHALL refuse
(ONE warn, no settle row) any pending prediction whose row lacks
`registered_by`.

#### Scenario: the raw-append bypass banks nothing

- **WHEN** a pending prediction row without `registered_by` is appended
  to the ledger by hand and its discriminator appears in the evidence
- **THEN** `settle_matching` refuses it with one warn and no settle
  row (ledger history unchanged)

#### Scenario: honest registration settles

- **WHEN** a prediction registered with a non-empty actor matches the
  evidence text
- **THEN** the settle fires and the row carries `registered_by`

### Requirement: The SNIPS comparator skips no-draw rows and cross-checks the π carriers (4-L8)

`policy_compare` SHALL skip decision rows whose audit envelope carries
`declared: true` (counted `skipped_declared_fiat`) and SHALL skip a
decision whose transition-row propensity differs from the audit
envelope's propensity (counted `skipped_propensity_mismatch`, ONE
warn).

#### Scenario: declared-by-fiat rows leave the weighted join

- **WHEN** an envelope carries `propensity: 1.0` and `declared: true`
- **THEN** the decision is excluded from every policy estimate and
  counted in `skipped_declared_fiat`

#### Scenario: a tampered carrier cannot move the verdict

- **WHEN** the transition row's propensity disagrees with the audit
  envelope's for the same (claim, family)
- **THEN** the decision is skipped, counted, and warned — the verdict
  is unchanged by the tampered row
