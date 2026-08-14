## Why

The verdict contract was rewritten (#106 verdict-scorer PQ-coverage; #107 verdict-redteam PQ blind). However, there is no mechanical schema validation for `evidence/verdict.json` output — the schema lives only in the agent markdown spec. This means:
1. Old-shape payloads (containing `classification` or `attribution` keys) can silently pass if an LLM reverts to pre-v11 behavior.
2. No structural validation enforces the v11 `analysis_verdict` shape (complete, correct, primary_questions, unresolved, contradictions, degraded, self_audit).
3. No regression tests guard against the old maliciousness/attribution schema creeping back.

This issue adds a JSON Schema (`schemas/verdict-output.json`) + validator + regression tests so the verdict output is mechanically checkable (maker-checker "mechanical gate priority").

## What Changes

- Add `schemas/verdict-output.json` (JSON Schema draft-07, mirrors `convergence-check-output.json` precedent from #97).
- Add `tests/test_verdict_contract.py` with fixture-based schema validation tests.
- Old-shape regression guards: schema rejects payloads containing `classification` or `attribution` keys.
- PQ-coverage logic fixtures: complete/incomplete, PROVEN-FULL/PROVEN-INITIAL, contradiction detection, model_selection C0b.

## Capabilities

### New Capabilities
- `verdict-output-schema`: JSON Schema for `evidence/verdict.json` mechanical validation via `conftest.py`'s `contract_validator("verdict-output", obj)`.

## Impact

- `schemas/verdict-output.json` — new file.
- `tests/test_verdict_contract.py` — new file.
- `openspec/changes/verdict-schema-guard/` — new openspec change artifacts.
- No existing files modified (audit found only unrelated identifier collisions).
