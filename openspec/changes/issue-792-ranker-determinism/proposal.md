# issue-792-ranker-determinism — value = evidence; exploration = explicit

## Why

The #107 ranker's value face was noise-shaped. Production (live rank,
2026-10; android 2026-10-21 logs): five same-family tier-1 claims scored
0.61-1.07 and every number was empty — (1) the per-round seed
`random.Random(f"thompson/{base}/{cid}")` re-drew each claim every round,
so the order changed while no data changed; (2) unlinked claims drew a
Beta(1,1) as their PRIMARY value face, so unlinked-vs-unlinked ordering
was uniform noise and unlinked-vs-linked mixed incompatible scales. The
R2 acceptance addition adds the propensity face: 6/16 archive
`sample_deviation` rows recorded propensity=0.0 while a deviation
occurred — the executed arm's recorded draw probability was zero, so
every ITT/OPE consumer dividing by 1/p is undefined.

## What Changes

1. **Linked claims rank by posterior MEAN, not a draw** —
   `case_value = Σ αᵢ/(αᵢ+βᵢ)` over linked oracle-case posteriors
   (scripts/priority_ratio.py): deterministic given data, monotone in
   evidence, reading the SAME `runs/posteriors.yaml` store the strategy
   sampler consumes. A cold linked case folds the neutral 0.5 prior mean.
2. **Unlinked claims carry NO fabricated value** — the Beta(1,1)
   fallback is retired: case_value = 0.0, the claim is DEMOTED below
   every value-bearing claim by a partition sort, ordered within the
   band by the declared deterministic default (downstream_term, tier,
   worth), and its feeds say
   `unlinked — no value channel (arm oracle cases / set answers_question)`.
   The oracle-linkage gap becomes the visible actionable signal.
3. **Determinism from inputs, not a counter** — the #251 round-seed faces
   (`case_face_seed` / `posterior_rng` / `posterior_seed_state`) and the
   ranker's `rng` parameter are retired. Same (ledger, claims, weights)
   → byte-identical ranking ANY round. The rank_feeds fingerprint now
   carries `posterior_hash` (canonical cases payload) and
   `rng_base: null` (the #266 frozen-sampling detector reads new tails
   as the honest gap; the consumer stays for historical tails). The #718
   L1 planner fork is re-keyed from the rank-input digests so the
   planner face cannot reintroduce round-dependence.
4. **Exploration is a declared slot, not smuggled noise** —
   `EXPLORE_EVERY_N_ROUNDS` (module constant, default 0 = off): when
   enabled, every Nth round promotes the best unlinked/lowest-attempts
   claim and labels it `exploration_arm` in feeds; value scores are
   untouched (never conflated with the value column).
5. **R2 — deviation propensity coherence (merged with #794)** — the
   production 6/16 propensity-0.0 deviation rows are closed structurally
   by the sampled-binds card the owner merged mid-flight: an
   out-of-support declaration is a REJECT (never a recorded deviation),
   and a RECORDED deviation requires an `agent-reasoning:` line AND a
   propensity > 0 arm. This card keeps the store face honest (an
   out-of-support arm's draw probability stays exactly 0.0 — the number
   #794's coherence gate consumes) and pins the RECORDED face: every
   deviation that reaches the usage row / `sample_deviation` event
   declares an in-support arm and carries propensity > 0.

## Impact

- Affected: `scripts/priority_ratio.py` (value face, partition sort,
  exploration slot, fingerprint, seed-face retirement),
  `scripts/rlvr/strategy_store.py` (untouched at merge — the #794
  sampled-binds gate supersedes the floor approach this card first
  drafted; the store's honest 0.0 out-of-support face stays),
  `scripts/kunglao-decide.py` / `hooks/worker_budget_core.py` /
  `scripts/replay_ruler.py` (callers drop the seed), 
  `scripts/acceptance_check.py` (feeds key + honest zero bound),
  `scripts/event_taxonomy.py` (rank_feeds description),
  `specs/phase-4/contract.md` (#792 revision block).
- Pins: NEW `tests/test_ranker_determinism_792.py` (cross-round
  byte-identity, unlinked demotion, mean monotonicity, exploration
  slot, fingerprint, R2 propensity), re-minted frozen capture in
  `tests/test_action_space_12.py`, updated rank-face pins across
  `tests/test_priority_ratio.py` (+13 files). The determinism fixture
  is the SYNTHETIC android production-shape distillation
  `devkit/production_shapes/android-2026-10-21-rank-shape.json`
  (shape-only; raw logs never enter the repo).
- Kept intact: the #295 ΔH removal (no dh_pq face), the candidate
  filter, the #759 worth channel, the #294 downstream term, the #157
  one-emit-per-run contract, the real Thompson sampler
  (`q_cells.sample_method_family` — untouched), #794/#797 surfaces
  (no supply/claims-birth or key/fingerprint changes).
