# Tasks — acceptance embed retire (#689)

## 1. Setup

- [x] 1.1 Worktree `D:/codebase/kunglao-issue-689-acceptance-embed-retire` branch `issue-689-acceptance-embed-retire` off origin/dev (`619ebd3`)
- [x] 1.2 Baseline read: 102 known-red nodeids (`reports/test-audit/full-run.log`); smoke candidates verified green + zero overlap with PR #681-684 file sets

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (Why: 602s/1004s = 60% evidence)
- [x] 2.2 design.md (D1-D6)
- [x] 2.3 specs/acceptance-smoke/spec.md
- [x] 2.4 tasks.md

## 3. RED tests (`tests/test_acceptance_689.py`)

- [x] 3.1 RED1: `_check_test_suite()` end-to-end < 60s (timed) — kills the embed
- [x] 3.2 RED2: `TEST_SUITE_TIMEOUT` (+ CEILING/ENV/`_test_suite_timeout_s`) absent from module source and namespace
- [x] 3.3 RED3: five-check `CHECKS` enumeration unchanged (pure, no subprocess)

RED evidence (base 619ebd3, module unchanged by #685): `2 failed, 1 passed in 308.00s` —
RED1 failed on the embed itself timing out after 300s; RED2 failed on the constant being present.

## 4. Implementation (GREEN)

- [x] 4.1 `scripts/acceptance_smoke.txt` (NEW): 68 pinned nodeids, 7 core files
- [x] 4.2 `scripts/acceptance_check.py`: `_check_test_suite(full=...)` smoke-by-default; `run_acceptance(full_suite=...)`; `main()` `--full`; retire `TEST_SUITE_TIMEOUT`/`CEILING`/`ENV`/`_test_suite_timeout_s`; add flat `SMOKE_SUITE_TIMEOUT=120` / `FULL_SUITE_TIMEOUT=1800`
- [x] 4.3 delete `tests/test_acceptance.py::test_test_suite_green_timeout_fits_full_suite`
- [x] 4.4 delete `tests/test_acceptance_timeout_budget.py` (retired-machinery tests)

GREEN evidence: `tests/test_acceptance_689.py tests/test_acceptance.py` → 6 passed in
11.31s (was 2x301s); CLI: `overall: PASS ... [smoke:68] 68 passed in 1.85s`; `--full`
wiring verified via stubbed subprocess (timeout 1800, no nodeids, `[full]` detail).

## 5. Validation

- [x] 5.1 `tests/test_acceptance_689.py` GREEN; `tests/test_acceptance.py` no longer burns ~301s/test (6.4s/test; slowest test overall 14.1s < 60s bound)
- [x] 5.2 `uv run python devkit/quality_gates.py` — Gates 1/3/4/5/6/7 PASS; Gate 2 = 14 failed / 3,722 passed in 602.87s, all 14 accounted for: 9 in the baseline ledger + 5 proven identical on clean b2b3661 baseline worktree (gate_power_473 / init_deploy_env / v012_milestone_audit×2 / workspace_export_540::sha256 — env-dependent, pre-existing on dev). Zero new out-of-ledger failures. (2 transient ext_index failures from this change's docstring edit were fixed by regenerating tools/_INDEX.ext.yaml and re-verified.)
- [x] 5.3 full-suite duration measured: 1,004.39s (2026-08-25 audit, before) → 602.87s (Gate 2 run, after, under parallel-slot load). Like-for-like mechanism: the two 301s acceptance tests now take 6.4s each.

## 6. PR

- [ ] 6.1 3-commit sequence: openspec / RED / GREEN — commit 1 done (5f41da0); RED+GREEN are staged in the worktree but BLOCKED on the orchestrator-held review-gate mint (`.git/hooks/pre-commit` requires independent reviewer evidence; the maker has no reviewer-dispatch channel — evidence staged, exact commands in the worker report)
- [ ] 6.2 push + PR to dev, body with RED+GREEN outputs, duration before/after, `Closes #689`
