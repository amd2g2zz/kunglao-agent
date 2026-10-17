# tasks — issue-695-recipe-arms

## 1. The arm registry + sampler (T4)

- [x] `scripts/rlvr/recipe_arms.py`: `RecipeArm` registry — 12
  closed-vocabulary families × 3 arms (tool_class / invocation /
  artifact / prior), `ARMS_BY_FAMILY` / `ARMS_BY_ID` derived maps
- [x] `arm_weights`: `prior · max(θ, THETA_FLOOR)` with the
  LAMBDA-tempered cross-agent warm start (owner comment 2026-10-15:
  per-agent posteriors, never forced pooling); `sample_recipe` the
  deterministic proportional draw

## 2. Dispatch recording (T2)

- [x] `q_cells.append_observation`: additive `recipe_id` /
  `recipe_propensity` / `recipe_source` columns (emitted together, only
  when the view names a recipe — every pre-#695 writer byte-identical;
  boundary validation degrades to null + warn)
- [x] `q_cells.record_dispatch_observation`: the recipe view via
  `recipe_arms.record_dispatch_recipe` (envelope `recipe_id` reconciled
  against the gate's own draw; fail-open to the none gap), result gains
  the additive `recipe` view
- [x] `event_taxonomy.EMIT_ACTIONS`: `recipe_deviation` registered

## 3. Trusted settlement attribution (T3)

- [x] `q_cells.observe_settlement`: the triple rides the settlement
  row + the result (ITT against the dispatch-recorded recipe; no
  worker narrative is read — the #881 pattern stays dead)
- [x] `recipe_arms.arm_fold`: solve-credit-only (a
  `credit_kind: verification` row is excluded per #705)

## 4. RED tests

- [x] `tests/test_recipe_arms_695.py`:
  `test_dispatch_records_recipe_propensity_and_source` /
  `test_settlement_banks_credit_against_recipe_without_worker_narrative`
  (lying `steps:` narrative planted) /
  `test_recipe_arms_floor_weight_never_deleted` /
  `test_no_new_reject_surface_for_tool_choice` (deviation + unregistered
  both pass) / `test_replay_reports_arm_level_separation`

## 5. S2 replay (T5)

- [x] `recipe_arms.replay_report`: offline arm-level separation +
  disagreement rate (pure read; the online switch stays #50/#13's call)

## 6. Registration surfaces

- [x] `scripts/README.md` directory row for `rlvr/recipe_arms.py`
- [x] deploy manifest re-emitted (`scripts/deploy_manifest.py --write`)
- [x] comment-hygiene / formal-code lint baselines re-emitted
- [x] ext-scan: no entry needed (no `__main__` entry point; rlvr
  subpackage is outside the scripts/*.py CLI glob)

## 7. Verification

- [x] targeted suite green (`pytest tests/test_recipe_arms_695.py -n 2`
  5/5; regression batches: q_cells/691/MARL/emit-gate 83 passed,
  settlement/worker-budget/strategy 186 passed)
- [x] `ruff check` clean on the touched files
- [x] `npx openspec validate issue-695-recipe-arms` exit 0
