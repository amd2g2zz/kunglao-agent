# Tasks — issue-250-plan-epistemics

- [x] SDD proposal + design + spec delta (this change)
- [x] RED: enumerated linear plan (steps without if-fails) rejected by the
      plan-first re-dispatch gate; branched plan passes; first dispatch and
      legacy inline plans unaffected — `tests/test_plan_gate_branching_250.py`
- [x] RED: must-master derivation (vmp/android), epistemic mint
      (boundary_type/answers_question/ΔH fields), situational PQ seeding
      (ledger.pqs first writer), signed apply_and_measure (softening delta
      negative, unclamped), settle_coverage annotation —
      `tests/test_plan_epistemics_250.py`
- [x] RED: xref/RegisterNatives semantic refutation regression —
      `tests/test_refutation_semantic_250.py`
- [x] RED: lint_facts assumptions key + observation-vs-world wording —
      `tests/test_lint_facts_assumptions_250.py`
- [x] RED: epistemic ΔH enters priority_ratio ranking via the seeded
      ledger (feed names situational source; LAMBDA_DH unchanged) —
      `tests/test_epistemic_pricing_250.py`
- [x] GREEN: scripts/plan_epistemics.py (lint/derive/mint/seed/measure/
      coverage)
- [x] GREEN: hooks/worker_budget_gates.check_worker_plan contingency leg
- [x] GREEN: scripts/refutation_propagate.py semantic face
- [x] GREEN: scripts/lint_facts.py assumptions + wording rules
- [x] GREEN: priority_ratio ΔH feed annotation (seed region untouched)
- [x] GREEN: settle-time coverage annotation in hooks/completion_gate.py
      (fail-open, non-blocking) — `tests/test_epistemic_coverage_hook_250.py`
- [x] Docs: agents/kunglao-worker.md plan format (per-step if-fails);
      templates/state/claim-register.yaml epistemic boundary_type
- [x] Register new fast test modules in tests/_tiers.py
- [x] openspec validate issue-250-plan-epistemics exits 0
- [x] Targeted suites + full fast tier + ruff on touched files green
