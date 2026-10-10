# Tasks

- [x] 0. openspec strict-valid + design review (three adjudication points:
      schema / retrieval loop / coverage+disambiguation) — disclosed
      self-review per the #478 quota-wall precedent
- [x] 1. RED: `tests/test_query_formulation_487.py` — formulation schema
      (facets/provenance, 3–5, closed kinds), per-facet retrieval, both
      disambiguation paths, fixture hit-rate comparison (formulation beats
      fragments, counts pinned)
- [x] 2. GREEN: `scripts/query_formulation.py` — formulate_problem +
      retrieve_facets + coverage/disambiguation + CLI face
- [x] 3. Wire e2e: `_maybe_distill` starts with formulation; prompt carries
      facets + coverage; `distill_result` detail carries the coverage matrix
      (emit_distill_result `coverage=` kwarg); fail-open degradation test
- [x] 4. Wire production: `online_distill.formulate_for_trigger` +
      `stamp_trigger(..., formulation=)` + `--scan` parity +
      `hooks/round_closure.py` + SKILL.md protocol sentence; stamp test
- [x] 5. Fixture corpus `tests/fixtures/query-formulation-487/corpus/`
      (6 cards) + staged-workspace helpers
- [x] 6. Registrations: scripts/README.md row → tools/ext-scan.py regen →
      deploy-manifest re-mint (order matters); hygiene baseline entries for
      the two new files
- [x] 7. Gates: ruff clean; devkit --quick ALL-PASS; silent-except /
      invocation-hygiene / dep-surface / doc-sync / agents-lint clean;
      review gate (independent reviewer PASS → evidence mint) below;
      PR to dev, five legs green, merge
- [ ] 8. Comment the delivery on #487 (do NOT close — release-train
      convention)
