## 1. Setup

- [x] 1.1 Branch `fired-predicate-resume` off `dev` b401d89 (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline: scripts/ 192 passed; tests/ 231 passed + 6 pre-existing failures (recorded)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: F4 goal-abandonment 0.00 -> 1.00; resume from fired predicates, never narrative)
- [x] 2.2 design.md (D1-D5 + R1-R4 rejected)
- [x] 2.3 spec.md (REQ 1: fired-predicate reads + never-narrative; REQ 2: cap + priority truncation; REQ 3: robustness; REQ 4: kick wiring)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate fired-predicate-resume` PASS

## 3. RED tests (write first, must fail) — tests/test_resume_prompt.py

- [x] 3.1 `test_prompt_contains_ledger_last_open_ids`: ledger last snapshot open_ids -> both ids in prompt (fired predicate)
- [x] 3.2 `test_prompt_excludes_progress_narrative`: progress.txt "我正在分析 C-007" -> sentence absent
- [x] 3.3 `test_prompt_converged_directive_when_no_open_claims`: open_ids=[] -> "CONVERGED, verify report", non-empty
- [x] 3.4 `test_prompt_lists_all_blockers`: blockers [B-01, B-02] -> both listed
- [x] 3.5 `test_prompt_surfaces_partial_facts_and_workers`: _INDEX PARTIAL + worker-status in-progress -> F042 / C301 present
- [x] 3.6 `test_prompt_truncates_claims_by_priority`: 20 claims, max_open_claims=5 -> 5 ids, C-PRIMARY kept, marker present
- [x] 3.7 `test_prompt_obeys_char_cap`: max_chars=500 -> len <= 500, marker present
- [x] 3.8 `test_prompt_missing_ledger_still_builds`: no ledger + 1 OPEN claim -> non-empty, claim id present
- [x] 3.9 `test_prompt_skips_malformed_ledger_lines`: bad line + valid snapshot -> valid row reflected
- [x] 3.10 `test_kick_stages_resume_prompt`: tick(dry_run=True) -> .kicker-prompt.txt starts with round line
- [x] 3.11 Confirm RED: all fail against current external_kicker.py (10 ImportError + 1 assertion, 11 failed)

## 4. GREEN — build_resume_prompt

- [x] 4.1 `build_resume_prompt(ws, *, max_chars, max_open_claims)` + constants DEFAULT_MAX_PROMPT_CHARS=4000 / DEFAULT_MAX_OPEN_CLAIMS=15
- [x] 4.2 Helpers: last ledger SNAPSHOT row (+round count), register open ids (OPEN + PARTIAL_STATUSES), ledger open_ids union, partial facts scan, in-progress worker stems, blockers (ledger -> blockers/*.md fallback), facts_total fallback
- [x] 4.3 Priority truncation: lazy `priority.rank_claims` order, register-order fallback, marker
- [x] 4.4 Kick wiring: `tick()` step 4 -> `build_resume_prompt(workspace)` (minimal hunk; local heartbeat_loop_prompt import dies)
- [x] 4.5 Confirm GREEN: `python -m pytest tests/test_resume_prompt.py -q` -> 11 passed

## 5. Full suites

- [x] 5.1 `python -m pytest scripts/ -q` -> 226 passed (baseline 226; test_external_kicker kick-prompt assertion updated to #45 contract), 0 failures
- [x] 5.2 `python -m pytest tests/ -q` -> 254 passed + 1 skipped + 6 pre-existing failures unchanged (4x convergence_completeness, SKILL.md 510>500, acceptance meta-gate)
- [x] 5.3 `openspec validate fired-predicate-resume` PASS

## 6. Commit

- [ ] 6.1 Commit SDD artifacts: `sdd(fired-predicate-resume): RECOVER-layer resume prompt from fired predicates (#45)`
- [ ] 6.2 Commit RED: `test(resume-prompt): RED — fired-predicate resume prompt tests (#45)`
- [ ] 6.3 Commit GREEN: `feat(external-kicker): build_resume_prompt — kick resumes from mechanical state (#45)`

## 7. PR

- [ ] 7.1 Push `fired-predicate-resume` to origin
- [ ] 7.2 PR body file + `gh pr create --base dev --head fired-predicate-resume` (do NOT merge; orchestrator verifies)
