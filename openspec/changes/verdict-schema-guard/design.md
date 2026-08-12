## Context

The verdict-scorer agent (#106) was rewritten from a maliciousness/attribution scorer to a pure PQ-coverage verifier. The output schema moved from `{classification, attribution_evidence, ...}` to `{_meta, sample_sha256, analysis_verdict: {complete, correct, primary_questions, unresolved, contradictions, degraded}, self_audit}`. However, no mechanical schema file exists under `schemas/` — the prior change explicitly decided against it (D5 in verdict-scorer-pq-coverage).

This issue adds the mechanical validation layer so the verdict is checkable by scripts/tests, not just LLM self-report. The `conftest.py` `contract_validator` fixture already provides a `jsonschema.Draft7Validator` wrapper for `schemas/*.json` files.

## Goals / Non-Goals

**Goals:**
- Create `schemas/verdict-output.json` mirroring the v11 `analysis_verdict` schema from `agents/verdict-scorer.md`
- Old-shape regression guards: `classification` and `attribution` keys are forbidden (schema uses `additionalProperties: false` or explicit `not` patterns)
- Fixtures covering: all-PQs-answered, missing-citing-fact, PROVEN-INITIAL-only, contradictions, model_selection C0b
- All tests pass via `contract_validator("verdict-output", obj)` from conftest.py

**Non-Goals:**
- Do NOT edit `agents/verdict-scorer.md` or `agents/verdict-redteam.md` (already merged).
- Do NOT edit `SKILL.md` or `DESIGN.md` (separate issues #108/#109).
- Do NOT create a runtime validator script — the JSON Schema is consumed via pytest `contract_validator` fixture.

## Decisions

### D1: Use additionalProperties: false for regression guard
**Decision**: Set `additionalProperties: false` on the top-level object and on `analysis_verdict`. This mechanically rejects any key not in the v11 schema, including old-shape keys like `classification` and `attribution`.
**Rationale**: Strongest regression guard. If an LLM reverts to pre-v11 behavior, the schema validation fails immediately.

### D2: Embed regression tests as fixture-based pytest tests
**Decision**: Create `tests/test_verdict_contract.py` with pytest fixtures for each scenario (complete, incomplete, contradiction, C0b), plus explicit tests that construct payloads with forbidden keys and assert validation failure.
**Rationale**: Follows the existing test pattern in the codebase (e.g., `test_verdict_scorer_contract.py`). The `contract_validator` fixture from `conftest.py` provides the validation.

### D3: No separate validator module
**Decision**: The JSON Schema file is consumed directly by `conftest.py`'s `contract_validator("verdict-output", obj)`. No separate `validate_verdict.py` script.
**Rationale**: YAGNI — the test infrastructure already handles schema loading and validation. A separate validator would be speculative.

## Risks / Trade-offs

- `additionalProperties: false` is strict: any future key added to the verdict schema requires a schema update. This is intentional — it forces explicit schema evolution.
- The schema validates structure, not semantics (e.g., whether `cited_fact` actually exists in `facts/`). Semantic validation is the agent's responsibility.
