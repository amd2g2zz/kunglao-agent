# issue-824-model-contract — tasks

1. [ ] SDD: openspec change directory (this change), `openspec validate` clean
2. [ ] RED: `tests/test_model_contract_824.py` — synthetic fixtures pin:
   schema reds (missing/mistyped fields, unknown commit action), the
   raw-log write refusal, the unverified-outcome write refusal, the
   clean-attribution-failure admission, the three-phase read face
   (illegal phase refused), retrieved-uncited decay GREEN, max-revalue
   cap, prune-by-utility, both views deterministic + store-free,
   PE-pathology ≈ 0, unverified milestone ignored, settlement hook
   updates stats, existing-face mappings untouched
3. [ ] GREEN: `scripts/rlvr/episode_schema.py` — schema `episode/1`
   + summary caps + fail-closed validator
4. [ ] GREEN: `scripts/rlvr/episode_pool.py` — runs/episodes/ physical
   layer + write gate (trust × admission) + read face + update policy
5. [ ] GREEN: `scripts/rlvr/pool_indexer.py` — value table + playbook
   view (pure derived, deterministic, store-free)
6. [ ] GREEN: `scripts/rlvr/reward_signal.py` — A1 signal + trust-gated
   milestones + settlement hook + per-fact audit-only declaration
7. [ ] registration: rlvr facade lines, scripts/README.md rows,
   tests/_tiers.py fast-tier entry
8. [ ] trio order: baselines emit FIRST, `deploy_manifest --write` LAST
9. [ ] targeted suites green (`-n 4`), local gates ALL-PASS, evidence +
   mint (reviewer kunglao-p1-824), then push + PR (no merge)
