# issue-792-ranker-determinism — tasks

1. [x] RED: `tests/test_ranker_determinism_792.py` — 11 pins across the
   five #792 designs + the R2 propensity pin (all failed on the live
   defect: round-moving fingerprints, unlinked noise outranking value,
   draw order inverting mean order, cold case != 0.5, missing slot
   constant, retired seed faces present, deviation propensity 0.0)
2. [x] RED: android production-shape fixture
   `devkit/production_shapes/android-2026-10-21-rank-shape.json`
   (synthetic; shape-only distillation: 272 rank_feeds / 111 entropy-0 /
   16 distinct rng_base / 8 deviations with 3 propensity-0.0)
3. [x] GREEN: `scripts/priority_ratio.py` — posterior-mean case value,
   unlinked demotion band, partition sort, exploration slot (default
   off), input-digest fingerprint (posterior_hash, rng_base null),
   seed-face retirement
4. [x] R2 resolution at merge: the #794 sampled-binds card (owner
   merged mid-flight) supersedes the drafted store floor — strategy_store
   stays dev-byte-identical; the R2 pin moves to the recorded-deviation
   face (in-support arm, propensity > 0) and the honest 0.0 out-of-support
   face #794's coherence gate consumes
5. [x] GREEN: callers — kunglao-decide, worker_budget_core,
   replay_ruler drop the seed; acceptance_check pins the new feeds key
   + honest zero bound; event_taxonomy rank_feeds description
6. [x] re-pin existing rank-face tests (13 files) + re-mint the
   `tests/test_action_space_12.py` frozen capture under the #792 face
7. [x] `specs/phase-4/contract.md` #792 revision block
8. [x] registration: no new scripts (README/ext-scan no-op, ext-scan
   regenerated zero-diff); `deploy_manifest.py --write` LAST
9. [x] ruff clean on all touched files; targeted suites green; full
   pytest `-n 4` green; quality gates ALL-PASS
