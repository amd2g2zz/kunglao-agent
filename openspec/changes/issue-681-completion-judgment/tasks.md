# tasks — issue-681-completion-judgment

## 1. RED (tests first)

- [x] `tests/test_completion_681.py`: checker-PASS upgrades a BLOCKED
  run (label + exit + ORACLE evidence); checker FAIL keeps the label;
  PARTIAL upgrades too (ORACLE-on-partial)
- [x] candidate contract: declared path wins; undeclared mismatch emits
  one typed `candidate-undeclared` event (never a silent .py
  fallback); .py families stay silent; unregistered families fail open
- [x] monotone delivery: `runs/deliverable-best-so-far.json` on
  PARTIAL; honest absence with no candidate
- [x] pins: every declared `checker.candidate` matches
  `eval_contract.candidate_suffix`; every non-.py unit declares one

## 2. The checker completion ruling (D-681.1)

- [x] `scripts/e2e/checkpoints.py`: `_checker_completion_ruling`
  (BLOCKED/PARTIAL scope; runs `checkpoint_oracle` when it has not
  run; PASS → `checker-PASS` + exit 0; fail-open one warn)
- [x] `_deliver_best_so_far` monotone hand-off (ws-relative + sha256 +
  label; never retracted; honest absence)
- [x] finalize wiring: ruling → delivery → `_final_verdict_of` → report

## 3. The candidate resolution contract (D-681.2)

- [x] `scripts/e2e/model.py`: `resolve_candidate(..., events=)` +
  `_family_contract_suffix` (eval_contract single source; fail-open)
- [x] `checkpoint_oracle` threads `candidate_events` into the evidence
  detail (both the no-candidate stop and the graded run)
- [x] declarations: 34 non-.py units declare their contract path
  (`client{suffix}` / `verdict.json` / `answer.txt`)
- [x] schema citizenship (review MEDIUM): `schemas/eval-task-v1.json`
  declares the optional `candidate` string; `eval_dataset.
  _validate_candidate_decl` rejects non-string declarations (ruff
  C901 drove the helper extraction)
- [x] `scripts/eval_toolflex.py`: the generator emits the toolflex
  declaration (re-mint stays byte-identical)

## 4. Verification

- [x] `uv run ruff check` clean on every touched Python file
- [x] `uv run python -m pytest tests/test_completion_681.py -q -n 2`
  → 14 passed (incl. the review-LOW tightenings: exact delivery-digest
  pin, never-retracted monotone pin)
- [x] regression: `tests/test_e2e_runner.py`,
  `tests/test_c7_chain_matrix4b.py` (108 passed); eval suites
  (dataset/contract/loop/release/chain/toolflex/misdirection/native/
  control-arm/oracle) green
- [x] `openspec validate issue-681-completion-judgment` exit 0
