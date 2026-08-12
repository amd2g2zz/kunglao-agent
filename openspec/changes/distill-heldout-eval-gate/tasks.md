# Tasks — distill-heldout-eval-gate (#82)

## 1. Setup

- [x] 1.1 Worktree wt82 on branch `feat/distill-heldout-eval-gate` at dev baseline `b399bdd` (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline measured: full suite (tests/ + scripts/) green apart from the pre-existing failures; `memory/scripts/test_memory_pipeline.py` smoke suite runs green
- [x] 1.3 Read-only ground truth: #81 spec at wt81 `openspec/changes/executable-l2-evaluation/` (receipt schema, evaluator ownership, non-evidence rule); current `memory/scripts/distill.py` stub (L23-L25, L83-L148); precedent `openspec/changes/tick-drift-recovery/`

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 `openspec new change distill-heldout-eval-gate` scaffolded (.openspec.yaml, schema spec-driven)
- [x] 2.2 proposal.md (why: stub synthesis + direct longterm write = no measurable promotion boundary; scope; capabilities; impact incl. #81 contract)
- [x] 2.3 design.md (D1-D9: candidate-first / journal-as-ledger / candidate lab + hidden fixtures / 5-condition promotion gate / registry + rollback / forged-receipt detection / duplicate-expiry-retirement / failure semantics / CLI; R1-R5 rejected)
- [x] 2.4 specs/distill-heldout-eval-gate/spec.md (REQ ×8 + scenarios covering all 5 acceptance criteria)
- [x] 2.5 tasks.md
- [x] 2.6 `openspec validate distill-heldout-eval-gate` PASS ("is valid")
- [x] 2.7 Commit openspec artifacts FIRST: `sdd(distill-heldout-eval-gate): proposal/design/spec/tasks for held-out evaluation gate + rollback (#82)`

## 3. RED tests (write first, must fail) — tests/test_distill_candidate_gate.py

- [ ] 3.1 `test_default_output_is_candidate_not_rule`: distill with ≥ threshold staging → `memory/candidates/cand-*.md` with `status: CANDIDATE`, `longterm/` untouched
- [ ] 3.2 `test_candidate_id_content_addressed_duplicate_detected`: identical staging + generator → same id, `duplicate` journal row, no second record
- [ ] 3.3 `test_promotion_without_receipt_stays_candidate`: `promote <id>` with no `evaluated` row / incomplete receipt → stays CANDIDATE, no `promoted` row, longterm unchanged
- [ ] 3.4 `test_held_out_gain_below_threshold_rejected_overfit`: gain < HELD_OUT_GAIN_MIN → REJECTED `overfit`, registry current unchanged
- [ ] 3.5 `test_safety_invariant_regression_rejected_harmful`: candidate fails pinned invariant / regresses baseline → REJECTED `harmful`, production unchanged, journal records invariant
- [ ] 3.6 `test_lineage_break_rejected_stale`: staging entry changed since snapshot → REJECTED `stale`
- [ ] 3.7 `test_forged_success_receipt_rejected`: receipt_digest mismatch / code digest mismatch / non-evidence dims claiming PASS / file outside lab outdir → REJECTED `forged-receipt`
- [ ] 3.8 `test_harmful_candidate_rejected_production_unchanged`: adversarial overclaim candidate → auto-REJECTED, rule set byte-identical
- [ ] 3.9 `test_rollback_restores_exact_prior_rule_set`: promote → rollback --to S → longterm bytes match backup, rule_set_digest matches, `rolled_back` row with to/reason/digests
- [ ] 3.10 `test_promote_rollback_drill_records_actions`: drill on scratch registry → one `promoted` + one `rolled_back` row, restored digests == pre-promotion snapshot
- [ ] 3.11 `test_expired_candidate_never_promotes`: generated > 30 days, no promoted row → refused `expired`, archived to `.expired/`
- [ ] 3.12 `test_evaluator_failure_keeps_staging`: evaluator crash / no receipt → failure receipt `stage: evaluation`, staging entries remain
- [ ] 3.13 `test_generation_failure_keeps_staging`: generator error → failure receipt `stage: generation`, no candidate, staging untouched
- [ ] 3.14 `test_staging_cleared_only_after_verified_candidate_and_receipt`: clear iff candidate verified AND completed receipt; otherwise retained
- [ ] 3.15 `test_failure_receipt_reproducible_digest`: same failing inputs ×2 → identical failure `receipt_digest` (ts excluded)
- [ ] 3.16 `test_source_evidence_retention_after_failure`: failed run → staging file byte-identical + failure receipt references its content hash
- [ ] 3.17 Confirm RED: `python -m pytest tests/test_distill_candidate_gate.py -q` fails on the new tests

## 4. GREEN implementation

- [ ] 4.1 distill.py: candidate-first path — content-addressed id, candidate record write, verified-then-clear condition (D1/D8); `--threshold`/`--force`/`--dry-run` kept; direct longterm write removed
- [ ] 4.2 distill.py: generation failure → failure receipt, staging untouched (D8)
- [ ] 4.3 `memory/scripts/evaluate.py`: candidate lab — corpus manifest (hash-pinned fixtures/oracles/invariants), held-in/held-out split, evaluator invocation per #81 contract, receipts to `memory/candidates/receipts/`, `--status` expiry scan (D3/D7)
- [ ] 4.4 `memory/scripts/promote.py`: 5-condition promotion gate (D4), rule-set snapshot + `memory/rules-backup/` + `memory/rules-registry.json` (D5), rollback with exact-restore verification, retire, registry print (D5/D9)
- [ ] 4.5 `memory/lifecycle-journal.jsonl`: append-only rows generated/evaluated/promoted/rejected/expired/retired/rolled_back/duplicate/failed (D2)
- [ ] 4.6 Forged-receipt checks in the gate (D6): receipt_digest recompute, code digest match, non-evidence dims, outdir provenance
- [ ] 4.7 Corpus seed fixtures under `memory/candidates/corpus/` (held-in + held-out cases + hidden oracles + manifest) — synthetic only, no host execution
- [ ] 4.8 Full suite GREEN: no new failures beyond the pre-existing set; `tests/test_distill_candidate_gate.py` passes; `memory/scripts/test_memory_pipeline.py` still green (schema/recall/forget untouched)

## 5. Verify

- [ ] 5.1 `python -m pytest tests/test_distill_candidate_gate.py -q` all pass
- [ ] 5.2 Full suites: `python -m pytest tests/ scripts/ -q` → pass apart from pre-existing failures UNCHANGED
- [ ] 5.3 CLI smoke: candidate generate → evaluate → promote on a scratch memory dir; rollback drill restores exact set; `evaluate.py --status` expires stale candidate
- [ ] 5.4 Confirm no edits to files owned by other issues: `scripts/kunglao_eval.py` / `eval/fixtures/` (#81, consumed read-only), `scripts/kunglao_verify.py` (#78 guard), `memory/scripts/forget.py` / `recall.py` / `memory_schema.py`
- [ ] 5.5 `openspec validate distill-heldout-eval-gate` PASS (final)

## 6. Commit + PR

- [ ] 6.1 Commit SDD artifacts FIRST: `sdd(distill-heldout-eval-gate): ...` (#82)
- [ ] 6.2 Commit RED tests: `test(distill): RED — candidate gate lifecycle tests (#82)`
- [ ] 6.3 Commit GREEN impl: `feat(distill): candidate-first held-out eval gate + rollback (#82)`
- [ ] 6.4 Push branch `feat/distill-heldout-eval-gate`, `gh pr create --base dev` (title `feat(distill): gate memory distillation behind held-out evaluation and rollback (#82)`) with RED→GREEN evidence
- [ ] 6.5 Do NOT merge / close / push to dev; orchestrator verifies first (maker-checker)
