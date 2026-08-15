## Why

`verdict-scorer` currently implements Stage 6 maliciousness scoring (6-dim -> classification) and threat attribution (Admiralty+ACH+Diamond -> named actor). Both capabilities are **out of scope** for kunglao-agent, which verifies RE analysis correctness/completeness against `task_spec.primary_questions` -- it does NOT do threat classification, attribution, or CTI. The agent must be rewritten as a pure PQ-coverage verifier.

## What Changes

- **BREAKING**: Remove all maliciousness scoring (6 dimensions, classification, severity, sandbox harness-confound table).
- **BREAKING**: Remove all attribution logic (Admiralty ledger, Diamond map, ACH hypotheses, S5 named-actor gate, attribution verdict).
- **BREAKING**: Remove all anti-patterns related to classification and attribution.
- Add PQ-coverage verification: read `task_spec.yaml` primary_questions, match to PROVEN facts via `answers_question`, enforce confidence bands (C0a/C0b mirrors convergence).
- Add cross-consistency check: consume `fact_contradiction_gate.py` output for contradiction detection.
- Replace output schema with `analysis_verdict` (complete, correct, primary_questions, unresolved, contradictions, degraded).
- Keep `degraded[]` self-honesty convention (mirrors #78 fail-closed).
- Keep `self_audit` block.
- Keep frontmatter `allowedTools` / `disallowedTools` unchanged.

## Capabilities

### New Capabilities
- `pq-coverage-verdict`: Primary-question coverage verification -- for each `task_spec.primary_questions[]` entry, find the answering fact, verify PROVEN status + confidence_band, produce `evidence/verdict.json` with `analysis_verdict` schema.

### Modified Capabilities
(none -- the old maliciousness/attribution capabilities are removed, not modified)

## Impact

- `agents/verdict-scorer.md` -- full rewrite (the only code-change file in scope).
- `agents/verdict-redteam.md` -- NOT in scope (separate issue #107).
- `SKILL.md` -- NOT in scope (separate issue #108/109).
- Tests: existing `test_release_receipt.py` references `verdict-scorer.md` by filename only (no schema pinning) -- no breakage. New contract test `test_verdict_scorer_contract.py` added.
- Downstream agents that consume `evidence/verdict.json` will see a schema break (classification/attribution keys gone, analysis_verdict added) -- this is intentional per the scope boundary correction.
