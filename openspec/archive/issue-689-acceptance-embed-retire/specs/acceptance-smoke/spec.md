# acceptance-smoke spec — #689

## ADDED Requirements

### Requirement: `_check_test_suite` SHALL run a pinned smoke subset, not the full suite

By default `scripts/acceptance_check.py::_check_test_suite` SHALL run pytest over the
nodeids listed in `scripts/acceptance_smoke.txt` (one nodeid per line; `#` comments and
blank lines ignored), NOT over the whole test suite. The invocation SHALL keep
`-q --tb=no -p no:cacheprovider` and `--ignore=tests/test_acceptance.py` (self-recursion
guard: a pinned acceptance nodeid would otherwise recurse). An empty or missing manifest
SHALL fail the check with an error detail (never silently pass).

#### Scenario: default run
- **WHEN** `_check_test_suite()` is called with no arguments
- **THEN** a single pytest subprocess runs only the pinned nodeids under a flat
  `SMOKE_SUITE_TIMEOUT` budget, completing end-to-end in well under 60s on an idle
  machine, and the result detail carries a `[smoke:N]` prefix (N = manifest size)

#### Scenario: manifest entry drift
- **WHEN** a pinned nodeid no longer exists (test renamed/deleted)
- **THEN** pytest exits nonzero ("no tests ran"/collection error) and the check FAILS
  with the tail of pytest output in `detail` — the manifest cannot silently shrink

### Requirement: full-suite enforcement SHALL live only in Gate 2

The always-on full-suite pytest enforcement SHALL live only in `devkit/quality_gates.py`
Gate 2 (Regression Safety). `acceptance_check` MUST NOT embed a full-suite run in any
test-invoked default path. An explicit operator channel SHALL remain: running
`acceptance_check.py` with `--full` (or `run_acceptance(full_suite=True)`) runs the
full suite (minus `tests/test_acceptance.py`) under a flat `FULL_SUITE_TIMEOUT` budget.

#### Scenario: operator explicit full run
- **WHEN** `python scripts/acceptance_check.py --full` is executed
- **THEN** the embedded run covers the whole suite except `tests/test_acceptance.py`
  and the `test_suite_green` detail carries a `[full]` prefix

#### Scenario: pytest never nests pytest by default
- **WHEN** the default acceptance path runs inside the suite (as `tests/test_acceptance.py` does)
- **THEN** the subprocess duration is bounded by the smoke subset (seconds), so suite
  total cost is linear in suite size, not quadratic

### Requirement: the full-suite timeout budget machinery SHALL be retired

The full-suite budget machinery in `scripts/acceptance_check.py` SHALL be retired: the
symbols `TEST_SUITE_TIMEOUT`, `TEST_SUITE_TIMEOUT_CEILING`, `TEST_SUITE_TIMEOUT_ENV`,
and `_test_suite_timeout_s()` (#351/#369/#457 machinery, which existed solely to
accomodate the embedded full suite) MUST NOT exist in the module.
Their tests (`test_test_suite_green_timeout_fits_full_suite`,
`tests/test_acceptance_timeout_budget.py`) SHALL be removed with them. Replacement
budgets are flat constants: `SMOKE_SUITE_TIMEOUT` (smoke path) and
`FULL_SUITE_TIMEOUT` (`--full` path) — no load scaling, no env override.

#### Scenario: retirement is mechanically checkable
- **WHEN** the acceptance module source is inspected
- **THEN** the string `TEST_SUITE_TIMEOUT` appears nowhere and none of the four retired
  symbols resolve on the module

### Requirement: the five-check acceptance enumeration SHALL be preserved

`CHECKS` SHALL remain exactly five checks in this order:
`_check_oracle` (oracle_10_10), `_check_cli_surface` (cli_surface_8),
`_check_priority_voi` (priority_voi_formula), `_check_digest` (digest_builds),
`_check_test_suite` (test_suite_green). Their result shape
(`{name, passed, detail}`) and `run_acceptance()` aggregation are unchanged.

#### Scenario: enumeration contract
- **WHEN** `[fn.__name__ for fn in acceptance_check.CHECKS]` is evaluated
- **THEN** it equals
  `["_check_oracle", "_check_cli_surface", "_check_priority_voi", "_check_digest", "_check_test_suite"]`
