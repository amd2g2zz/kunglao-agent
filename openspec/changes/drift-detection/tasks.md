# Tasks — drift detection (#43)

## 1. Setup

- [x] 1.1 Branch `drift-detection` off `dev` b401d89 (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline measured: scripts/ 226 passed; tests/ 243 passed + 1 skipped + 6 pre-existing failures (SKILL.md 510>500, 4x test_convergence_completeness, test_acceptance meta-gate)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: alive-but-stuck F2/F3 regime — heartbeat fresh + ledger writing + zero progress, invisible to time-based detection)
- [x] 2.2 design.md (D1-D4 + R1-R3 rejected)
- [x] 2.3 spec.md (REQ: signature_rotation / workers_progressing / drift_detected / should_kick drift branch / tunable constants)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate drift-detection` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_drift_detected_frozen_3_rows_no_worker`: 3 identical ledger rows + no status files -> rotation 3, `drift_detected` True
- [x] 3.2 `test_drift_detected_exempts_fresh_worker`: 3 identical rows + in-progress worker mtime 5min -> `workers_progressing` True -> `drift_detected` False
- [x] 3.3 `test_drift_detected_below_window`: 2 identical rows -> rotation 2 < 3 -> False
- [x] 3.4 `test_should_kick_not_persistent_below_escalate`: rotation 3 but older rows 4-6 differ -> escalate False
- [x] 3.5 `test_should_kick_escalates_at_6_frozen_rows`: 6 identical rows -> should_kick True
- [x] 3.6 ts/open_count exclusion, corrupt-row robustness, missing ledger, workers_progressing edge cases (stale/done/worktree/none), fresh-worker blocks escalation, constants wiring
- [x] 3.7 Confirm RED: `python -m pytest tests/test_drift_detection.py -q` fails (ImportError / missing module)

## 4. GREEN — scripts/lib_kunglao.py

- [x] 4.1 New module: constants ROTATION_WINDOW=3 / DRIFT_ESCALATE_ROWS=6 / WORKER_PROGRESS_MINUTES=20
- [x] 4.2 `signature_rotation(ws, window=None)`: bounded tail read, signature tuple excl. ts, corrupt rows skipped, never raises
- [x] 4.3 `workers_progressing(ws, now=None, fresh_minutes=...)`: scan mirrors convergence_check._scan_active_workers (main runs + .wt-* worktrees), last-status=in-progress, mtime < fresh_minutes
- [x] 4.4 `drift_detected(ws)`: rotation >= ROTATION_WINDOW AND NOT workers_progressing

## 5. GREEN — scripts/external_kicker.py should_kick drift branch

- [x] 5.1 `should_kick(workspace)`: drift_detected AND rotation >= DRIFT_ESCALATE_ROWS; function-level lib_kunglao import; the file's ONLY change

## 6. Validation

- [x] 6.1 `python -m pytest tests/test_drift_detection.py -q` -> all pass
- [x] 6.2 `python -m pytest scripts/ -q` -> 226+N passed, 0 failures (no regression)
- [x] 6.3 `python -m pytest tests/ -q` -> 243 passed + 1 skipped + 6 pre-existing failures unchanged
- [x] 6.4 `openspec validate drift-detection` PASS (final)

## 7. Commit + PR

- [x] 7.1 Commit SDD artifacts: `sdd(drift-detection): proposal/design/spec/tasks for ledger-signature drift detection (#43)`
- [x] 7.2 Commit RED tests: `test(drift-detection): RED — signature rotation / worker progression / drift escalation tests (#43)`
- [x] 7.3 Commit GREEN impl: `feat(drift-detection): alive-but-stuck detection — signature_rotation + workers_progressing + drift_detected + should_kick drift branch (#43)`
- [x] 7.4 Push branch `drift-detection`, `gh pr create --base dev` with PR body
- [x] 7.5 Do NOT merge; orchestrator verifies independently first
