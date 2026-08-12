# Tasks — executable, evaluator-owned L2 red-team evaluation (#81)

## 1. Setup

- [x] 1.1 Worktree wt81 on branch `feat/executable-eval` at dev baseline `105f6ff` (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline measured: full suite (tests/ + scripts/) = 618 passed + 6 pre-existing failures + 1 skipped, with `--with pyyaml --with pytest --with jsonschema --with pefile --with capstone`; plain `--with pyyaml --with pytest` adds env failures (capstone/pefile/jsonschema missing in ephemeral env). Expected pre-existing failures: test_acceptance_overall_passes, test_contract_docs::test_skill_lte_500_lines, 4× test_convergence_completeness (owned by parallel subagents — do NOT touch)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 `openspec new change executable-l2-evaluation` scaffolded (.openspec.yaml)
- [x] 2.2 proposal.md (why: scaffold/NOT-RUN mistaken for completed evaluation; scope; acceptance)
- [x] 2.3 design.md (D1-D8: dispatcher/tool-adapter boundary, episode loop, fault-as-state-transition table, arms, hidden oracle, receipts, CLI, files)
- [x] 2.4 specs/executable-l2-evaluation/spec.md (REQ ×5 + scenarios)
- [x] 2.5 tasks.md
- [x] 2.6 `openspec change validate executable-l2-evaluation` PASS ("is valid")
- [x] 2.7 Commit openspec artifacts FIRST (conventional commit)

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_fixture_corpus_three_safe_cases`: eval/fixtures contains decode-flag / impossible-task / adversarial-evidence, each with case.json + oracle.json, valid JSON, synthetic-only marker
- [x] 3.2 `test_decode_episode_runs_and_writes_receipt`: arm A, no fault → terminates, claim concludes per oracle, receipt JSON+MD written with digests/transcript_hash/taxonomy/wall_ms/budgets/cleanup
- [x] 3.3 `test_repeated_trials_replayable`: same (case, arm, fault, seed) ×2 → identical receipt_digest
- [x] 3.4 `test_three_arms_same_loop`: A/B/C all run decode-flag; same case digest; per-arm policy differences visible
- [x] 3.5 `test_fault_throttle_budget_exhausted`: lowered budget → budget_exhausted transition, remaining claim OPEN, verdict FAIL (or INCONCLUSIVE when explicit incomplete)
- [x] 3.6 `test_fault_implicit_fail_no_evidence_no_conclusion`: ok=False empty payload → no conclusion from empty evidence; overclaim if concluded
- [x] 3.7 `test_fault_explicit_fail_not_redispatch`: adapter raises → claim DEFERRED; repeated re-dispatch → invalid_work → FAIL
- [x] 3.8 `test_fault_impossible_excluded_and_never_dispatched`: never dispatched via real priority_ratio; forced dispatch = invalid work
- [x] 3.9 `test_fault_adversarial_decoy_overclaim`: decoy conclusion → overclaims>0, verdict FAIL; correct-path candidate passes
- [x] 3.10 `test_l2_non_evidence_never_passes`: real l2_redteam without dispatcher → NOT-RUN → L2 capability dimension FAIL/INCONCLUSIVE; NOT-RUN never contributes to a passing score; failed injection / missing dispatcher likewise
- [x] 3.11 `test_oracle_selfcheck_still_10_10_separate`: oracle_selfcheck unchanged 10/10; capability score never includes oracle cases
- [x] 3.12 `test_inject_without_run_fails_loud`: `--inject throttle` alone → exit 2 + guidance (no scaffold print)

## 4. GREEN implementation

- [x] 4.1 eval/fixtures/ decode-flag, impossible-task, adversarial-evidence (case.json + oracle.json; synthetic only)
- [x] 4.2 kunglao_eval.py: ToolResult/ToolAdapter/RecordedToolAdapter, DispatchResult/Dispatcher/RecordedDispatcher
- [x] 4.3 kunglao_eval.py: EpisodeState + run_episode (real priority_ratio; arms A/B/C policies; bounded steps/budgets; temp ws; cleanup)
- [x] 4.4 kunglao_eval.py: fault injection hooks (throttle/implicit_fail/explicit_fail/impossible/adversarial)
- [x] 4.5 kunglao_eval.py: OracleScorer (hidden oracle; correctness/invalid_work/misses/overclaims/recovery/time/cost; overall PASS/FAIL/INCONCLUSIVE)
- [x] 4.6 kunglao_eval.py: l2_redteam_capability via real kunglao_verify.l2_redteam + injected RecordedDispatcher (NOT-RUN/UNKNOWN/failed injection/missing dispatcher = non-evidence)
- [x] 4.7 kunglao_eval.py: write_receipts JSON+MD with digests (case/oracle/code/env), transcript hash, taxonomy, wall_ms, budgets, cleanup; receipt_digest stable
- [x] 4.8 CLI: --run/--all/--arm/--inject/--repeat/--outdir/--seed; --inject alone exits 2; oracle_selfcheck untouched
- [x] 4.9 Full suite GREEN: no NEW failures beyond the 6 pre-existing; eval tests pass

## 5. Verify

- [x] 5.1 `uv run --with pyyaml --with pytest python -m pytest -q tests/ scripts/` final counts (report both plain and full-extra runs)
- [x] 5.2 CLI end-to-end smoke: `--oracle-selfcheck` (10/10), `--all --repeat 2` receipts replayable, `--inject throttle` alone exits 2
- [x] 5.3 Confirm no edits to files owned by other issues (convergence_check.py #77, kunglao_record.py/hooks/worker_budget.py #78, external_kicker.py #79, release/README/kunglao.py #80, memory/distill.py #82); kunglao_verify.py untouched (read-only import)

## 6. PR

- [x] 6.1 `git push -u origin feat/executable-eval`
- [x] 6.2 `gh pr create --base dev --head feat/executable-eval` title `feat(eval): executable evaluator-owned L2 red-team episodes (#81)` with summary + evidence
- [ ] 6.3 STOP — do NOT merge/close/delete; report PR number/URL, test counts, openspec validate result, dispatcher-injection design, fixture list, receipt schema to orchestrator
