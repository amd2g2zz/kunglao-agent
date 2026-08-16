# Tasks - fix-98-maker-checker-deadlock (#98)

## 1. Setup

- [x] 1.1 Worktree wt98 on fix-98-maker-checker-deadlock (base dev 9f9c9d6)
- [x] 1.2 Baseline: 716 passed, 2 pre-existing failures (acceptance/contract), 1 skipped

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (What/Why/Scope/Acceptance)
- [x] 2.2 design.md (D1-D5: two-tier exception classification, degradation pattern, hook, self_caveat, rejected alternatives)
- [x] 2.3 specs/maker-checker-deadlock/spec.md (REQ-1..5 + 9 scenarios)
- [x] 2.4 tasks.md

## 3. RED tests (write first, must fail)

- [x] 3.1 claim_migrator: blind_gate ImportError -> BLOCKED (existing behavior, must still pass)
- [x] 3.2 claim_migrator: blind_gate runtime error (RuntimeError) -> STAMP degraded (RED confirmed: returned False/BLOCKED)
- [x] 3.3 claim_migrator: contradiction gate runtime error -> STAMP degraded
- [x] 3.4 claim_migrator: inference gate runtime error -> STAMP degraded
- [x] 3.5 blind_gate: self_caveat in fact frontmatter -> (False, STAMP, self_caveat reason)
- [x] 3.6 blind_gate: self_caveat does not bypass self-stamp guard
- [x] 3.7 Hook: import block ImportError -> block (existing behavior, must still pass)
- [x] 3.8 Hook: execution block runtime error -> violation/STAMP guidance (not "fail closed")

## 4. GREEN - scripts/blind_gate.py

- [x] 4.1 check_proven_gate: extract self_caveat from frontmatter, return (False, STAMP, self_caveat reason)
- [x] 4.2 check_inference_blind_scope: same self_caveat recognition

## 5. GREEN - scripts/kunglao_record.py

- [x] 5.1 Split each of three gate blocks: import in own try/except (BLOCKED on any exc) + execution in own try/except (degrade to STAMP on non-ImportError)
- [x] 5.2 BLIND gate block
- [x] 5.3 Contradiction gate block
- [x] 5.4 Inference gate block

## 6. GREEN - hooks/worker_budget.py

- [x] 6.1 Execution block (L460-482): split except into ImportError (fail closed) + Exception (degrade, add violation)
- [x] 6.2 Import blocks (L434-455): unchanged (FAIL_CLOSED)

## 7. Regression + validation

- [x] 7.1 tests/ full: 730 passed, 2 pre-existing failures unchanged, no new failures
- [x] 7.2 Existing test_fail_closed_gates.py updated: test_claim_migrator_blocks_proven_when_gate_raises now asserts STAMP degradation (not BLOCKED) per #98 policy change
