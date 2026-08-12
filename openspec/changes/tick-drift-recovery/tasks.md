# Tasks — tick-drift-recovery (#79)

## 1. Setup

- [x] 1.1 Branch `fix/tick-drift-recovery` off dev `105f6ff` (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline measured: scripts/ + tests/ suites green apart from the 6 pre-existing failures (SKILL.md 510>500, 4x test_convergence_completeness, test_acceptance meta-gate)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: #43 predicate never wired — fresh-heartbeat tick skips before evaluating should_kick; controlled reproduction)
- [x] 2.2 design.md (D1-D5: single drift definition / branch placement / reason-key receipt / fresh-worker race / repeated ticks; R1-R3 rejected)
- [x] 2.3 spec.md (REQ: tick evaluates should_kick on fresh heartbeat; drift receipts distinct without stale-path regression)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate tick-drift-recovery` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_tick_fresh_heartbeat_drift_kicks`: fresh heartbeat + 6 frozen rows + dry_run -> rc 0 + `reason: "drift"` receipt + prompt staged
- [x] 3.2 `test_tick_fresh_heartbeat_no_drift_skips`: fresh heartbeat + no ledger -> alive-skip, no receipt
- [x] 3.3 `test_tick_fresh_heartbeat_below_escalation_skips`: fresh heartbeat + 5 frozen rows -> alive-skip, no receipt
- [x] 3.4 `test_tick_fresh_heartbeat_progressing_worker_skips`: 6 frozen rows + fresh worker status -> no kick (fresh-worker race)
- [x] 3.5 `test_tick_drift_repeated_ticks_deterministic`: two consecutive dry-run ticks -> both rc 0 + drift receipts
- [x] 3.6 `test_tick_stale_session_receipt_unchanged`: no heartbeat -> kick receipt WITHOUT reason key (regression)
- [x] 3.7 `test_tick_lock_held_skips_before_drift`: fresh lock file -> lock-skip rc 0, no receipt, no drift evaluation
- [x] 3.8 Confirm RED: `pytest tests/test_drift_detection.py -q` fails on the new tick tests

## 4. GREEN — scripts/external_kicker.py tick()

- [x] 4.1 Fresh-heartbeat branch evaluates `should_kick(workspace)` before returning (D2)
- [x] 4.2 Drift True -> fall through to the shared recovery path (lock / hooks ensure / prompt / dry-run / receipt)
- [x] 4.3 Receipt gains `reason: "drift"` ONLY on the drift path (D3); stale path byte-identical
- [x] 4.4 Distinct log line `kicker: DRIFT-KICK — session alive but stuck ...`
- [x] 4.5 No change to lib_kunglao.py / convergence_check.py / hooks / constants (issue-owned files untouched)

## 5. Validation

- [x] 5.1 `python -m pytest tests/test_drift_detection.py -q` -> all pass
- [x] 5.2 `python -m pytest scripts/ -q` -> all pass (no regression)
- [x] 5.3 `python -m pytest tests/ -q` -> pass apart from the 6 pre-existing failures UNCHANGED
- [x] 5.4 `openspec validate tick-drift-recovery` PASS (final)

## 6. Commit + PR

- [x] 6.1 Commit SDD artifacts FIRST: `sdd(tick-drift-recovery): proposal/design/spec/tasks for tick() alive-but-stuck drift evaluation (#79)`
- [x] 6.2 Commit RED tests: `test(kicker): RED — tick() drift integration tests (#79)`
- [x] 6.3 Commit GREEN impl: `fix(kicker): tick() evaluates alive-but-stuck drift on fresh heartbeat (#79)`
- [x] 6.4 Push branch `fix/tick-drift-recovery`, `gh pr create --base dev` -> PR #85 with RED->GREEN evidence
- [x] 6.5 Do NOT merge / close / push to dev; orchestrator verifies first (maker-checker)
