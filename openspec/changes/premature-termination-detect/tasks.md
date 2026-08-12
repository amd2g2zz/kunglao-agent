# Tasks — premature-termination detection (#54)

## 1. Setup

- [x] 1.1 Worktree wt54 on branch `premature-termination-detect` at dev baseline `4868418` (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline measured: scripts/ 226 passed; tests/ 292 passed + 1 skipped + 6 pre-existing failures (test_acceptance meta-gate, test_skill_lte_500_lines, 4x test_convergence_completeness)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: 3rd recurrence; layering vs #43/#44; 4 fingerprints from instance evidence)
- [x] 2.2 design.md (D1-D6 + R1-R4; D1 = layering table; D4 = recall/precision stance)
- [x] 2.3 spec.md (REQ: detect() 4 fingerprints / task_text grounding + indeterminate-F1 / F3 qualifier + F4 zero-open exclusion / CLI exit 0/1/2 / cross-ref #43+#44)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate premature-termination-detect` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_regression_fixture_fires_all_4`: issue 现象段 verbatim → all 4 fingerprints fire with evidence spans (Acceptance a)
- [x] 3.2 `test_clean_completion_fires_zero`: genuine completion (task quoted, 0 open, no cost, no invented tier) → 0 fire (false-positive guard)
- [x] 3.3 `test_F1_self_anchoring_isolation`: self-summary done-phrase + task_text whose anchor is absent → only F1
- [x] 3.4 `test_F2_self_invented_tiering_isolation`: tier keyword + open-item ref, no completion → only F2
- [x] 3.5 `test_F3_cost_semantic_drift_isolation`: cost figure + informational qualifier, no completion → only F3
- [x] 3.6 `test_F4_false_completion_isolation`: completion declaration + open-items-remaining, no tier keyword → only F4
- [x] 3.7 `test_module_docstring_cross_references_43_44`: module docstring names #43 and #44 (Acceptance c)
- [x] 3.8 `test_F1_indeterminate_without_task_text`: self-summary phrase present, no task_text, no marker → F1 not fired, note = indeterminate
- [x] 3.9 `test_cli_exit_codes_and_json`: CLI exit 0 on clean / 1 on fired / 2 on missing file; JSON report well-formed
- [x] 3.10 Confirm RED: `python -m pytest tests/test_premature_termination_detect.py -q` → ModuleNotFoundError (module not yet implemented)

## 4. GREEN — scripts/premature_termination_detect.py

- [x] 4.1 `detect(transcript, task_text=None)`: 4 fingerprint detectors (F1-F4), table-driven regex constants, agent-region segmentation, evidence spans per fingerprint
- [x] 4.2 task_text recovery (explicit arg / extraction marker / indeterminate-F1 honest degradation)
- [x] 4.3 `main()` CLI: argparse `<transcript-file>` + `--task-text` / `--task-text-file`, JSON report, exit 0/1/2
- [x] 4.4 module docstring cross-references #43 and #44 as complementary, non-duplicate
- [x] 4.5 Confirm GREEN: `python -m pytest tests/test_premature_termination_detect.py -q` → 17 passed

## 5. Failure-modes docs

- [x] 5.1 `references/failure-modes-lifecycle.md`: add "Termination failures" section with the 4-fingerprint table (PT1-PT4), instance evidence, cross-ref #43/#44
- [x] 5.2 `references/failure-modes.md`: +1 index line pointing to the new lifecycle section

## 6. Validation

- [x] 6.1 `python -m pytest tests/test_premature_termination_detect.py -q` → 17 passed
- [x] 6.2 `python -m pytest scripts/ -q` → 226 passed, 0 failures (no regression; detector is tests/-only)
- [x] 6.3 `python -m pytest tests/ -q` → 309 passed + 1 skipped + 6 pre-existing failures unchanged (292 baseline + 17 new; the SAME 6: test_acceptance, test_skill_lte_500_lines, 4x test_convergence_completeness)
- [x] 6.4 `openspec validate premature-termination-detect` PASS (final)

## 7. Commit + PR

- [x] 7.1 Commit SDD artifacts (`f7811f4`)
- [x] 7.2 Commit RED tests (`024e712`)
- [x] 7.3 Commit GREEN impl + docs (`88015bf`)
- [x] 7.4 Push branch `premature-termination-detect`, `gh pr create --base dev` → PR #72 (https://github.com/amd2g2zz/kunglao-agent/pull/72)
- [x] 7.5 Do NOT merge; orchestrator verifies independently first (PR left OPEN)
