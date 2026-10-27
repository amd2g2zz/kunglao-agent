# issue-365-distill-engine — the unified model's distillation domain

## Why

Owner-directed design, converged 2026-09-23 (rulings verbatim in issue
#365). Distillation today is ad-hoc: the offline waves (#358/#364) and the
online TOOL engine (#458 — tool acquisition, a different grain) leave
KNOWLEDGE distillation with no standardized product, no 0-1 quality bar, no
settled reward, and no lifecycle. Per the five-party review (#806) and the
A2 single-model law, the engine must be a DOMAIN INSTANCE of the unified
RL model (P1-P3 already merged: episode_pool / pool_indexer /
reward_signal / meta_policy) — not a parallel system.

## What Changes

1. **StandardDistillItem (`scripts/distill_schema.py`)** — schema
   `distill-item/1`: the pool episode schema's distillation-domain
   instance. A dataclass + JSON schema + lint over the ADDITIVE `distill`
   block an `episode/1` pool episode carries (`source_strategy` self|hybrid,
   `source_refs`, `collection_ts`, `content` methodology skeleton
   {branch_table, verdict_algebra, pseudocode_groups}, `scoring` block
   {4 dims + total + assessor}, `epistemic_class`
   evidence-derived|community-claim|external-derived, `lineage` supersedes
   chain, `optimization_rounds`). Items RIDE the P1 pool write/read faces
   (`episode_pool.write_episode` — the same trust wall + admission; no new
   storage). An item that can't fill the schema doesn't exist.
2. **0-1 scoring (`scripts/rlvr/distill_score.py`)** — four weighted
   dimensions: generality 0.3 (decision rules surviving value-stripping —
   mechanical lint reusing the #826 case-specific refusal), self-inspiring
   0.25 (new hypotheses for unseen classes — model-judged via an injected
   assessor with the rubric, mechanical unseen-class proxy as the labeled
   fallback), methodology-shape 0.25 (branch-table/algebra density —
   mechanical), novelty 0.2 (recall-delta vs existing pool refs —
   mechanical). Per-dimension scores ALWAYS recorded (never a bare total).
   Below threshold → abandon (reward 0.01 row, reason kept). Scoring
   results enter the playbook view: the P1 view CALLED not modified, with
   the P3 leftover closed — score-aware fragment ordering (support-ranked
   fragments ordered by their source item's total score).
3. **distill_rollout settlement (`scripts/rlvr/distill_rollout.py`)** —
   the reward_signal domain's distillation extension: schema
   `distill-rollout/1` rows in the consolidated settlement family +
   the `distill_rollout` word in event_taxonomy.EMIT_ACTIONS. Reward
   bands (issue lineage): consumed+helped 0.5-1.0 / consumed-neutral
   0.1-0.5 / never-consumed 0.01 / adverse (misled + detour evidence) 0.
   Reward history feeds strategy priors (same accounting family as #341).
4. **Hybrid research loop (`tools/auxiliary/hybrid_distill.py`)** —
   `--strategy hybrid` = self sources ⊕ a network-search ACTION shaped as
   a research LOOP: hypothesis → search → SNR gate (novel-hypothesis
   increment) → next hypothesis (≤ MAX_ROUNDS) → converged = proceed /
   2 consecutive barren rounds = ABANDON. `--strategy self` = the same
   pipeline, no search (sources: D-gate-passing notes, facts, lessons,
   env-state). The search action is INJECTABLE (tests inject a mock — no
   real network). Budget caps per stage. mechanisms.yaml entry:
   event-driven trigger only (the restraint ruling lives as the trigger
   type), cost class, cockpit_signal.
5. **3-strike optimize-then-remove (`scripts/rlvr/distill_lifecycle.py`)** —
   the P1 update policy's utility decay, instanced in the distillation
   domain: up to 3 optimization rounds (retrigger description / recontent /
   recoverage), each re-scored; all 3 exhausted still low → REMOVAL from
   the library surfaces (playbook view + recall contexts skip
   `distill_removed` items — read-side composition, the P1 faces stay
   unmodified); rollout history ARCHIVES to the ledger (the file stays on
   disk — the lesson lives in accounts, not on shelves).
6. **D-gate (`scripts/rlvr/distill_dgate.py`)** — the NOTES_DUE chain
   extension: a note passes only if it answers the three questions (why
   this plan order / situation→next-action branches / hidden reasoning).
   Mechanical lint (three sections present + non-trivial). The
   StandardDistillItem schema is the target shape — self-distill items are
   born here at runtime (D-gate-passing notes are self sources).
7. **Conflict face** — recall top-k similarity flags; never a silent
   overwrite (a superseding item MUST declare `lineage.supersedes`);
   external-derived never overrides evidence-derived (the lineage wall).

## Constraints honored (the #365 binding rulings + A1-A5)

- Two collection strategies, ONE pipeline (ruling 1): strategy differs
  only at collection; clean→schema→score→settle is shared code.
- Research LOOP, not one-shot (ruling 2): the SNR gate + barren-abandon
  are the loop's walls; a one-shot search cannot pass.
- Distillation IS a rollout (ruling 3): worthless attempts are settled
  (0.01), never silently dropped.
- A2 single-model law: items live IN the pool (runs/episodes/), through
  the P1 write gate; no new store, no second schema chain of custody.
- A3: scoring enters the playbook view as a derived-view sharpening.
- A4: the trust spine (`verifier_integrity.resolve_verification`) is
  CALLED, never modified — an item's scorecard verification record rides
  the canonical surface; settlement/verifier semantics untouched.
- A5: zero new human decision points.
- Restraint ruling (2026-09-28 lineage): mechanisms.yaml entry is
  event-triggered ONLY; no tick, no cron.
- No touch: settlement/verifier semantics (called only), #818 climbing
  tests, #846/#847 surfaces, the #458 tool engine (different grain).

## Impact

- commits: feat: the distillation engine — StandardDistillItem schema,
  0-1 scoring, rollout settlement, hybrid research loop, 3-strike
  lifecycle (issue 365)
- tests: tests/test_distill_schema_365.py, test_distill_score_365.py,
  test_distill_rollout_365.py, test_distill_lifecycle_365.py,
  test_distill_dgate_365.py, test_hybrid_distill_365.py (synthetic
  workspaces; the hybrid search action is a MOCK — no real network)
- registration: scripts/README.md rows + scripts/rlvr/README.md +
  rlvr facade; tools/_index-auxiliary.md + tools/_INDEX.yaml +
  ext index baseline FIRST, deploy-manifest --write LAST
