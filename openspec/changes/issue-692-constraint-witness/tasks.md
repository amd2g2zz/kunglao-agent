# tasks — issue-692-constraint-witness

## 1. Gate 1 — spec first

- [x] 1.1 openspec change `issue-692-constraint-witness` (proposal,
      design, tasks, specs/constraint-witness/spec.md);
      `openspec validate issue-692-constraint-witness --strict` green.

## 2. RED (TDD — tests from the spec scenarios)

- [x] 2.1 `tests/test_constraint_witness_692.py`:
      `test_not_done_without_witness_is_refused_at_lint` — no block and
      partial coverage exit non-zero with a witness-named error; full
      check/none coverage exits zero; `--stamp-dispatch` refuses the bare
      document.
- [x] 2.2 `test_degraded_solution_with_green_outcome_fails_oracle` — a
      workspace violating a witnessed `not_done` row evaluates FAIL and a
      green outcome (`PASS`) composes to FAIL; clean control stays PASS.
- [x] 2.3 `test_joint_verdict_requires_witness_and_outcome` — truth table
      (only PASS+PASS yields PASS) + fail-open UNDECLARED postures with
      warnings (missing file, blockless document).

## 3. GREEN — schema + lint (T2)

- [x] 3.1 `scripts/goal_operationalization.py`: `WITNESS_SCHEMA`,
      `witness_block`/`witness_map`, `_witness_spec_error`,
      `_witness_errors` wired into `_content_errors` (R6).
- [x] 3.2 constitution freeze: `stamp_dispatch` deep-copies the witness
      map into `constitution.constraint_witness`;
      `_constitution_errors` refuses post-dispatch withdrawal/weakening.

## 4. GREEN — joint oracle verdict (T3)

- [x] 4.1 new `scripts/e2e/constraint_witness.py`: `evaluate` (sh -c
      check contract, KUNGLAO_WS/KUNGLAO_REPO export, verdicts
      holds/violation/declared-none/error, fail-open + warn postures) and
      `joint` (witness AND outcome).
- [x] 4.2 `scripts/e2e/checkpoints.py`: `build_goal_op_doc` declares the
      witness block; `checkpoint_oracle` evaluates the block through the
      ctx.cmd seam, records `detail.constraint_witness`, and ends with
      `status = joint(status, witness.status)`; docstrings updated.
- [x] 4.3 fixture fallout: goal-operationalization fixtures (#128
      `_doc`/`_sim_doc`/append case, declared-coverage builder,
      heartbeat teardown workspace) carry witness blocks so their
      valid/converged semantics are preserved.

## 5. Operator-facing surfaces

- [x] 5.1 skill pre-registration step + validator refusal list,
      heartbeat constitution fill list, init draft scaffold, state
      template block, e2e runbook C6-pre-1 template, scripts README
      catalog row (R6 + the joint verdict pointer).

## 6. Local-only demonstration (T4)

- [x] 6.1 `experiments/blocked-path-units/degraded-jsrpc/` (gitignored,
      never committed): goal-op with a browser/JSRPC witness, the
      degraded artifact, and the evaluate → FAIL → joint-RED run notes.

## 7. Verification

- [x] 7.1 targeted tests green:
      `pytest tests/test_constraint_witness_692.py -q -n 2`.
- [x] 7.2 fallout suites green: goal-operationalization, declared
      coverage, heartbeat-off, e2e runner, loop-completion, intake
      admission, rlvr p0.
- [x] 7.3 `ruff check` on touched Python files; comment-hygiene and
      formal-code lints at baseline (no new debt); deploy manifest
      re-emitted.
- [x] 7.4 `openspec validate issue-692-constraint-witness --strict`.
- [x] 7.5 `gitnexus detect-changes` before commits; commits <= 300 lines
      each; experiments/ stays local.
