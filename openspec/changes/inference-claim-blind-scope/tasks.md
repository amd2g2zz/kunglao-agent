## 1. Setup

- [x] 1.1 Create branch `inference-claim-blind-scope` off `dev` (one issue one PR one branch one worktree)
- [x] 1.2 Confirm baseline test counts before changes (scripts/ 144 passed; tests/ 6 pre-existing failures recorded)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: a2b5e25c problem 2, F040 routing inference un-covered by BLIND)
- [x] 2.2 spec.md (REQ: inferential claims need independent static sign-off; env-negative-evidence rule; claim_migrator downgrade; backstop)
- [x] 2.3 design.md (D1-D6: pattern contract, coverage markers, env-fault diagnostic, signature, wire points, schema extension)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate inference-claim-blind-scope` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 RED1: inferential claim (routing statement) + sign-off evidence orchestrator-captured → `check_inference_blind_scope` not-allowed, STAMP
- [x] 3.2 RED2: inferential claim + sign-off with independent static xref → allowed, PROVEN
- [x] 3.3 RED3: pure byte-anchor claim (no inferential patterns) → allowed regardless of sign-off shape
- [x] 3.4 RED4: 0-hits + env-fault self-report + no static xref → not-allowed, reason names environmental evidence
- [x] 3.5 a2b5e25c backtest: F040 fixture (routing inference, orchestrator-captured, stalled/never-reconnected, byte-anchor sign-off) → STAMP; backfill static xref in sign-off → passes
- [x] 3.6 edges: no signoff, self-stamp, REFUTE verdict, `corrects F-034` pattern, statement-only vs fact-text-only inference, env-fault WITHOUT 0-hits → generic coverage failure

## 4. blind_gate.py implementation

- [x] 4.1 `INFERENTIAL_PATTERNS` + `is_inferential_claim(statement, fact_text)` (first 4000 chars)
- [x] 4.2 `_has_zero_hits(text)` / `_has_env_fault(text)` (stalled/never reconnected/未触发/timeout/reconnect)
- [x] 4.3 `_signoff_evidence_text(signoff)` (evidence_path + refute_attempt + finding) + static-marker test
- [x] 4.4 `_claim_statement(register_text, claim_id)` — parse `statement:` from the claim block
- [x] 4.5 `check_inference_blind_scope(claim_id, facts_dir, register_text, worker_id=None)` — D4 order: fact → signoff → self-stamp → REFUTE → orchestrator-captured → static markers → env-fault diagnostic

## 5. Wire into claim_migrator (kunglao_record.py)

- [x] 5.1 PROVEN branch: third gate after BLIND + CONFLICT; failure → `effective_status = STAMP`, message gains `[INFERENCE GATE: ...]`
- [x] 5.2 RED1/2/4 + backtest GREEN via claim_migrator (integration)

## 6. Backstop (hooks/worker_budget.py)

- [x] 6.1 `compare_register_change_proven_gate`: inference check joins violations (reuses register_text)
- [x] 6.2 Hook-side integration test GREEN

## 7. Docs + validation

- [x] 7.1 `references/schema.md`: verifier_sign_off inference-coverage convention line
- [x] 7.2 `python -m pytest scripts/` full pass (no new failures)
- [x] 7.3 `python -m pytest tests/` — new tests GREEN, 6 pre-existing failures unchanged
- [x] 7.4 `openspec validate inference-claim-blind-scope` PASS

## 8. PR + merge + cleanup

- [ ] 8.1 Commit (SDD first, then impl+tests), push branch, open PR to `dev` (body: Closes #48)
- [ ] 8.2 Squash-merge to dev, close issue #48
- [ ] 8.3 Remove worktree + delete branch; update master-plan.md delta
