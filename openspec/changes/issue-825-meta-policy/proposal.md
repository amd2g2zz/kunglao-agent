# issue-825-meta-policy — the unified RL model's P2 meta-policy rewire

## Why

P1 (#824) landed the contracts — episode schema, pool gates, derived
indexers, the A1 reward switch — with NO behavior change for existing
readers. P2 makes the meta-policy REAL: commit selection conditions on
the context-feature vector (the contextual successor of the
context-free family bandit), pool retrieval fires at the two decision
points (episode start + commit boundaries) and feeds the executor's
context, and the family bandit is DEMOTED to a cold-start prior — it
advises only until the pool has coverage, never a central dispatch
decision alone (#806 axis: the context-free family bandit's central
role is abolished).

## What Changes

1. **Context features from real sources (`rlvr/meta_context.py`)** —
   `assemble(ws)` builds the context-feature vector from the sources
   that already exist: `task_spec.yaml` (lane, dynamic-RE constraint,
   depth, verification method, model_selection family candidates),
   `evidence/die.json` + `evidence/apkid.json` (protection salients:
   detected packer / obfuscator / entropy class), and the #812
   capability facts (`runs/env-state.json` per_capability + the probe
   cache — READ-ONLY, a feature face never executes a probe).
   Deterministic: deduped, sorted, capped at the episode schema limits
   (16 tokens, 64 chars each). Absent sources degrade honestly
   (no token — absence is not a feature).
2. **Context-conditional commit selection (`rlvr/meta_policy.py`)** —
   `select_commit(ws, features, ...)` reads the P1 value table
   (`pool_indexer.value_table`) and scores the six-commit vocabulary:
   overlap-weighted empirical score (W_REWARD · mean_reward −
   W_COST · mean_cost), n-shrinkage toward the cold-start prior. THE
   PRIOR (`cold_start_prior`) is the ONLY place the meta path consults
   the family bandit (`q_cells.fold().family_mass` — the shrunk family
   posterior mean) plus exogenous feature shifts (dynamic-RE forbidden
   / dynamic capability fail). Grep-verifiable demotion: no dispatch
   face consults the bandit alone.
3. **Pool retrieval at the decision points (`rlvr/meta_retrieval.py`)** —
   `assemble(ws, features, phase)` wraps the P1 read face at the legal
   phases (episode_start / commit_boundary / blocked): utility-score
   ranked (knob b weights), threshold-filtered, capped by the context
   budget; the playbook view rides alongside (feature-intersection
   matched). `envelope_block(ws, claim, phase)` = the SINGLE dispatch
   interface (schema `meta-policy/1`: commit + context + budget) and
   `render_block` its prompt-side text face (marker
   KUNGLAO_META_POLICY). Wired into `dispatch_context.
   build_dispatch_context` as an optional fail-open block (the
   providers/tool_tiers/instrument_menu pattern) — episode-start
   retrieval rides EVERY dispatch.
4. **The three learnable knobs (only these)** — (a) value-table
   weights (W_REWARD / W_COST / W_PRIOR / N_SHRINK); (b) utility-score
   weights (W_CITATION / W_RETRIEVAL); (c) retrieval threshold/count
   (RETRIEVE_MAX / MIN_UTILITY — the context budget). Env-configurable
   with documented defaults; nothing fitted at runtime.
5. **Utility chain measurement** — the tracked chain retrieved →
   cited → outcome-improved: `stamp_retrieved` records the episode-
   start case ids on the episode; `record_citation` stamps `cited`
   case ids on a commit entry (additive optional fields the episode/1
   validator tolerates); `utility_chain(doc)` reports
   {retrieved, cited, cited_from_retrieved, improved}.
6. **Component-ablation hooks** — KUNGLAO_META_RETRIEVAL=0 removes the
   retrieval component (cases/playbook empty, budget still reported);
   KUNGLAO_META_VALUE_TABLE=0 removes the value table (selection rides
   the prior; pool-different contexts no longer change the choice).

## Constraints honored (A1–A5)

- **A2 single-model law**: the value table and playbook are the P1
  derived views — no new store, no parallel statistics face.
- **A3**: the pool thickens → the value table sharpens → selection
  shifts (the growth loop is wired, pinned by the 17/17 pin).
- **A4**: only settlement-stamped (reward.r) episodes feed the table
  (P1 honest-gap rule, unchanged); the trust spine is only ever
  CALLED.
- **A5**: zero new human decision points.
- No touch: settlement/verifier semantics (called read-only via the
  P1 faces), #818 in-flight tests (new tests only in my pin file),
  #816 corpus (another agent), claims_store/scalar semantics.

## Impact

- commits: feat: the meta-policy rewire — context-conditional commit
  selection, pool retrieval at the decision points, the bandit demoted
  to cold-start prior (issue 825)
- tests: tests/test_meta_policy_825.py (synthetic fixtures: the 17/17
  same-family-different-context pin, both-phase retrieval visibility,
  single-interface envelope, ablation switches, bandit-demotion grep
  pin, utility chain, feature sources)
- registration: rlvr facade lines + scripts/README.md rows +
  tests/_tiers.py fast-tier entry; baselines emitted FIRST,
  `deploy_manifest --write` LAST (the dispatch_context import of the
  rlvr meta modules pulls them into the deploy closure — the manifest
  MUST be regenerated at the final tip)
