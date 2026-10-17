# Tasks — issue-719-distill-action

- [x] openspec change created (proposal / design / spec delta);
      `openspec validate issue-719-distill-action --strict` green
- [x] RED: `tests/test_distill_action_719.py` — distill selectable
      (level/cost/precondition/references/estimator stub, count 24),
      budget guards enforced (per-run cap, explicit refusal reasons,
      fail-closed corruption, never-loosen clamp), reactive marker
      path unchanged (scan + reserve with no policy involvement; tick
      step still owns the auto-fire) — 6 failed pre-implementation,
      the reactive-path pin passed (it must — the path is unchanged)
- [x] GREEN: `orchestration.distill` entry in `scripts/action_space.py`
      (ORCHESTRATION level alongside osint, cost 5, availability-or-
      initiative precondition — no trigger rule, references naming
      online_distill + runs/distill-budget.json), assert 23 → 24;
      `actuate_distill` budget seam delegating to
      `online_distill.reserve_act` (one call, one receipt, refusals
      diagnosed via `refuse_reason`)
- [x] `tests/test_action_space_12.py` EXPECTED_ORCHESTRATION gains
      `distill` (the vocabulary pin moves with the vocabulary);
      frozen-capture byte-equivalence stays green
- [x] Gates: `tests/test_distill_action_719.py tests/test_action_space_12.py`
      green under `-n 2` (43 passed); neighboring registry consumers
      (planning_tier_684, action_space_539, factor_vector_12,
      priority_data_hookup_9, value_flag_removed_51) green;
      comment_hygiene_lint / formal_code_lint baselines re-minted
      byte-identical (no new debt); deploy-manifest refreshed
- [x] Review gate: independent code-reviewer PASS (0 CRITICAL / 0 HIGH;
      the one MEDIUM — openspec dir sweep-in — resolved by the docs
      commit in this same series) → evidence + mint per commit;
      push + PR to dev with the openspec mapping table
