# Capability: verdict-output-schema

## Specification

A JSON Schema (draft-07) for `evidence/verdict.json` produced by `verdict-scorer` v11. Consumed via `conftest.py`'s `contract_validator("verdict-output", obj)`.

### Schema Structure

```
schemas/verdict-output.json
  $schema: http://json-schema.org/draft-07/schema#
  $id: kunglao-agent/schemas/verdict-output.json
  type: object
  additionalProperties: false  ← regression guard: rejects old-shape keys

  required: [_meta, sample_sha256, analysis_verdict, self_audit]

  _meta:
    type: object, additionalProperties: false
    required: [source, schema_version, queried_at, methodology]
    source: string (must equal "verdict-scorer")
    schema_version: string (pattern: "^\\d{4}-\\d{2}-\\d{2}-v\\d+$")
    queried_at: string (ISO8601 datetime)
    methodology: string

  sample_sha256: string (pattern: "^[0-9a-f]{64}$")

  analysis_verdict:
    type: object, additionalProperties: false  ← rejects classification/attribution
    required: [complete, correct, primary_questions, unresolved, contradictions, degraded]
    complete: boolean
    correct: boolean
    primary_questions: array of PQ items
    unresolved: array of strings (question IDs)
    contradictions: array of contradiction objects
    degraded: array of degraded objects

    primary_questions[]:
      type: object, additionalProperties: false
      required: [id, answered, cited_fact, confidence_band, gap]
      id: string
      answered: boolean
      cited_fact: string (null allowed)
      confidence_band: string (null allowed)
      gap: string (null allowed)

    contradictions[]:
      type: object
      required: [question, fact_a, fact_b, nature]
      question: string
      fact_a: string
      fact_b: string
      nature: string

    degraded[]:
      type: object
      required: [reason, affected_question]
      reason: string
      affected_question: string (null allowed)

  self_audit:
    type: object, additionalProperties: false
    required: [evidence_strength, ignored_evidence, open_questions]
    evidence_strength: string (enum: ["strong", "mixed", "weak"])
    ignored_evidence: array of strings
    open_questions: array of strings
```

### Regression Guards

The `additionalProperties: false` constraint on both the top-level object and `analysis_verdict` ensures that old-shape keys (`classification`, `attribution`, `attribution_evidence`, `maliciousness`, `named_actor`, `leads`, `severity`, etc.) are mechanically rejected by the schema validator.

### Test Coverage

- `tests/test_verdict_contract.py` validates:
  1. Old-shape regression: payloads with `classification` or `attribution` keys → validation failure
  2. All-PQs-answered fixture → `complete: true`, `unresolved: []`
  3. Missing-citing-fact fixture → `complete: false`, PQ in `unresolved`
  4. PROVEN-INITIAL-only fixture → `complete: false`
  5. Contradiction fixture → `contradictions` non-empty
  6. model_selection C0b fixture → `complete: true`
