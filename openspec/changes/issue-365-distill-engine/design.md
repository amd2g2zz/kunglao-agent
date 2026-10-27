# Design — issue-365-distill-engine

References: #365 binding rulings (2026-09-23, verbatim in the issue), the
#806 axis axioms A1-A5, the merged P1-P3 faces (rlvr/episode_schema,
episode_pool, pool_indexer, reward_signal, meta_policy, meta_retrieval,
playbook).

## D1 — The item is a pool episode, not a second store (A2)

A StandardDistillItem is an `episode/1` pool document carrying an ADDITIVE
`distill` block (episode/1 tolerates additive keys — the #825/
`stamp_retrieved` precedent). The claim id is `D-<slug>`; the item lands
through `episode_pool.write_episode` UNMODIFIED:

- trust wall: the item's `outcome.evidence_ref` points at its scorecard
  verification record (`runs/verification-<D-id>.md`, `verdict:
  verified`) minted ONLY when the scoring gate admits the item — the
  score IS the distillation act's verification, resolved through the
  unmodified `resolve_verification` spine (A4);
- admission: a scored-and-admitted item is a completed outcome (admits).

Rejections never touch the pool: a schema lint failure or a below-threshold
score leaves only the `distill-rollout/1` row (reward 0.01, reason kept) —
"an item that can't fill the schema doesn't exist" and a worthless attempt
is still settled (ruling 3).

Why not a `runs/distill-items/` store: A2 forbids parallel chains of
custody. In-pool, the item automatically rides the P1 read/update faces
(retrieval counters, decay, utility-ranked recall) and the playbook view's
admission spine (completed + trust-resolving) — the consumption surfaces
already exist.

## D2 — Scoring: mechanical spine, injected assessor (ruling 4)

`score_item(item, known_corpus, assessor=None)`:

- generality 0.3 — mechanical decision-rule lint: content rules surviving
  value-stripping = rules WITHOUT case-specific tokens (the #826
  `playbook.is_case_specific` refusal REUSED, not re-implemented);
- methodology-shape 0.25 — mechanical density: branch-table rows +
  verdict-algebra entries + pseudocode groups normalized against caps;
- novelty 0.2 — mechanical recall-delta: fragment-token overlap of the
  item vs the existing pool refs (top-k feature/fragment match), 1 − max
  overlap (a duplicate of an existing ref scores 0);
- self-inspiring 0.25 — model-judged via the INJECTED `assessor` callable
  (the dispatch-assessor seam: production passes the dispatch face, tests
  pass a stub). Without an assessor the mechanical unseen-class proxy
  applies and the recorded assessor identity is `mechanical-proxy` — the
  score block always names WHO judged each dimension (never a bare total).

Threshold: `SCORE_THRESHOLD = 0.6` (documented policy constant). Below →
abandon row. Per-dimension scores + total + assessor recorded on every
scoring, admitted or abandoned.

## D3 — The research loop is a meta-policy information-collection instance

The loop's per-round decision (continue-hypothesis / switch / abandon) is
the loop-level form of the commit vocabulary: persist (same hypothesis,
deeper query), switch (next hypothesis), and the barren-abandon wall. The
loop rides the `distill` orchestration action's budget family (#719) —
it is the KNOWLEDGE half of the action the #458 engine left tool-shaped.
Strategy differs ONLY at collection (ruling 1): after collection, both
strategies share clean → schema → score → write gate → rollout row.

SNR gate: a round is FERTILE when its results carry novel-hypothesis
increment (result tokens unseen in the known corpus: self sources + all
prior rounds); otherwise barren. Two CONSECUTIVE barren rounds → ABANDON
(with reason); ≤ MAX_ROUNDS hard cap; per-stage budget caps (rounds,
results per round) are policy constants.

Search action injection: the loop calls an injected `search(hypothesis)`
callable. Production wires the dispatch/search face; tests inject a mock.
The module itself performs NO network IO (grep-pinned by tests).

## D4 — Settlement bands (ruling: the graded spectrum)

`settle_consumption(item_id, consumed, helped, adverse, strength)` → band
+ reward:

| band | reward |
|---|---|
| consumed + helped | 0.5 + 0.5·strength ∈ [0.5, 1.0] |
| consumed + neutral | 0.1 + 0.4·strength ∈ [0.1, 0.5] |
| never consumed | 0.01 |
| adverse (misled + detour evidence) | 0.0 |

Adverse REQUIRES a detour-evidence reference (an empty-evidence adverse
claim is refused — the reward-0 face is evidence-gated). Rows carry
schema `distill-rollout/1`, append via `consolidated_ledger`
(settlement family — "how it closed"), emit `distill_rollout` events.
`strategy_priors` folds reward history by `source_strategy` — the
distillation STRATEGY itself gets optimized (same accounting family as
#341 rotation induction / Thompson rank).

## D5 — 3-strike = the utility-decay ladder, distilled-domain instance

`optimization_rounds` counts re-scores in the additive block; each round
re-scores through the SAME `score_item` face. A passing round re-admits
(strikes clear, lineage grows). Three exhausted rounds still below
threshold → `distill_removed {at, reason, strikes}` stamped on the pool
document:

- the playbook view and recall-context faces SKIP removed items (read-side
  composition over the P1 views — CALLED not modified);
- the file STAYS on disk; the rollout history stays in the ledger — the
  lesson lives in accounts, not on shelves (ruling 5).

## D6 — Conflicts: flags, never silent overwrites

Before landing, `flag_conflicts` computes recall top-k similarity against
existing pool items (fragment-token overlap). A similarity ≥
CONFLICT_SIMILARITY item MUST declare `lineage.supersedes` (explicit) or
the landing is refused as a would-be silent overwrite (flagged, never
resolved). The lineage wall: an `external-derived` item can never
supersede an `evidence-derived` one (epistemic classes are ranked;
superseding may only move DOWN the trust ranking, never up).

## D7 — D-gate: the three-question lint feeds the self pipeline

`lint_note(text)` mechanically requires the three sections (why-this-plan-
order / situation→next-action branches / hidden reasoning) present AND
non-trivial (per-section min length). `hybrid_distill --strategy self`
consumes only lint-passing notes (NOTES_DUE products) — self-distill items
are born at runtime here, in the StandardDistillItem shape.

## D8 — Event-driven only (restraint ruling)

The mechanisms.yaml entry declares `trigger.type: event` (settlement event
class — rollup is when notes come due and self sources are freshest),
`cost_class: medium`, a cockpit_signal reading the rollout rows. No tick,
no cron, no wake-class beyond the declared vocabulary.
