# Tasks

## 1. RED tests (fixture-shape coverage)

- [ ] 1.1 Extend `tests/test_convergence_completeness.py` with a `_make_ws(..., ts_text=None)` override so tests can inject raw task_spec.yaml content
- [ ] 1.2 Add RED5 tests: canonical `{id, need}` form parses and gates fire (orphan/unverified/CONVERGED happy path)
- [ ] 1.3 Add RED5 tests: plain string form parses; legacy one-key mapping parses (id set non-empty; gates fire)
- [ ] 1.4 Add RED5 tests: explicit empty list stays feature-unused (CONVERGED allowed with orphan)
- [ ] 1.5 Add RED5 tests: malformed fixtures (two-key mapping without id, non-string id, non-str item, mixed list with malformed item, duplicates) → `decide()` returns `INVALID`, exit code 4, reason in `action`/`pq_parse_error`, never `CONVERGED`/exit 0
- [ ] 1.6 Add RED5 tests: mixed accepted forms normalize to a non-empty set; top-level mapping form preserved
- [ ] 1.7 Run focused command — confirm RED (existing 4 + new failures)

## 2. Implement canonical parse in scripts/convergence_check.py

- [ ] 2.1 Add `_parse_primary_questions(task_spec) -> (list[(qid, need)], error)` covering all accepted forms and all malformed shapes (D1, D4, D5, D6)
- [ ] 2.2 Refactor `_pq_ids()` to a thin wrapper over the canonical parse
- [ ] 2.3 Refactor `_unverified_primary_questions()` to consume the canonical parse
- [ ] 2.4 Refactor `decide()`: parse once, add `INVALID` decision (exit 4) checked before the matrix (D2, D3), add `pq_parse_error` field
- [ ] 2.5 Run focused command — all green

## 3. Full-suite verification and PR

- [ ] 3.1 Run `uv run --with pyyaml --with pytest python -m pytest -q scripts/` — green (no new failures)
- [ ] 3.2 Run full `tests/` suite — only the 2 known pre-existing failures remain (`test_acceptance_overall_passes`, `test_skill_lte_500_lines`); all 4 convergence_completeness failures now green
- [ ] 3.3 `openspec validate primary-questions-schema-normalization` prints "is valid"
- [ ] 3.4 Push `fix/primary-questions-schema` and open PR to `dev` with RED→GREEN evidence; do NOT merge/close
