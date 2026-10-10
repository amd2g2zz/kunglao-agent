# Cross-Workspace Method Memory — the keyed fold promoted user-level, plus the Claude-Code-memory distillation bridge

Status: design draft — implementation gated on owner sign-off (this PR is the sign-off instrument; the owner decisions are §8)
Issue: #583
Milestone: v0.2
Date: 2026-10-09
Intersects: the v0.2 reflective-mutation four-layer design (memory layer); #582 (the refutation fold, landed), #584 (fact uncertainty fields, landed), #586 (timeline v2, landed)

## 0. Scope and invariants

- **Design only.** This card ships a document, not code. Every mechanism below lands through an EXISTING face or is explicitly listed as new in §8 with its owner decision; nothing here is implemented before the owner signs §8 line-by-line.
- **No new mechanism classes.** L3/L4 reuse the three substrate patterns the repo already runs: append-only JSONL write log, folding read face, feature-keyed pools. The promotion is a *location + admission* change; the bridge is a *producer* for an existing consumer; consolidation is a *fold discipline*, not a new store.
- **Hyperparameter discipline** (closeout-plan §4, state.py precedent): at most 3 new constants across the whole design, all declared policy constants — the engagement-age half-life (§2.4), the entry size cap (§5), and the dedupe index token budget (§4.1). Nothing fitted, nothing tuned at runtime.
- **No new background rhythm.** The distillation-frequency restraint (owner ruling, recorded with the #478 spine) holds: the bridge rides the existing `distill-online` / `distill-hybrid` action faces and their budget ledger (`scripts/online_distill.py` — per-run act caps + workspace-lifetime counters). It never adds a cron, a tick, or a "distill when idle" heuristic.
- **No-backcompat policy** (owner ruling 2026-09-01): the store promotion gets no dual-read era and no compat shim. The store is append-only JSONL; the migration is a one-shot copy + re-derive, and old deployment-local stores that are not migrated simply stop being read.

## 1. The five-layer framing (owner thesis, with the code mapping)

The owner's validated thesis places every memory-adjacent concern on one ladder; this card is the home of layers 3-4. The mapping matters because each layer's *contract* is set by the layer below it, and the granularity red line in L5 is what keeps L3/L4 honest.

| Layer | Contract | Home | Status |
|---|---|---|---|
| L1 structured evidence & hypothesis | every number traceable to raw evidence | fact contract (`scripts/lint_facts.py`, `templates/fact-frontmatter.md`); per-fact uncertainty + next-probe fields (#584, `scripts/hypothesis_view.py`) | landed |
| L2 reproducible event logs & checkpoints | replay from the event stream, never hand-written | `runs/` audit, `transitions.jsonl`, timeline v2 (#586: `scripts/timeline_face.py`, `scripts/progress_timeline.py`), dual DAG (`scripts/evidence_dag.py`), promotion write-back (`scripts/fact_status_sync.py`) | landed |
| **L3 transferable procedural memory** | method-family posteriors keyed by feature signature, shared across workspaces and deployments | the keyed fold — §2 of this card | **this card** |
| **L4 retrieval / consolidation / promotion / forgetting** | provenance preservation is the hard constraint; forgetting is bounded (PARK downweight, never delete) | the reconcile pipeline — §3, the gates — §5 | **this card** |
| L5 RLVR policy on top | the policy **schedules** experiments, retrieval, and verification; it **never writes hypothesis content** | `hooks/lib_kunglao.py` ACTION_TYPES (dispatch / verify / recall-history / distill-online / distill-hybrid / replan / rollback / stop / expand), CONTEXT_RECIPES (`facts_anti_hints` among them), `scripts/action_space.py` (18 actions) | existing action faces |

**Why the red line is load-bearing.** L5's granularity ruling — scheduling is the policy's, content is the frozen LLM's within acts — means the memory system's writes must be mechanically derivable from settled evidence (transitions, verify credits, oracle outcomes) or gated distillations (§3), never a policy-side "belief edit". A policy that could write hypothesis content would be a critic by another name, and critics are ruled out (closeout-plan §4: no critic / value estimator / actor at this data scale). Every write face below is therefore either a settlement hook (as today, the e2e settlement path in `scripts/e2e/checkpoints.py`) or the gated bridge read of prose (§3) — there is no third path and this card adds none.

**Why L4's hard constraint is provenance preservation.** A consolidated prior that lost its evidence chain is an unauditable number — it violates the every-number-traceable foundation that L1 enforces for facts and #586's projection enforces for events. Practically: every folded entry in §4 carries its source row ids, and supersession is recorded rather than applied in place. Forgetting stays the bounded form: the #634 PARK semantics ("the opportunity pauses, it is not lost", `scripts/exogenous.py`) generalize to memory — mass decays in the fold, rows are never deleted.

## 2. The promotion — the WS2 keyed fold goes user-level

### 2.1 What exists today

The cross-task posterior store (#545, WS2) is `scripts/rlvr/strategy_store.py`: append-only `posterior-store/1` JSONL, keyed `(method_family, arm_key, feature_key, fingerprint)`, rooted at `scripts/rlvr/patterns/` (env override `KUNGLAO_POSTERIOR_STORE`). Its guard set is already the right one:

- **Feature-keyed, never identity-keyed** (#518 rule): `feature_key_of()` = SHA-256 over the sorted mined feature tokens (`scripts/rlvr/feature_prior.py`, #460-B), fail-open to the inert `"none"`.
- **Holdout firewall**: `append_row()` refuses any row whose serialized form carries a holdout unit id from `eval/v1/split.yaml` (read-only — the never-write wall), and `scripts/eval_split_lint.py` re-checks the file as the second gate.
- **Read admission**: `warm_pools()` contributes other workspaces' settled rows as LAMBDA-tempered anchor mass (`meta_arms.LAMBDA = 0.25`, power-prior) through `q_cells.cell_posterior(warm_pool=...)` — never a local-cell write; `load_rows(ws)` is leave-one-out (a workspace never warm-starts from its own rows).

### 2.2 Why promote at all

The store is **deployment-local**: it lives inside one repo checkout, so its hard-won method-family experience does not survive a clone, a worktree rotation, a VM redeploy, or the multi-machine reality of the public-canonical repo. The refutation fold (#582, `scripts/rlvr/refutation_fold.py`) already demonstrates the value of the cross-engagement read — a second workspace with the same feature signature inherits the raised verification density — but its substrate is trapped in the same deployment. The lessons library (`scripts/failure_analysis_gate.py`, #495) is the existence proof for the fix: it is already **global, cross-sample, never per-workspace**, rooted at `~/.claude/skills/kunglao-agent/references/lessons/`. Method memory deserves the same lifetime.

### 2.3 The promotion mechanics

- **New root**: a user-level memory root, recommended `~/.kunglao/memory/` (env override `KUNGLAO_MEMORY_STORE`, same override pattern as `KUNGLAO_POSTERIOR_STORE`). Precedents: `LESSONS_DIR_DEFAULT` (global prose, user-level, shipped), `~/.kunglao/samples/` (user-level bytes, #358 lineage). The deployment-local path stays as a *fallback read seed* only if the owner prefers a soft landing — see D1.
- **Same row schema** (`posterior-store/1`), same write face (the settlement hook), same fold faces (`warm_pools`, the refutation fold). A promoted row is byte-identical to today's row; only `store_root()` changes. This is why the promotion is cheap: every consumer already reads through the fold, nobody reads the file path directly.
- **Ownership**: the store is *user* data with *repo-defined* schema — the repo owns the schema and the gates, the user-level directory owns the rows. The repo never writes outside the memory root; the memory root never holds code.

### 2.4 Decay across engagement ages

Within one engagement, the DTS discount (`scripts/rlvr/posteriors.py` — γ decay as a fold/read-face property, raw counts never rewritten) already handles recency. What it does not express: a method that worked months ago on a stale toolchain should lose authority even if it was never refuted — the world moved, not the evidence.

The design adds exactly one mechanism: an **engagement-age multiplier applied in the fold** at read time. Each store row already carries `ts`; the fold computes the age of the row's engagement relative to now and discounts its mass by a bounded schedule with one new policy constant (the half-life, D3). Properties:

- **Fold-only, never rewrite** — the house pattern (`posteriors.py` γ discipline, `refutation_fold.py` FOLD_GAMMA decay guard, `prediction_ledger.py` expired-flips-on-read). Raw rows are untouched; a fresh engagement of the same signature re-derives full authority by contributing new rows.
- **Evidence-based, not manual** — a stale method loses weight because newer observations exist or because the schedule ages it, never because someone pruned it. The loser stays traceable (§4.3).
- **Bounded, not zero** — the multiplier floors above 0: aged evidence stays PARK-able prior art for retrieval (the #495 method-ladder's first rung reads lessons regardless of age), it just stops anchoring the sampler at full strength.

## 3. The distillation bridge — prose substrate to keyed priors

### 3.1 The honest answer that motivates it

Today the policy runs on its own ledger substrate and does not read Claude-Code-native memory — deliberate, because RL needs keyed tables and CC memory is outer-harness prose. But that prose accumulates real method knowledge (case reports, lesson notes, the field-journal family) that the keyed store never sees. The bridge is the one-way converter: **the journal is the SOURCE, the keyed fold is the INDEX.** Retrieval stays feature-keyed (§8 rejects the keyword-index alternative); the prose stays greppable, replayable, and human-auditable.

### 3.2 The entry contract (field-journal shape, adopted from the owner's reference pack)

A journal entry is a dated, template-contracted markdown document with fixed sections:

1. scenario category / goal / scope (anonymized — no sample identity beyond what the feature tokens already carry);
2. **execution chain including dead ends** — matches the dead-ends rule the timeline already enforces (#586: failure and timeout entries cite bounded gap evidence);
3. pitfalls / toolchain findings;
4. **reusable pattern** — the field that carries the distillation axiom in prose form: if there is no reusable pattern, there is no promotion (generalization + self-start only; case-specific entries are rejected whole, per the quality bar);
5. evolution actions.

**Provenance-validated rows**: every evidence row inside an entry must satisfy the same mechanical field contract as case evidence (severity / status / repro command / content hash / artifact path), checkable by the lint faces (`scripts/lint_facts.py` lineage; the reference pack validates with a review script in strict mode — ours is the existing fact/evidence lint, extended with a journal mode). This is "consolidated memory keeps provenance" made mechanical: prose memory carries machine-checkable evidence links or it does not promote.

### 3.3 The pipeline

```
journal entries --intake gates (5)--> distill_spine T-pass --> products --> keyed fold
 (prose, user-level)   quality bar     de_case -> promote_form   priors /     warm_pools,
                       gates decide    -> tag -> verify -> dedup  anti-hints   feature_pool,
                       unattended      (#478, the ONE pass)                    anti_hints recipe
```

- **Through the ONE spine** (`scripts/distill_spine.py`, #478): `de_case` strips case-specifics (the axiom enforced as a stage, not a hope), `tag` adds feature tokens via the #460-B projection, `verify` checks against the evidence rows, `dedup` folds near-duplicates. Stage order is fixed (`SpineOrderError`); a product that skips a stage is a contract violation. Landing goes through the ONE landing face (the #474 tier-1 path) — the bridge mints no second landing.
- **Products are two, both existing consumers**: (a) **feature-keyed priors** — Beta-style mass onto family pools, entering the sampler through the exact faces cross-task mass uses today (`warm_pools` anchor, `feature_pool` similarity-discounted — `scripts/rlvr/q_cells.py`); (b) **anti-hint entries** — string-list rows for the `facts_anti_hints` context recipe (`scripts/rlvr/compose.py` validates `dispatch.anti_hints` as a string list today). Both are *reads* by the policy, never prompt writes — the L5 red line holds at the bridge's exit.
- **Frequency restraint** (owner ruling): the bridge fires inside the existing `distill-online` / `distill-hybrid` action faces' budget ledger (`scripts/online_distill.py` — per-run act caps, hop caps, flock-guarded workspace-lifetime counters). No new cadence, no background sweep. If nothing triggers a distillation act, the journal waits.
- **Unattended and quality-gated** — a deliberate divergence from the reference pack's human-in-the-loop promotion (§8.3): the distillation axioms plus the intake gates decide; the owner audits via the audit lines (§4.3) after the fact.

## 4. Consolidation and update as first-class (owner refinement)

**The bridge is a reconcile pipeline, not an append.** An append-only accretion of stale, duplicate, or contradictory priors is retrieval noise wearing a memory badge. The house pattern to follow is the append-only write log + folding read face — history is never rewritten; consolidation lives in the fold; everything is replayable. Precedents: `prediction_ledger.py`'s latest-per-id fold (status flips on read, history intact), `posteriors.py`'s γ fold, `refutation_fold.py`'s per-signature fold.

### 4.1 Dedupe by token-set

Candidate entries project to canonical token sets (the #460-B `feature_tokens` discipline — string equality, order-independent, float-free); dedupe is Jaccard above a policy threshold, judged **before** promotion by a bounded index read (the ~200-token pre-check, §5's size discipline). N similar observations fold into one canonical entry with all N source ids retained. This is `index-dedupe-on-write` from the reference pack, mapped onto the existing similarity machinery — no new embedding layer, no fuzzy identity join.

### 4.2 Contradiction resolution

When two folded entries conflict (method A helped here, hurt there), the fold resolves by **recency + evidence weight**: newer engagements discount older ones (§2.4's schedule), settled credits outweigh journal claims, oracle-settled evidence outweighs prose assertion. The rule is arithmetic over evidence in the fold — the same discipline as `refutation_fold.py`'s bounded multiplier — never a judge call.

### 4.3 Explicit supersession, on the record

What replaced what, and why, is an **audit line** on the surviving entry: `{supersedes: [source_ids], reason: <token-set summary>, ts}`. The superseded entry stays in the write log and traceable — its evidence rows remain valid even where its generalization lost. This is the memory analogue of `fact_status_sync.py`'s named-skip discipline (#586): every state change names what it did.

### 4.4 Re-derivation from the evidence log

When the underlying evidence changes (a verdict flips, a correction lands), the affected entries re-derive from the write log — the recompute face. This is possible *because* the store is a fold: replay the source rows through the pipeline and the consolidated view updates by construction (`posteriors.py`'s replay-in-input-order is the exact precedent). A method that worked on stale toolchains loses authority by evidence, not by manual pruning.

### 4.5 Provenance preservation (the hard constraint)

Every consolidated number carries its evidence chain: the fold's output exposes the contributing row ids, and a consolidated prior whose chain is broken does not enter the sampler (it degrades to prose prior art, retrievable but never anchoring). Forgetting stays bounded: mass decays, PARK semantics, never deletion.

## 5. Intake gates (anti-poisoning)

The promotion target is a trust boundary twice over: cross-workspace data flows in, and LLM-distilled prose is an adversarial surface (#582's line — the system that learns from text can be poisoned through text). The reference pack's community-PR gate maps to four checks on every promoting entry; all four run **fail-closed on write admission** (a gate failure blocks promotion loudly) while reads stay fail-open (house convention — a dirty store degrades, it never breaks settlement).

| Gate | Check | Existing face it extends |
|---|---|---|
| injection features | no prompt-injection patterns in entry prose (instruction-override phrasing, fake tool output, embedded envelopes) | the eval-misdirection lineage (`scripts/eval_misdirection.py`); the reserved `<case-hints>` contract in `references/contracts/xml-injection-standard.md` is the shape precedent |
| secret scanning | no unsanitized secrets in promoted prose (the journal anonymizes scope; the gate verifies) | `dispatch_context._redact_tokens` hygiene; the repo constraint "no secrets in the tree" |
| scope checks | the distiller writes ONLY the memory dir — the community-PR property "only the journal dir touched" as a write-face allowlist | the global-shelf-no-runtime-write-face rule (`scripts/online_distill.py`) |
| size caps | bounded entries (the one new constant, D5's neighbor); unbounded memory is retrieval noise by construction | `online_distill`'s hop caps and expansion caps |

**The eval-corpus exclusion rides the same gate class.** The held-out path contract (eval prefixes stay distiller-excluded) must survive the promotion: the holdout filter precedes the append exactly as `strategy_store.append_row()` does today, `scripts/eval_split_lint.py` stays the second gate over the user-level file, and the bridge's journal reader inherits the exclusion (a journal entry about a holdout unit does not promote). Belt and suspenders, unchanged, because the promotion must not weaken the firewall #518 built.

## 6. Cold start — same problem, two substrates, one coordination story

- **Prose layer**: seeded journal entries (the reference pack's 17-seed pattern) — day-one prior art so the bridge has source material and retrieval has something to return. Written by hand once, template-contracted like every other entry.
- **Policy layer**: WS3's intake seeding (`scripts/rlvr/priors.py`, `seed_intake_prior`, #544) — the frozen model's self-assessed family priors spread as weak Beta mass, skepticism-first (cap 0.5, never commits hard; a seed source is accepted or rejected whole — no partial credit).

**Coordination**: the two layers never cross. Policy-layer seeds are *not* distilled experience and must not enter the journal (they are model opinion, not evidence); journal seeds flow through the SAME bridge and the SAME intake gates as organic entries — the gates see a row field, not a privileged path. Both are bounded by construction: seeds never anchor at full strength, and the store's own experience displaces both as engagements accumulate. The failure mode this avoids is the seeding prior leaking authority past its skepticism cap — the #544 cap-0.5 ruling is the boundary.

## 7. Rejected alternatives, on record

1. **Project Ire's CFG-as-memory** (within-sample world-model reconstruction as the memory substrate). Rejected by the actor-model lineage ruling: the diagnosed memory defect was missing *actor objects* (price/ordering/knowledge absent from the decision surface), not missing control-flow structure. Reconstructing a per-sample CFG is a world model, and our memory stays **ledger + facts**. The keyed fold and the journal are the design; the CFG is not.
2. **Keyword-index retrieval** (the reference pack's face). Rejected: retrieval must condition on the same variables the policy conditions on — the feature signature (#518's rule, #460-B's token sets). A keyword index drifts from those variables, invites vocabulary games, and cannot enter `warm_pools`' Jaccard machinery without a second similarity layer. The journal is the SOURCE, the keyed fold is the INDEX; the prose stays greppable for humans, which is what keyword search was actually for.
3. **Human-in-the-loop promotion** (the reference pack asks the user before an entry promotes). Rejected for kunglao: unattended operation is the product, and a prompt-per-promotion gate re-introduces the park-and-bash trap at the memory layer. Ours is quality-gated and unattended — the distillation axioms + intake gates decide; the owner audits via audit lines and the replayable write log after the fact.

## 8. The design decisions for the owner (the sign-off list)

Each decision lists the recommendation, the tradeoff, and what breaks if chosen wrong. Implementation of §2-§5 starts only after these five are signed.

### D1 — Where the user-level store lives, and who owns it

**Recommendation**: `~/.kunglao/memory/posterior-store.jsonl` + `KUNGLAO_MEMORY_STORE` override; the repo owns schema and gates, the directory owns rows; deployment-local `scripts/rlvr/patterns/` is retired as a store root (one-shot copy to the new root; no dual-read era — the no-backcompat policy).
**Tradeoff**: user-level survives deploy rotation and shares across a user's machines, but it sits outside repo governance — the lint gates must be re-pointed at an untracked path, and backup/teardown becomes the user's concern.
**If wrong**: a repo-adjacent root (XDG-style) trades portability for governance; keeping deployment-local answers nothing — that is the status quo this card exists to end.

### D2 — Read/write admission gates

**Recommendation**: the unchanged guard set, re-pointed: holdout filter precedes append + `eval_split_lint` as the second gate (now over the user-level file); `load_rows` stays leave-one-out; `warm_pools` stays LAMBDA-tempered anchor-only; **new**: provenance-mandatory write admission — a row without `workspace_id` / `ts` / `feature_key` / `provenance.dispatch_id` is refused (today the fields are filled but not enforced; promotion makes them a gate, because cross-engagement data without provenance is unauditable by construction).
**Tradeoff**: mandatory provenance refuses otherwise-valid legacy rows — accepted, because the rows are re-derivable from the settlement history and the no-backcompat policy covers the rest.
**If wrong**: weakening the firewall for convenience re-opens the #518 contamination hole at exactly the moment the store starts crossing machines.

### D3 — Decay policy across engagement ages

**Recommendation**: the engagement-age multiplier in the fold (§2.4) with one half-life constant, floored above zero (PARK semantics — mass decays, rows persist), applied uniformly to anchor mass and refutation-fold mass so both consumers age on one clock.
**Tradeoff**: a single half-life is coarse — toolchain drift is faster for some families than others; the alternative (per-family half-lives) spends the second of our three constants and adds a calibration burden before there is data to calibrate against.
**If wrong**: no decay at all means stale authority anchors the sampler indefinitely (the exact failure the DTS discount was adopted to kill *within* engagements); too-aggressive decay starves cold start of the only prior art that exists.

### D4 — Contamination guards for the promotion

**Recommendation**: the eval-corpus held-out contract survives verbatim (filter-precedes-append + lint, §5's closing paragraph, extended to the journal reader); the #582 dynamic guard (honesty-healing refutation fold) is unchanged; **new**: the intake gates (§5) as the static guard on the bridge, and cross-workspace rows keep feature-keying with `workspace_id` as a label, never a join key.
**Tradeoff**: the static gates cost a lint pass per promoting entry — cheap; the temptation to skip them for "trusted" prose is the actual risk, because prose is the one surface where poisoning is cheap and subtle.
**If wrong**: one poisoned user-level store poisons every future deployment of the user — the blast radius of this decision is the largest on the card.

### D5 — The bridge read-face

**Recommendation**: the distiller reads journal entries from a single user-level journal directory (beside the memory store, same override pattern), validates them through a journal mode of the existing fact lint (the mechanical field contract, §3.2), and emits only the two products — feature-keyed priors and `anti_hints` string rows — through the ONE spine and ONE landing face. The policy reads priors via `warm_pools`/`feature_pool` and anti-hints via the existing `facts_anti_hints` recipe; nothing in the policy or prompt layer learns a new write face.
**Tradeoff**: funneling through the spine means the bridge inherits the spine's conservatism (case-specific stripping can thin genuinely useful entries); the alternative — a bespoke bridge pipeline — forks the T-pass and violates the #478 one-spine ruling for no measured gain.
**If wrong**: any second landing face or any policy-side write path breaks the L5 red line and re-creates the critic-by-another-name hazard named in §1.
