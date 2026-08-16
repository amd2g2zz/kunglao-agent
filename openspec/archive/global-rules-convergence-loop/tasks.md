## 1. Setup

- [x] 1.1 Branch `global-rules-convergence-loop` off `dev` 532a336 (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline: scripts/ 179 passed; tests/ 231 passed + 6 pre-existing failures + 1 skipped (recorded)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: #1 invariant lives only in SKILL.md; rules/common is the always-on channel)
- [x] 2.2 spec.md (REQ: distilled file <150 lines; 9-point outline markers; no 80+ char verbatim blocks vs reference; SKILL.md/reference untouched)
- [x] 2.3 design.md (D1-D4 + R1-R4 rejected)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate global-rules-convergence-loop` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_rules_file_exists`: rules/kunglao-convergence-loop.md exists
- [x] 3.2 `test_rules_file_lte_150_lines`: total lines < 150
- [x] 3.3 marker tests: first-tool invariant / decision table / 5 behaviors / maker-checker / tool boundary / hard prohibitions / file map / pointers
- [x] 3.4 `test_no_long_verbatim_blocks_from_reference`: no 80+ char shared substring with references/convergence-loop.md beyond vocabulary
- [x] 3.5 Confirm RED: file missing → all 12 fail (FileNotFoundError)

## 4. GREEN — distilled rules file

- [x] 4.1 Write `rules/kunglao-convergence-loop.md` (9 sections, 70 lines, maker-checker.md style)
- [x] 4.2 Confirm all contract tests PASS (12/12; negative controls: verbatim paragraph → 200+ violations detected, vocab-only command → 0)

## 5. Full suites + validation

- [x] 5.1 `pytest scripts/ -q` -> 179 passed (no regression, unchanged from baseline)
- [x] 5.2 `pytest tests/ -q` -> 243 passed (231 + 12 new) + 6 pre-existing failures unchanged + 1 skipped
- [x] 5.3 `openspec validate global-rules-convergence-loop` PASS

## 6. Commit

- [x] 6.1 Commit SDD artifacts: `sdd(global-rules-convergence-loop): proposal/design/spec/tasks for #46`
- [x] 6.2 Commit tests + rules file: `feat(rules): distilled kunglao-convergence-loop.md always-on rules (#46)`
- [x] 6.3 Push branch + open PR to dev (PR #66 — NOT merged; orchestrator verifies first)
