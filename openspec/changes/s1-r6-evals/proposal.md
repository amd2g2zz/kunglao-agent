# Proposal — evals/evals.json skill-creator evals (#117)

## Why

The skill-creator manual requires skills to have an `evals/evals.json` file defining at
least 3 evals with id, prompt, expected_output, files, and expectations fields. The
kunglao-agent repo has no such file. The existing `eval/fixtures/` directory contains
internal harness fixtures (case.json + oracle.json) for the `kunglao_eval.py` module, but
these serve a different purpose (L2 red-team bounded episodes with arm A/B/C configs
and fault injection). The skill-creator evals.json is a separate contract describing
scenario-level behavioral expectations for the skill as a whole.

## What Changes

- **`evals/evals.json`** (new): Skill-creator-compliant eval manifest with 3 evals:
  1. **Convergence loop dispatch** (id=1): Given a fixture workspace with an open
     claim, the orchestrator must dispatch per priority.py rather than idling.
  2. **Maker-checker verification** (id=2): A worker produces a fact; an independent
     verifier blind-verifies and passes (no self-stamp).
  3. **Verdict correctness/completeness** (id=3): Given a converged fact base and
     task_spec, the verdict outputs PQ-coverage verdict without maliciousness/attribution
     (B4-2 decoupled behavior).

- **`tests/test_evals_schema.py`** (new): Validates evals.json structural requirements:
  1. File exists and is valid JSON.
  2. Contains `skill_name` matching "kunglao-agent".
  3. Contains at least 3 evals.
  4. Each eval has required fields: id, prompt, expected_output, expectations.
  5. Each eval id is a positive integer.
  6. Each eval has at least one expectation.

## Non-goals

- Does NOT modify `eval/` or `eval/fixtures/` (internal harness).
- Does NOT modify `scripts/kunglao_eval.py` (module-level eval infrastructure).
- Does NOT change SKILL.md or any hooks/scripts.
- Does NOT add new behavioral tests beyond the schema guard.

## Capabilities

### Added Capabilities

- `evals-manifest`: a skill-creator-compliant evals/evals.json with 3 scenario-level
  evals covering convergence dispatch, maker-checker verification, and verdict
  correctness/completeness, enabling the skill-creator grading pipeline to evaluate
  the skill.

## Impact

- `evals/evals.json`: new, ~80 lines (3 eval entries).
- `tests/test_evals_schema.py`: new, ~55 lines (6 assertions).
- Suite impact: +6 new passing tests; 0 existing tests modified; no regressions.
- Related: #81 (eval harness), #115 (references index) -- no overlap.
