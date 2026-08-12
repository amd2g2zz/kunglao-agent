# Tasks — env-negative-rule (#56)

## 1. Setup

- [x] 1.1 Worktree `wt56` on branch `env-negative-rule` off `dev` baseline `fd53d93` (clean)
- [x] 1.2 Baseline test counts confirmed: scripts/ 226 passed; tests/ baseline recorded (350 passed + 1 skipped + 6 pre-existing failures per task brief)

## 2. Gap assessment (READ-ONLY)

- [x] 2.1 Read `scripts/blind_gate.py` fully; map `is_inferential_claim`, `_has_zero_hits`, `_has_env_fault`, env-fault diagnostic (line 345-351)
- [x] 2.2 Read `scripts/kunglao_record.py` wire point (`claim_migrator` PROVEN branch) + confirm `hooks/worker_budget.py` is the second wire point
- [x] 2.3 Probe four F040-shape synthetic claims against shipped `check_inference_blind_scope` (probe in `$CLAUDE_JOB_DIR/tmp/probe_gap.py`)
- [x] 2.4 Result: #48 catches routing+`0 hits` and existence+`0 hits`; MISSES existence+`no call captured` and `absent`+`no calls observed` → residual = code generalization (G1 basis vocab, G2 negative-existence flagging) + doc + regression test

## 3. OpenSpec artifacts (SDD)

- [x] 3.1 proposal.md (why: F040 a2b5e25c; gap-assessment summary; residual statement; non-goals)
- [x] 3.2 spec.md (ADDED Requirements: env-negative basis+conclusion rule; negative-existence inferential; same-gate enforcement; doc placement)
- [x] 3.3 design.md (Gap assessment vs #48 with probe evidence; D1-D5; file layout; out of scope)
- [x] 3.4 tasks.md
- [x] 3.5 `openspec validate env-negative-rule` PASS

## 4. RED tests (write first, must fail)

- [x] 4.1 F040 regression (routing + `0 hits` + env-fault) → STAMP — asserts #48's existing behavior (acceptance #2); GREEN already, documents the regression contract
- [x] 4.2 existence + "no call captured" + env-fault → STAMP (the G1 residual; currently passes — RED)
- [x] 4.3 "absent" + "no calls observed" + env-fault → STAMP (G1+G2 residual; currently passes — RED)
- [x] 4.4 existence reason names environmental problem (G1 diagnostic; RED on reason)
- [x] 4.5 routing "no call captured" reason names environmental (G1 diagnostic; RED on reason)
- [x] 4.6 complementarity: same gate function (no `check_env_negative_gate`); positive existence + byte-anchor claims not over-flagged
- [x] 4.7 env-negative WITH static xref → PROVEN
- [x] 4.8 run → 4 RED (residual) + 5 GREEN (regression/complementarity) confirmed

## 5. GREEN — generalize blind_gate.py

- [x] 5.1 `_ENV_NEGATIVE_BASIS_PATTERNS` (broader vocab) + `_has_env_negative_basis`; `_has_zero_hits` kept as backward-compat alias
- [x] 5.2 `_NEGATIVE_EXISTENCE_PATTERNS` folded into `is_inferential_claim` (NEGATIVE conclusions only; positive existence not flagged)
- [x] 5.3 env-fault diagnostic uses `_has_env_negative_basis`; reason message generalized to "routing or existence"
- [x] 5.4 all 9 new tests GREEN; `tests/test_inference_blind_scope.py` (#48 suite, 17) + `tests/test_blind_gate.py` (19) still GREEN

## 6. Docs

- [x] 6.1 `references/failure-modes-monitoring.md`: env-negative rule subsection under F8 family (trigger vocab, forbidden conclusions, enforcement gate, F040 incident, cross-refs to #48 + failure_analysis_gate 3-question mechanism)
- [x] 6.2 `references/failure-modes.md`: one-line index pointer

## 7. Full suites + validate

- [x] 7.1 `python -m pytest scripts/ -q` — 226 passed (baseline preserved)
- [x] 7.2 `python -m pytest tests/ -q` — 359 passed + 1 skipped + 6 pre-existing failures (350 baseline + 9 new green)
- [x] 7.3 `openspec validate env-negative-rule` PASS (final)

## 8. PR (do NOT merge — orchestrator verifies)

- [ ] 8.1 Commit SDD alone, then impl+tests+docs; push branch `env-negative-rule`
- [ ] 8.2 `gh pr create --base dev --head env-negative-rule` (body: gap-assessment result + residual + RED/GREEN counts)
