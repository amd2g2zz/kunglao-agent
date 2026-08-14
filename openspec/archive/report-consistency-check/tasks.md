# Tasks — cross-chapter report-INTERNAL consistency checker (#57)

## 1. Setup

- [x] 1.1 Worktree wt57 on branch `report-consistency-check` at dev baseline `fd53d93` (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline measured: scripts/ 226 passed; tests/ 350 passed + 1 skipped + 6 pre-existing failures (test_acceptance meta-gate, test_skill_lte_500_lines, 4x test_convergence_completeness)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: a2b5e25c problem 3; layering vs #50 / numeric-fidelity; 3 fixture groups + amplification)
- [x] 2.2 design.md (D1-D8 + R1-R4; D1 = layering table; D3 = polarity engine; D5 = recall/precision stance; D7 = CC2 warning vs CC1/CC3 hard)
- [x] 2.3 spec.md (REQ: check() 3 checks / polarity engine / exclusive-pair / CONFLICT marker / CC2 warning separate / CLI exit 0/1/2 / cross-ref #50 + numeric-fidelity)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate report-consistency-check` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_regression_fixture_flags_all_3_groups`: regression fixture (3 contradiction groups, public issue content) → CC1 for HandleCommand + CC3 for named-pipe/shm + CC3/CC1 for registry (Acceptance 1)
- [x] 3.2 `test_regression_amplification_detected`: config-storage NEG + persistence-mechanism NEG across chapters → CC2 in `amplifications` (Acceptance 2)
- [x] 3.3 `test_clean_report_zero_inconsistencies`: clean consistent report → 0 inconsistencies, 0 amplifications (precision guard / Acceptance)
- [x] 3.4 `test_conflict_marker_acknowledges_contradiction`: CONFLICT marker on a polarity-flipped chapter → `acknowledged=true`, not counted in inconsistency_count
- [x] 3.5 `test_exclusive_mechanism_negated_not_flagged`: "shared memory, NOT named pipe" → no CC3 exclusive-mechanism flag
- [x] 3.6 `test_module_docstring_cross_references_50_and_numeric_fidelity`: docstring names #50 and numeric-fidelity (Acceptance 3)
- [x] 3.7 `test_cli_clean_exits_0` / `test_cli_inconsistent_exits_1` / `test_cli_missing_file_exits_2`: CLI exit codes + JSON well-formed
- [x] 3.8 Confirm RED: `python -m pytest tests/test_report_consistency_check.py -q` → ModuleNotFoundError (module not yet implemented)

## 4. GREEN — scripts/report_consistency_check.py

- [x] 4.1 `check(report_text)`: chapter segmentation (`## N.N` / `### N.N.N` headers, fenced code blocks tracked separately), polarity engine (±12-char negator window), 3 checks (CC1 symbol polarity / CC2 amplification / CC3 topic polarity + exclusive-mechanism), CONFLICT-marker acknowledgment
- [x] 4.2 table-driven constants (SYMBOL tokens, EXCLUSIVE_MECHANISM_PAIRS, CALIBER keywords, negator patterns) — extensible
- [x] 4.3 `main()` CLI: argparse `<report-file>`, JSON report, exit 0/1/2
- [x] 4.4 module docstring cross-references #50 and numeric-fidelity as complementary, non-overlapping
- [x] 4.5 Confirm GREEN: `python -m pytest tests/test_report_consistency_check.py -q` → all pass

## 5. Module docstring carries the call contract (no separate references doc)

- [x] 5.1 Module docstring of `scripts/report_consistency_check.py` carries: #50 + numeric-fidelity cross-reference, the 3-check table, the CONFLICT-marker escape hatch, and the 3-step hr-report pipeline call contract (BLOCK CC1/CC3, WARN CC2). The separate `references/report-checks.md` was DROPPED (the harness blocks report-named .md writes; the substance lives in the docstring, avoiding edit conflicts with failure-modes-* owned by other changes).

## 6. Validation

- [x] 6.1 `python -m pytest tests/test_report_consistency_check.py -q` → 14 passed
- [x] 6.2 `python -m pytest scripts/ -q` → 226 passed, 0 failures (no regression)
- [x] 6.3 `python -m pytest tests/ -q` → 364 passed (350 baseline + 14 new) + 1 skipped + the SAME 6 pre-existing failures unchanged
- [x] 6.4 `openspec validate report-consistency-check` PASS (final)

## 7. Commit + PR

- [x] 7.1 Commit SDD artifacts (db974e0)
- [x] 7.2 Commit RED tests (12460bc)
- [x] 7.3 Commit GREEN impl + SDD delta (docstring carries the call contract; no separate references doc)
- [ ] 7.4 Push branch `report-consistency-check`, `gh pr create --base dev`
- [ ] 7.5 Do NOT merge; orchestrator verifies independently first (PR left OPEN)
