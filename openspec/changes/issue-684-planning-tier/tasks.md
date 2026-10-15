# Tasks — issue-684-planning-tier

- [x] SDD proposal + design + spec delta (this change)
- [x] RED: registry tier — policy level holds exactly the six
      candidate-set controls, replan not duplicated, plan_segment is a
      worker-domain verb (tests/test_planning_tier_684.py)
- [x] RED: propensity record — mint/split/supersede record with
      producing step + propensity; non-settleable actions and illegal
      propensities refused fail-open, writing nothing
- [x] RED: revoke attribution — supersede revocable against its
      producing step; one revoke per action; unknown id refused
- [x] GREEN: action_space.py — POLICY level, ActionSpec.settleable
      flag (default False), six policy entries reusing existing
      mechanisms by reference, replan moved from orchestration,
      plan_segment demoted (consumer worker, not settleable), registry
      assert 18 → 23
- [x] GREEN: scripts/planning_actions.py — record/read/revoke over
      runs/planning-actions.jsonl (planning-action/1 +
      planning-revoke/1, schema-tagged, append-only, fail-open), CLI
      --list/--revoke
- [x] Update tests/test_action_space_12.py vocabulary pin (orchestration
      loses replan; policy tier asserted) — frozen rank capture
      untouched and green
- [x] Registrations: scripts/README.md catalog row, tests/_tiers.py
      FAST_MODULES, tools/_INDEX.ext.yaml regenerated, deploy-manifest
      regenerated
- [x] openspec validate issue-684-planning-tier exits 0
- [x] Targeted suites (test_planning_tier_684 + test_action_space_12 +
      test_priority_ratio) green; ruff on touched files; hygiene +
      formal-code baselines; comment_hygiene_lint +
      formal_code_lint + deploy_manifest --write
