# testing — #807 amendment

## ADDED Requirements

### Requirement: Bloat inventory precedes deletion
The system SHALL provide `scripts/test_inventory.py` which classifies every
test function in `tests/` into zero or more bloat classes
(mock-shape-only, generated-file golden, dead-code pin,
parameter-redundant) and emits per-class counts plus per-test detail.
The committed inventory SHALL exist before any deletion PR content.

#### Scenario: inventory runs over the real suite
- **WHEN** `uv run python scripts/test_inventory.py --tests-dir tests` is run
- **THEN** it exits 0 and writes JSON with keys `totals` (files,
  test_functions) and `classes` (per-class counts + member lists).

### Requirement: Ratchet floor file is raise-only
`coverage-floor.json` SHALL carry `schema`, `floor`, `min_floor`,
`measured_set`, `baseline_measured`. The ratchet SHALL be seeded at the
recorded measured baseline (hygiene-baseline precedent: seed at truth;
a seed more than 5% below the recorded baseline is refused). `min_floor`
(70.0) is the immutable climb target — a guard test SHALL fail when the
target is lowered or when a PR's floor is lower than the base branch's
floor (CI: `scripts/coverage_floor.py monotone --base-ref`). The CI
`check` step SHALL fail when measured coverage is below `floor` and
SHALL print the climb gap while `floor` is below `min_floor`.

#### Scenario: lowering the ratchet fails a test
- **WHEN** the monotone comparator is given base floor 72.0 and candidate 70.0
- **THEN** it reports a violation (exit non-zero / violation=True).

#### Scenario: raising the ratchet passes
- **WHEN** base floor 70.0 and candidate 75.0
- **THEN** no violation.

#### Scenario: base branch has no ratchet yet
- **WHEN** `monotone` runs and the base ref carries no coverage-floor.json
  (the ratchet-introducing PR)
- **THEN** monotonicity is vacuously satisfied and the step passes.

### Requirement: CI enforces the floor on the measured set
release-check.yml SHALL generate `coverage.json` over `--cov=scripts
--cov=hooks` and run `scripts/coverage_floor.py check` failing the job when
the measured percent is below `coverage-floor.json:floor`.

#### Scenario: below-floor measurement is red
- **WHEN** coverage.json totals.percent_covered = 65.0 and floor = 70.0
- **THEN** `check` exits 2 with a message naming measured, floor, and the
  raise-path (real tests, never bar-lowering).

### Requirement: Coverage policy (amends #564 observation-only)
Coverage at the pytest.ini / local level REMAINS observation (no
`--cov-fail-under` anywhere — guard retained). The scoped measured set
(scripts/ + hooks/) in CI is ENFORCED at the ratchet floor (#807).
`tests/test_coverage_policy_564.py` SHALL assert the amended policy: the
three config surfaces document the #807 amendment; `coverage-floor.json`
exists, is valid, and floor >= 70.0; release-check.yml carries the floor
and monotone steps.

#### Scenario: policy guard accepts the amended state
- **WHEN** the guard suite runs against a tree with the floor wired
- **THEN** all #564 guard tests pass with the amended markers (#807 present,
  no raw --cov-fail-under reintroduced).

### Requirement: Production-shape replay gate (Standard 12)
The system SHALL provide `devkit/production_replay_gate.py`: a fixture
loader (`production-shape/1`, synthetic-by-contract) plus an assertion
runner that replays committed shape fixtures
(`devkit/production_shapes/`) through registered assertions. Fixtures
distilled from real production runs SHALL be SYNTHETIC (counts, field
names, ordering faces and template tokens only — raw logs carry user
content and never enter the repo). The registration surface SHALL stay
open for the cross-card assertions (#801 unbounded-warn circuit
breaker, #800 orphan settlement / missing_rollout, #809 false-reject);
this card implements only the infrastructure and its own INV-003 face.
The gate SHALL NOT add telemetry warn points (Standard 11: structural
report rows + exit codes instead).

#### Scenario: INV-003 family-level face replays both ways
- **WHEN** the arm-NULL production-shape fixture (posterior-store rows
  with no arm attribution) is replayed through the built-in
  `inv003-posterior-family-key` assertion
- **THEN** the rl-posterior-moved fingerprint reads FAIL and the
  assertion passes (the sentinel must reject it).
- **WHEN** the arm-keyed control fixture is replayed
- **THEN** the fingerprint reads PASS.

#### Scenario: raw log content cannot enter the fixture set
- **WHEN** a fixture declares `synthetic: false`
- **THEN** the loader refuses it (ValueError).

### Requirement: INV-003 is a family-level liveness signal
`devkit/liveness_fingerprints.json` `rl-posterior-moved` SHALL count
only posterior-store rows carrying a NON-EMPTY arm key (`arm_key` or
`arm`): case-level movement — key-less rows, dispatch-pending
structural mass, or credits with no arm attribution — SHALL NOT
satisfy the sentinel. `devkit/invariants/registry.json` INV-003 SHALL
state the family-level semantics, and a guard test SHALL pin the
arm-NULL broadcast shape as RED.

#### Scenario: production broadcast shape is red
- **WHEN** a workspace's posterior store holds only key-less rows
  (the two 2026-10 production runs' shape)
- **THEN** `devkit/liveness_gate.py --ledger <ws>` FAILS
  rl-posterior-moved.
