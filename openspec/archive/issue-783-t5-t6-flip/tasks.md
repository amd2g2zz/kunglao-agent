# Tasks — issue-783-t5-t6-flip

## 1. SDD

- [x] 1.1 proposal.md (three closure gaps + default-flip)
- [x] 1.2 design.md (digest authority, three-leg drift, gate parity, flip wiring)
- [x] 1.3 tasks.md

## 2. RED

- [x] 2.1 `tests/test_deploy_lifecycle_783.py` — T5 unit pins
      (manifest_digest equivalence, check-stale deploy-drift envelope incl.
      missing-carrier leg, early-exit refresh item + dirty refusal)
- [x] 2.2 same file — T6 e2e (real init → carrier+copies+inverted settings;
      tamper → deploy-drift; upgrade → restore+carrier; current+zero
      skill-abs paths; init idempotency)
- [x] 2.3 RED evidence captured

## 3. GREEN

- [x] 3.1 `deploy_manifest.manifest_digest` + carrier helpers + `deploy_drift`
- [x] 3.2 `deploy_workspace_copy` carrier write (+report digest)
- [x] 3.3 `deployed_refresh.refresh` carrier write
- [x] 3.4 `kunglao.py cmd_check_stale` deploy-drift criterion
- [x] 3.5 `kunglao_upgrade` early-exit refresh + shared dirty-gate block
- [x] 3.6 init default-flip in `deploy_hooks` (+ deployed_manifest report)

## 4. GUARD_TEST_SWEEP

- [ ] 4.1 sweep `uv run --project` / canonical-shape / `deployed` assertions
      across test_deploy_inversion_783, test_stale_workspace_gate_748,
      test_upgrade_safety_753, test_deploy_surface_755, test_kunglao_init,
      test_wire_up_settings, test_env_check, test_canonical_chain_752,
      test_external_kicker, test_review_hook_install
- [ ] 4.2 sync every guard that pins the pre-flip init command shape; list
      each in the PR body

## 5. Regression + quality gates

- [ ] 5.1 targeted 7-file suite green
- [ ] 5.2 full suite: failure set == the two known machine-local adb reds
- [ ] 5.3 devkit/quality_gates.py exit 0
- [ ] 5.4 release_receipt --check exit 0
- [ ] 5.5 ruff check clean
- [ ] 5.6 deploy-manifest digest regen chore commit (if scaffold shas moved)

## 6. Ship

- [ ] 6.1 review-gate evidence per commit; PR feat/783-t5-t6-default-flip → dev
- [ ] 6.2 auto-merge squash
