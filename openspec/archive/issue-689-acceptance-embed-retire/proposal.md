# Proposal: retire test_acceptance O(n^2) self-embedding (#689)

## Problem

`scripts/acceptance_check.py::_check_test_suite` runs the ENTIRE pytest suite as a
subprocess (excluding `tests/test_acceptance.py`). `tests/test_acceptance.py` calls
`run_acceptance()` twice (`test_acceptance_overall_passes`, `test_acceptance_has_five_checks`),
so every full-suite run re-runs the suite twice more — an O(n^2) cost curve: the suite
doubling doubles this file's cost quadratically.

Measured 2026-08-25 (full audit, Windows host, `reports/test-audit/full-run.log`):

- Full suite: 3,761 tests / 1,004s (test-body)
- `test_acceptance_has_five_checks`: 301.24s
- `test_acceptance_overall_passes`: 301.13s (currently buys a known failure: the
  embedded suite inherits the dev branch's 102 known-red baseline, so the check can
  only fail locally regardless of any fix)
- 602s / 1,004s = 60% of the entire suite's time comes from these 2 tests

The #351 era already papered over this once by raising `TEST_SUITE_TIMEOUT` 60s → 300s
(plus #369 load-scaling, #457 win32 getloadavg guard). Those are timeout band-aids on
an architectural flaw — issue #689 forbids repeating that pattern.

The full-suite signal itself is redundant: `devkit/quality_gates.py` Gate 2
(Regression Safety) already IS full pytest. pytest nesting pytest duplicates it and
makes every quality-gate cycle pay for it.

## Solution (issue's three options, taken as a hybrid)

1. `_check_test_suite` runs a **pinned smoke subset**: a fixed nodeid manifest
   (`scripts/acceptance_smoke.txt`, 68 nodeids over 7 core files — priority /
   digest / convergence / verify-record-monitor / event-concurrency / evals schema;
   measured ~3s, all green on dev, zero overlap with the 102-failure baseline and
   with in-flight PR #681-684 file sets).
2. Full-suite enforcement lives ONLY in Gate 2 — pytest no longer nests pytest.
   `quality_gates.py` is unchanged (it already owns the job).
3. The five acceptance checks keep their semantics; `acceptance_check.py --full`
   still allows an explicit full-suite run for operators.

## What retires (issue acceptance item 3)

- `TEST_SUITE_TIMEOUT` constant — and with it the whole "fit-the-full-suite-duration"
  budget machinery that exists solely to accommodate the embed:
  `TEST_SUITE_TIMEOUT_CEILING`, `TEST_SUITE_TIMEOUT_ENV` (`KUNGLAO_TEST_SUITE_TIMEOUT`),
  `_test_suite_timeout_s()` (#369 load scaling).
- `tests/test_acceptance.py::test_test_suite_green_timeout_fits_full_suite` (the
  "#351 timeout must fit the embed" test).
- `tests/test_acceptance_timeout_budget.py` (the #369 budget-machinery test file —
  imports the retired symbols; keeping it would leave broken imports).

## Out of scope

- Gate 2 / quality_gates.py changes (it already runs full pytest; no change needed).
- The 102 known-red baseline items (tracked by PR #681-684 and #686/#687).
- Nightly-CI acceptance marker split (issue option 2) — the smoke subset already
  restores acceptance to seconds; a deselect marker adds nothing on top.

## Acceptance (issue #689)

- [ ] No single test in `pytest tests/` exceeds 60s
- [ ] Five-check acceptance semantics preserved (`CHECKS` enumeration unchanged;
      explicit `--full` still runs the full suite)
- [ ] `TEST_SUITE_TIMEOUT` constant and its fit-the-full-suite tests retired
- [ ] Full suite measured duration drops 17min → ~7min (posted to the issue after merge)

## Related

- #351 (timeout raise — the pattern this change refuses to repeat), #369 (load-scaled
  budget), #457 (win32 getloadavg guard) — all retire together with the embed.
- Gate 2: `devkit/quality_gates.py:_gate2_regression_safety`.
