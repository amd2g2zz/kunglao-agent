## 1. Setup

- [x] 1.1 Branch `active-workers-single-source` off `dev` f0d44b4 (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline: scripts/ 144 passed; tests/ 222 passed + 6 pre-existing failures (recorded)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: double-truth-source — gate reads state cache, convergence reads status files)
- [x] 2.2 spec.md (REQ: gate counts status files not cache; scan byte-equivalent to convergence_check)
- [x] 2.3 design.md (D1-D4 + R1-R4 rejected)
- [x] 2.4 tasks.md
- [ ] 2.5 `openspec validate active-workers-single-source` PASS

## 3. RED tests (write first, must fail)

- [ ] 3.1 `test_check_workers_lt_3_from_status_files`: 3 in-progress status files -> `not ok and '3' in msg`
- [ ] 3.2 `test_check_workers_lt_3_empty_state_cache`: 1 in-progress + empty state segment -> ok
- [ ] 3.3 `test_check_workers_lt_3_ignores_done`: 1 in-progress + 1 done -> ok
- [ ] 3.4 Migrate `test_check_workers_lt_3_ok` / `_reject` to dict signature (Path -> `{'workspace': ...}` + status files)
- [ ] 3.5 Confirm RED on old gate (still reads state cache -> new status-file tests fail)

## 4. GREEN — lib_kunglao.scan_active_workers

- [ ] 4.1 Add `scan_active_workers(workspace) -> (active, stuck)` mirroring convergence_check.py:74-120 byte-for-byte
- [ ] 4.2 Imports: `re`, `datetime` at module top; `STUCK_MINUTES = 20`

## 5. GREEN — worker_budget.check_workers_lt_3

- [ ] 5.1 Signature `(state_path: Path)` -> `(paths: dict)`; read source = `scan_active_workers(paths['workspace'])`
- [ ] 5.2 FAIL_OPEN: missing workspace / exception -> `(True, '')`
- [ ] 5.3 `pre_check` call site: `check_workers_lt_3(paths['state'])` -> `check_workers_lt_3(paths)`

## 6. Docs + validation

- [ ] 6.1 `pytest scripts/test_worker_budget.py -v` -> all pass (30 migrated + 3 new)
- [ ] 6.2 `pytest scripts/ -q` -> 144+ passed (no regression)
- [ ] 6.3 `pytest tests/ -q` -> 222 passed + 6 pre-existing failures unchanged
- [ ] 6.4 `openspec validate active-workers-single-source` PASS

## 7. Commit

- [ ] 7.1 Commit SDD artifacts: `sdd(active-workers-single-source): ... (#37)`
- [ ] 7.2 Commit impl + tests: `feat(worker-budget): active_workers single-source — gate reads status files (#37)`
