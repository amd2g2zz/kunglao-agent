# Validation receipt

All data used here is synthetic. No sample was executed on the host. External
worker/checker/settler model output is mocked; the real dispatch, SubagentStop,
blind-input, settlement, credit, sampler and subprocess Stop components run.

- RED: original production-terminal and persisted-S5 suites: 2 failed, 14 passed.
  Eligible success and verified failure both lacked episodes.
- Production boundary suites (`test_production_terminal_1005`,
  `test_face_spans_1005`, `test_production_learning_1005`,
  `test_s5_persisted_boundary_1005`): 26 passed. Also rerun after introducing
  platform-specific locking in a combined facade run: all 26 passed; that run
  separately exposed two missing facade exports, subsequently corrected.
- Existing requested regressions (`completion_gate`, `episode_settle`,
  `e2e_resume_rl_rounds_1005`, `e2e_init_analysis_rounds_1005`,
  `learning_seal_1005`, `decision_feedback_1005`, `orphan_resolver_1005`,
  `strategic_declaration_1005`): 177 passed in 789.10 seconds.
- Existing settlement-input quality regression: 11 passed.
- Full test collection: 14,482 tests collected; full execution was not run.
- OpenSpec validation: passed. Scoped `devkit.spec_coverage.check_change`: [].
- Facade regression: 4 passed after consumed-module exports were corrected.
- Ruff on touched Python files: final rerun passed. Deployment-manifest
  regeneration is included; final verification is recorded by the handoff.

The tests distinguish initial settlement from the existing legitimate scalar
tier amendment. They check stable credit after duplicate completion/Stop and
preservation of pre-existing append-only rows after partial-write recovery.
The armed test saves paired sampler receipts within its temporary workspace;
this is component evidence, not an expert-capability or efficacy benchmark.

Not yet verified: real Windows locking/durability, real Claude session
liveness, real samples, abrupt process exit/kill, dispatch/worker/checker stage
spans, five synthetic paired environments and the 200+200-seed evaluator.
`devkit/experiments/v016_within_task.py` does not exist. S5 owner-dependent
acceptance remains open. This slice does not close issue #1005.

## Independent review P1 revision

The three original reviewer probes were run unchanged with current-worktree
helper modules preloaded (their hardcoded `/tmp` snapshot path otherwise selects
the previous candidate). They failed 3/3 before this revision and passed 3/3
after it (52.15 seconds). The original probe file was not edited or removed.

The eight added `test_production_terminal_faults_1005` cases passed in 144.56
seconds. They cover notes I/O/YAML/shape failures and recovery, a tampered
round-credit row, a missing/short seal key without rewriting the original row or
key, and a genuine subprocess Stop whose existing Q-cell recovery owner
swallows an injected write exception. That Stop blocks, retains a named retry
checkpoint and unchanged settlement facts; the next successful Stop restores
credit and a repeat does not add credit.

The new production suites plus completion/episode/seal/rejection/orphan/S5,
facade and input-quality regressions passed together: 213 passed in 294.24
seconds. E2E resume/init regressions are run separately. Ruff on all touched
Python files, OpenSpec validation, scoped `check_change: []`, deployment manifest
verification (665 entries) and `git diff --check` passed. No full pytest run,
real Windows run or real sample execution is claimed. The earlier remaining
acceptance tasks remain open.

The separately run resume/init E2E group initially returned 4 passed and one
init subprocess timeout at 180 seconds (seed 23, before terminal settlement).
The exact failed test was rerun unchanged and passed in 159.40 seconds. No
assertion, timeout, fixture or baseline was weakened. This is a recorded
intermittent initialization timeout, not a claim of a clean first E2E run.
The three P1 fixes still require an independent specification re-review; this
worker receipt is not review approval.
