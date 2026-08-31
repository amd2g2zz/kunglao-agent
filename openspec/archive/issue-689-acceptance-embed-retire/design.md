# Design — acceptance smoke subset (#689)

## D1. What `_check_test_suite` runs after the change

Default path (smoke): `pytest -q --tb=no -p no:cacheprovider --ignore=tests/test_acceptance.py
<68 pinned nodeids>` with a flat 120s budget. Measured: ~3s (1.4s + 1.2s in two probes,
68 tests, 7 files). The `--ignore=tests/test_acceptance.py` flag is kept even under the
smoke path: if someone ever pinned an acceptance nodeid into the manifest, `run_acceptance`
would otherwise recurse into itself. As a guard it is cheap and load-bearing.

`--full` path (operator-explicit only): the same command without nodeids — the whole
suite minus `tests/test_acceptance.py`, flat 1800s budget. Not load-scaled, no env
override: the budget machinery's reason to exist (the always-on embed) is gone.

## D2. Manifest: `scripts/acceptance_smoke.txt`

Lives module-adjacent (same directory as `scripts/acceptance_check.py`, which reads it).
The plan card allowed `devkit/acceptance_smoke.txt` or module-same-directory; module-
adjacent wins on cohesion — the reader, the manifest, and `scripts/README.md`'s entry for
`acceptance_check.py` all live in one place.

Format: one nodeid per line, `#` comments and blank lines ignored. An empty manifest is a
configuration error and fails the check loudly (`error: ...`) rather than silently passing.

Selection criteria for the 68 pinned nodeids (whole files, all of their tests):

| File | Covers | Green check |
|---|---|---|
| tests/test_priority_ratio.py | decision core (VoI/leverage/discriminator) | yes, dev |
| tests/test_digest.py | digest/report core | yes, dev |
| tests/test_convergence_rules_file.py | convergence contract file | yes, dev |
| tests/test_convergence_completeness.py | convergence completeness | yes, dev |
| tests/test_verify_record_monitor.py | 3 CLIs (verify/record/monitor) | yes, dev |
| tests/test_record_event_concurrent.py | event recording concurrency | yes, dev |
| tests/test_evals_schema.py | eval schema + coverage scenarios | yes, dev |

Excluded on purpose: `tests/test_digest_sec_g_528.py` (1 known-red on the dev baseline;
also touched by in-flight PR #681) and every file in the 102-failure baseline ledger.
Verified zero overlap with the file sets of in-flight PRs #681-#684, so merging them
cannot turn the smoke red.

Smoke ≠ regression enforcement. The smoke subset asserts "the core machinery is alive",
not "the suite is green". Full-suite green is Gate 2's job and stays Gate 2's job.

## D3. Timeout model: flat constants, machinery retired

| Before | After |
|---|---|
| `TEST_SUITE_TIMEOUT = 300` (floor) | deleted |
| `TEST_SUITE_TIMEOUT_CEILING = 1200` (#369 cap) | deleted |
| `TEST_SUITE_TIMEOUT_ENV` (#369 override) | deleted |
| `_test_suite_timeout_s()` (load scaling) | deleted |
| — | `SMOKE_SUITE_TIMEOUT = 120` (flat; subset ≈ 3s → 40x headroom) |
| — | `FULL_SUITE_TIMEOUT = 1800` (flat; `--full` only) |

Why flat is safe now and was not before: the budget-scaling existed because an
always-on 300s+ subprocess sat inside two tests of the suite it measured. The smoke
path is ~3s of pure-unit tests with no subprocess-heavy or env-dependent cases; a
constant with 40x headroom cannot flake on load. #351's lesson is honored by removing
the embed, not by another timeout number.

## D4. API surface changes

- `_check_test_suite(full: bool = False) -> dict` — same result shape
  (`{"name": "test_suite_green", "passed": bool, "detail": str}`); `detail` gains a
  `[smoke:N]` / `[full]` prefix so reports say which mode ran.
- `run_acceptance(full_suite: bool = False) -> dict` — same aggregation; only
  `_check_test_suite` receives the flag (other four checks unchanged).
- `main()` gains `--full`; `--write` unchanged.
- `CHECKS` enumeration (the five checks) is unchanged — that is a contract,
  tested by both the legacy `test_acceptance_has_five_checks` and the new #689 tests.

## D5. Test retirement vs test addition

Deleted:
- `tests/test_acceptance.py::test_test_suite_green_timeout_fits_full_suite` — pins the
  retired constant's semantics ("timeout must fit the embed").
- `tests/test_acceptance_timeout_budget.py` (9 tests) — pins the retired #369 load-scaling
  budget; imports deleted symbols.

Kept unchanged:
- `test_acceptance_overall_passes` — now genuinely meaningful: it passes iff the smoke
  subset + four static checks are green (previously it burned 301s to rediscover the
  dev baseline's 102 failures).
- `test_acceptance_has_five_checks` — same enumeration contract, now seconds.
- `test_test_suite_green_keeps_quiet_no_cache_pytest_flags` — the new implementation
  keeps `-q`, `--tb=no`, `-p no:cacheprovider`, `--ignore=tests/test_acceptance.py`.

Added (`tests/test_acceptance_689.py`): see tasks.md §3 — timed smoke contract, symbol
retirement contract, enumeration contract.

## D6. Risks

| Risk | Mitigation |
|---|---|
| A pinned smoke test goes red (future regression) | Intended signal: acceptance is supposed to fail when core machinery breaks; the operator sees `[smoke:68]` in the detail line |
| Manifest drifts out of sync with renamed tests | Pinned exact nodeids fail collection loudly (`no tests ran` → nonzero rc) rather than silently shrinking; collection error is visible in `detail` |
| Someone re-adds full-suite embed | RED test ① (`_check_test_suite` e2e < 60s) fails the moment the embed returns |
