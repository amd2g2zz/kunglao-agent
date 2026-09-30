# Proposal — issue-461-option-death (Phase 2)

## Why (a NEW change, not an extension — documented choice)

Issue 461 Phase 2: Bayesian option-death termination for method
families — the learned "when to quit". The owner ruling (2026-09-30):
termination is a learned posterior INSIDE the option (Option-Critic:
β(s) is a termination function of the option, not a sibling arm in a
flat action space), attribution-in-state is the discriminator, and NO
rules or gates are added — behavior emerges from state + termination +
outcome correlation. Phase 1 (PR #471) landed the substrate this
consumes: the obstacle/1 attribution registry (`runs/obstacles/`,
`scripts/rlvr/obstacles.py`), the ob= signature segment (state-sig/2),
the worker intervention protocol, and the EX-4 trap fixture. #462
(PR #466) landed the runtime fold (settlement → observe); #460-B
(PR #475) landed the feature-prior seam pattern this change mirrors.

OpenSpec choice: a NEW change `issue-461-option-death` rather than
extending `issue-461-attribution-state`, because a change is one
reviewable unit — Phase 1 is merged and archivable on its own; folding
Phase-2 deltas into it would couple two PRs' archive steps and blur
the requirement-to-test mapping. Same convention the sibling pair
issue-460-feature-mining / issue-460-predict-before-try follows
(Part A and Part B as separate changes).

## What changes

1. **`scripts/rlvr/termination.py`** (new): the option-death estimator
   — a DERIVED, deterministic, ts-free receipt over two pure reads:
   death evidence from the obstacle registry (one obstacle row = one
   attributed failure = one death observation for its (kind,
   method_family) cell), alive evidence from the q-cell fold (the
   family's γ-discounted success mass). Posterior: Beta(α, β) per
   (obstacle-kind, method_family) cell — the ob= signature segment
   DECOMPOSED into its component kinds, NOT the full signature hash
   (ob= is cumulative, so exact-hash keys fragment and repetition can
   never accumulate; the closed 5-kind enum keeps the key space
   bounded). Decision face `option_dead(ws, family)` / `verdicts(...)`:
   dead iff any kind present in the CURRENT signature carries a cell
   with posterior mean ≥ DEATH_THRESHOLD (0.75, policy constant).
   Cause-free failures contribute NOTHING (no obstacle row → no death
   observation) — they remain the attribution protocol's feed.
2. **Sampler wiring (floor-not-delete)**: `q_cells.sample_method_family`
   gains an optional duck-typed `death` mapping ({family → verdict});
   a dead family's sampling weight is multiplied by ARM_FLOOR (0.1) —
   floored, never zeroed, so the option stays in the action space and
   is REVIVABLE when new alive evidence drops the posterior below
   threshold (the PARK pattern: suspension, not terminal). BOTH
   production sampler hosts thread the verdicts fail-open (any
   failure → no kwarg → the pre-change draw):
   `strategy_store.method_lead` (the advisory compose lead) AND
   `scripts/e2e/checkpoints._sample_envelope_family` (the #462 W4
   envelope sampler — the action-selection site banked into the q-cell
   log at the ALLOW tail; missing it would leave the mechanism an
   advisory prompt line). The sampler module itself never imports
   termination/obstacles — the verdict mapping is duck-typed, keeping
   the import-direction wall. Zero-registry workspaces get NO kwarg at
   all (receipts byte-identical day one).
3. **EX-6 `experiments/ex6_option_death.py`**: the declared-synthetic
   MC replay A/B the issue's acceptance names — attribution-in-state +
   learned termination (arm B) vs current decay-only (arm A) vs a
   cause-free control (arm C: termination consulted, attribution
   skipped — must stay all-alive) on the owner's five-step trap
   trajectory (EX-4's registered-family truth table). Dead families'
   repeated ATTRIBUTED failures drive their posteriors over threshold
   and out of the sampling mass; the breakthrough family
   (crypto-core-identification) stays alive and is reached; arm C
   never terminates anything. Deterministic, committed results.
4. **Registration**: rlvr `__init__` export map, scripts/README.md +
   scripts/rlvr/README.md rows, tests/_tiers.py fast set, deploy
   manifest re-mint.

## Non-goals (phase boundary)

- NO gates, NO rules, NO verdict-face enforcement: nothing rejects a
  dispatch, a settlement, or a cause-free failure. Termination moves a
  sampling weight to a floor — that is its entire actuation surface.
  The Phase-1 attribution-state spec's recording-only clause is
  AMENDED in its still-open change to license exactly this one
  consumption face (reject/block/gate stays barred forever);
  `rlvr.obstacles` code is untouched except a one-line docstring note
  that the Phase-2 consumer exists.
- NO new persistent store: the estimator is a pure fold over the
  obstacle registry + q-cell log (no second data spine, no dual-write
  hazard). The receipt document is deterministic (no wall clock).
- NO change to `rlvr.state` (signature/v-anchor frozen at state-sig/2),
  the posterior store, or the settlement faces. The 396 freeze wall
  pins stay untouched (strategy_store/compose/q_cells/checkpoints are
  not pinned faces — verified); the budget forced-closure stays the
  safety bound, orthogonal and unchanged.
- NO cross-workspace pooling: posteriors are workspace-lifetime
  (registry + q-cell log of ONE ws); sharing via the #460 feature
  table is the named v0.2 seam.
- NO activation flag: unlike #460-B (which reweights every cold-start
  sample and therefore shipped flag-off pending its A/B), termination
  is evidence-gated — a zero-registry workspace threads no kwarg at
  all (receipts byte-identical), and a workspace with fewer than two
  attributed same-cause failures per family draws byte-identically
  (all-alive multipliers are IEEE-exact × 1.0). Day-one workspaces
  cannot actuate it; EX-6 ships in the same change.
