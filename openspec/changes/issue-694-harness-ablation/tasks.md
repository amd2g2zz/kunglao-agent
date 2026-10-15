# tasks — issue-694-harness-ablation

## 1. The pre-registered protocol (local-only)

- [x] protocol written to `experiments/exp-s11-h-ablation/protocol.md`
      BEFORE any run: arms H0/H1/H2, task sequence, N (>=3 repeats),
      metrics (success / time-to-correct / worker+orchestrator cost /
      false-proven), stop rule, decision rule, termination
      re-measurement
- [x] the five-face keep/cut table applied per slimming item (design.md
      carries the reviewable copy)
- [x] H0 reuses the registry's `cc-bare` face (no new arm invented)

## 2. The runner extension (per-arm accumulating store)

- [x] RED: `tests/test_eval_matrix_arm_store_694.py` — registry
      validation, store location, materialize-once + accumulation,
      torn-warm repair, launch grouping, progress receipt
- [x] `warm_up.store_mode: per-run | per-arm` (default `per-run`;
      malformed refuses at `load_config`)
- [x] `store_dir_of` + `child_env` + `materialize_store` honor the
      scope; arms stay structurally isolated; the scope binds
      store-bearing arms only
- [x] `launch_groups`: an accumulating arm's cells ride one sequential
      group in declared order (enforced for any plan order); every
      other cell keeps its own group
- [x] progress spine records `store_mode` (doc + accumulating rows)

## 3. Verification

- [x] focused suites green (the new suite, `test_eval_matrix_ws5.py`,
      `test_seven_arm_569.py`, `test_eval_registry_561b4.py`,
      `test_eval_contract_352.py`)
- [x] `openspec validate issue-694-harness-ablation` exit 0
- [x] comment-hygiene + formal-code lints clean; deploy manifest
      re-emitted and verified

## 4. Owner-gated (NOT in this change)

- [ ] owner budget approval for the real runs (S11 envelope: 54 cells,
      <=108 USD child-side + orchestrator-side cost)
- [ ] three arms run; results reported as-is (negatives included);
      the pre-ACT-BUDGET termination observation re-measured under the
      post-fix budget faces
- [ ] triage: H1>H0 -> execute the slimming list; H2>H1 -> hand the
      listed decisions to the RL; neither -> re-cut the RL scope —
      any landing is a versioned change with the ablation receipt
      attached
