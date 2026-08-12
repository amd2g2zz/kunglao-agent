## 1. OpenSpec Change Artifacts

- [x] 1.1 Create `openspec/changes/verdict-schema-guard/proposal.md`
- [x] 1.2 Create `openspec/changes/verdict-schema-guard/design.md`
- [x] 1.3 Create `openspec/changes/verdict-schema-guard/tasks.md` (this file)
- [x] 1.4 Create `openspec/changes/verdict-schema-guard/specs/verdict-output-schema/spec.md`

## 2. RED Phase — Write Tests First

- [ ] 2.1 Create `tests/test_verdict_contract.py` with:
  - Schema validation REJECTS payload with `classification` key
  - Schema validation REJECTS payload with `attribution` key
  - Fixture: all PQs PROVEN-FULL → `complete: true`, `unresolved: []`
  - Fixture: 1 PQ no citing fact → `complete: false` + PQ in `unresolved`
  - Fixture: PQ cited but only PROVEN-INITIAL → `complete: false`
  - Fixture: same-topic 2 PROVEN facts without supersedes → `contradictions` non-empty
  - Fixture: model_selection PQ with 1 PROVEN + rest REFUTED → `complete: true`
- [ ] 2.2 Verify tests FAIL (schema file does not exist yet → `pytest.fail("schema file missing")`)

## 3. GREEN Phase — Implement Schema

- [ ] 3.1 Create `schemas/verdict-output.json` (JSON Schema draft-07) with:
  - Top-level required: `_meta`, `sample_sha256`, `analysis_verdict`, `self_audit`
  - `additionalProperties: false` on top-level and `analysis_verdict`
  - `analysis_verdict` required: `complete`, `correct`, `primary_questions`, `unresolved`, `contradictions`, `degraded`
  - `primary_questions[].id`, `answered`, `cited_fact`, `confidence_band`, `gap`
  - `self_audit` required: `evidence_strength`, `ignored_evidence`, `open_questions`
- [ ] 3.2 Verify all new tests PASS

## 4. Validate

- [ ] 4.1 Run `python -m pytest tests/test_verdict_contract.py tests/test_release_receipt.py tests/test_global_rule_subset.py -v` → all green
- [ ] 4.2 Run `python -m pytest -q` → no new failures beyond known 2 pre-existing
- [ ] 4.3 Verify old-shape grep: `grep -rl "classification\|attribution" tests/ | grep -v test_no_cti_agents | grep -v test_verdict_scorer | grep -v test_verdict_redteam` → only unrelated collisions remain
- [ ] 4.4 OpenSpec validate (if tool available)

## 5. Stage

- [ ] 5.1 `git add` new files only: `schemas/verdict-output.json`, `tests/test_verdict_contract.py`, `openspec/changes/verdict-schema-guard/`
- [ ] 5.2 Verify `git diff --cached --stat` shows expected files
- [ ] 5.3 NO commit, NO push
