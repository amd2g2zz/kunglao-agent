## 1. Setup

- [x] 1.1 Branch `failure-lessons` off `dev` 532a336 (one issue / one PR / one branch / one worktree wt41)
- [x] 1.2 Baseline: scripts/ 179 passed; tests/ 231 passed + 6 pre-existing failures (SKILL.md 510>500, 4× test_convergence_completeness, test_acceptance meta-gate — recorded, not to fix)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: failure analysis leaves no trace; no outcome at claim closure; cross-sample reuse impossible)
- [x] 2.2 spec.md (REQ: record outcome fields / lessons aggregation closed-loop / BLOCKED 3 similar lessons / parameterized library)
- [x] 2.3 design.md (D1-D5 + R1-R4 rejected)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate failure-lessons` PASS

## 3. RED tests (write first, must fail) — scripts/test_failure_lessons.py

- [x] 3.1 `test_record_outcome_writes_fields_and_preserves_prior`: --outcome/--what-happened lands in analyses/failure-*.yaml; prior fields preserved
- [x] 3.2 `test_record_outcome_validation`: bad outcome value / outcome-without-what-happened / what-happened-without-outcome rejected
- [x] 3.3 `test_lessons_proven_writes_lesson_file`: closed PROVEN → lesson-*.md in tmp library by failure signature
- [x] 3.4 `test_lessons_negative_needs_redteam_confirm`: NEGATIVE + ledger red-team CONFIRMED → in library; without → /reflect queue (negative-unverified)
- [x] 3.5 `test_lessons_refuted_and_no_outcome_go_to_queue`: REFUTED / no-outcome → no lesson, queue reasons refuted / no-outcome, idempotent
- [x] 3.6 `test_lessons_group_and_dedup`: same-signature claims → one lesson file with both sources; re-run adds nothing
- [x] 3.7 `test_blocked_includes_similar_lessons`: BLOCKED dict has top-3 similar_lessons; empty library → []
- [x] 3.8 `test_search_keywords`: --search matches by keyword overlap, empty query → empty result, exit 0
- [x] 3.9 `test_failure_blocked_parsing_backward_compatible`: scan_workspace BLOCKED set identical with/without outcome fields
- [x] 3.10 Confirm RED (functions/CLI flags don't exist yet → import/usage errors)

## 4. GREEN — failure_analysis_gate.py

- [x] 4.1 `OUTCOME_VALUES` tuple constant (no `TERMINAL = {` — test_status_defs grep guard)
- [x] 4.2 record_analysis: --outcome/--what-happened validation + field-level merge preserving prior entry
- [x] 4.3 `_signature` / `_claim_topic` / `_slug` helpers (method + assumption + claim topic → sha256[:10])
- [x] 4.4 `aggregate_lessons(workspace, library, reflect_queue)` — closed-loop gate via outcome_capture.read_outcome_rows; idempotent write; queue append (JSON array, dedup claim_id|reason)
- [x] 4.5 `_score_lessons(text, library)` + `search_lessons` — keyword overlap, top-3
- [x] 4.6 check_claim BLOCKED gains `similar_lessons`; _print_blocked prints them; scan_workspace keeps `(workspace, library=None)` signature
- [x] 4.7 CLI: `--lessons` / `--search` / `--library` / `--reflect-queue` flags

## 5. Full suites

- [x] 5.1 `pytest scripts/test_failure_lessons.py -q` → all pass
- [x] 5.2 `pytest scripts/ -q` → 179+N passed, 0 failures
- [x] 5.3 `pytest tests/ -q` → 231 passed + 6 pre-existing failures unchanged
- [x] 5.4 `pytest scripts/test_v1_8_enforcement_gates.py -q` → 31/31
- [x] 5.5 `openspec validate failure-lessons` PASS

## 6. PR

- [x] 6.1 Commit SDD / RED / GREEN (small atomic commits)
- [x] 6.2 Push `failure-lessons`, open PR → `dev` (do NOT merge; orchestrator verifies)
