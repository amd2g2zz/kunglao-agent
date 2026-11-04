# issue-826-attribution-playbook — the unified RL model's P3: attribution + tune/switch commits + playbook compression

## Why

P1 (#824) landed the contracts, P2 (#825) made the meta-policy a real
learner with contextual commit selection. P3 adds the senior-expert
capabilities that are LEARNED inside the one model (#806 axis):

- failures today carry at most a free-text `attribution` string — no
  feature-level account of WHY an episode failed, so the three-way
  persist/tune/switch decision has no evidence behind it;
- `tune` and `switch` exist as vocabulary but carry no semantics: no
  envelope fields, no required reason, and nothing prevents the 9x
  dead-path re-probe shape (blind same-class retry);
- successful episodes enter the pool but their reusable fragments are
  admitted raw by the P1 view — no compression rules, so case-specific
  noise can ride the executor's context;
- nothing handles SURPRISE (a verified outcome contradicting the value
  table's expectation): the update rule has no contradiction face.

## What Changes

1. **Attribution model, learned (`rlvr/attribution.py`)** — context ->
   outcome feature importance computed as deterministic statistics over
   the P1 pool at call time (per-feature failure contrast + presence
   lift; pure stdlib counting, no fitted parameters, no model calls,
   no storage). Two faces: METHOD attribution
   (hypothesis_wrong / tool_mismatch / depth_insufficient — decided by
   the learned feature statistics plus the episode's own evidence
   signals, deterministic precedence) and ENVIRONMENT-NOISE features
   (exogenous: features with no outcome contrast are demoted to prior
   INPUT, never named as causes — the #421 demotion). Output =
   attribution report (schema `attribution-report/1`) with a stable
   digest ref. Synthetic fixtures distinguish a tool-missing failure
   from a hypothesis-wrong failure — NOT a binary accident/failure
   flag.
2. **The tune/switch commits, real semantics (`rlvr/commit_semantics.py`)**
   — `validate_tune_commit`: tune = SAME class + a non-empty
   parameter/tool delta (`param_changes` / `tool_changes` additive
   commit fields the episode/1 validator tolerates); `validate_switch_commit`:
   switch = a DIFFERENT class (`to_class`) + a REQUIRED attribution
   reference (`attribution_ref`) — a blind lane change is RED
   (CommitError). The dead-path gate: `validate_commit_history` refuses
   the 9x same-class re-probe shape (DEAD_PATH_CAP consecutive
   same-class attempts without an intervening tune/switch). The
   envelope carries the fields: `enrich_block` additively decorates the
   P2 meta-policy block's `commit` entry with the attribution evidence
   (switch) / the tune delta contract (tune) / the dead-path reading —
   the P2 faces keep their semantics (extension, not rewrite; on
   conflict both survive).
3. **Playbook compression (`rlvr/playbook.py`)** — the P1 playbook view
   (`pool_indexer.playbook_view`, called not modified) is the admission
   spine; compression applies the distillation quality axioms:
   case-specific fragments (claim ids / fact ids / long hex digests /
   artifact paths) are REFUSED; self-starting fragments (verb-bearing
   method summaries) are kept; cross-episode support ranks what rides
   the capped context (generalization preference). The output is a
   DERIVED view (no store); injection goes through the P2 retrieval
   face (`meta_retrieval.assemble` — the `playbook` key now serves the
   compressed view; the P1 view face itself is untouched).
4. **Self-correction loop (`rlvr/commit_semantics.py`)** — surprise =
   a verified outcome contradicting the value table's expectation for
   the committed class (completed while the cell's mean reward is
   negative, or failed while positive). `surprise_check` detects it;
   `reexamination_block` produces the forced re-examination commit
   payload (the update rule's contradiction face) that rides the
   envelope.
5. **Component ablation, four knobs** — P2's retrieval + value_table
   switches plus `KUNGLAO_META_ATTRIBUTION=0` (no attribution evidence
   on tune/switch commits) and `KUNGLAO_META_PLAYBOOK=0` (no playbook
   groups ride the context). `price_ablations` reports each knob's
   output-terms price (what disappears from the envelope when the
   component is removed).

## Impact

- Products: `scripts/rlvr/attribution.py`,
  `scripts/rlvr/commit_semantics.py`, `scripts/rlvr/playbook.py`
  (new); `scripts/rlvr/meta_policy.py` (additive: two knob keys,
  envelope enrichment call, render lines);
  `scripts/rlvr/meta_retrieval.py` (additive: compressed playbook
  injection + ablation switch).
- Constraints honored: settlement/verifier semantics only ever CALLED;
  eval corpus untouched; P2 meta-policy semantics preserved (the
  episode_start commit key-set pin stays exact); no new storage (all
  three products are deterministic faces over the P1 pool).
