# issue-824-model-contract — the unified RL model's P1 contract

## Why

The owner-approved axis rewrite (#806, 2026-10-25) replaces the layered
model with ONE model: one loop / one learner / one pool (axioms A1–A5).
Today the "memory" of the system is scattered across independent faces
(case_bank JSONL, strategy_store posterior rows, the lessons CBM
library, recall_inject index) with no shared episode grain, the
learning signal still carries per-fact credit (the dilution disease the
panel named: 1.2 obs/cell, a day spent reporting a PE's sha256 scores
well), and the write path records raw process because nothing at the
boundary refuses it. P1 lands the CONTRACTS — no new storage, no
behavior change for existing readers until P2.

## What Changes

1. **Episode schema (`rlvr/episode_schema.py`)** — schema `episode/1`:
   the machine-readable frontmatter of one episode = one task
   (`context_features` / `commits[]` / `outcome` / `cost` / `utility` /
   `reusable_fragments` / `milestones[]` / `reward`), validated by a
   fail-closed validator. Body and fragments are SUMMARIES ONLY — a
   raw-log write attempt is refused by the schema's summary limits
   (the write-side compression face).
2. **Pool physical layer (`rlvr/episode_pool.py`)** — `runs/episodes/`
   in the workspace: markdown+frontmatter files riding the EXISTING
   runs/ zone (the what-happened layer that already hosts
   dispatch-ledger.jsonl / case-bank.jsonl / experience.jsonl). Zero
   new storage engines; the directory is created lazily by the pool
   module (eager init scaffolding is #791 init-v2 territory). THE THREE
   POLICIES AS HOOK GATES (A2: policy, not agent discipline):
   - WRITE: admission = terminal-nonzero-reward OR clean-attribution
     failure OR surprise event, summaries only, AND the trust gate —
     an episode's outcome enters the pool only when its verification
     reference resolves to a PASSED record (`verifier_integrity.
     resolve_verification`, called unmodified — A4: verified evidence
     only at the memory boundary).
   - READ: retrieval at exactly three legal phases (episode_start /
     commit_boundary / blocked); utility-ranked, deterministic; each
     retrieval bumps the episode's retrieval counter (the update
     policy's citation potential).
   - UPDATE: every settlement updates the stats; retrieved-but-uncited
     episodes decay; a cited similar case gets max-revalue (capped);
     capacity prunes by utility, never by time.
3. **Indexers (`rlvr/pool_indexer.py`)** — DERIVED VIEWS ONLY (A3):
   the value table (context_features × commit action → n /
   mean-reward / mean-cost over episode files; regenerate = identical
   output; writes NO file — no parallel store) and the playbook view
   (successful-episode compression: completed+verified episodes'
   reusable fragments, deduped, capped — the legitimate form of
   distillation; deep compression is P3, this card pins the rules).
4. **Reward switch (`rlvr/reward_signal.py`)** — the learning signal
   becomes `R = completion + milestone_progress − cost_term` (A1):
   completion is the verified task outcome, milestones are the task
   decomposition's sub-goals EACH gated by the trust spine (the same
   `resolve_verification` wall), cost is the normalized episode cost.
   Per-fact credit RETIRES from the learning signal — it survives only
   as the audit face (the existing step-credit/scalar faces, called
   read-only). The settlement hook (`on_settlement`) computes R for the
   episode and fires the pool's update policy.

## Constraints honored (A1–A5)

- **A1**: `compute_reward` takes completion / milestones / cost — no
  fact-credit parameter exists in the signature; the PE pathology
  (many verified facts, zero task completion) scores ≈ 0 (pinned).
- **A2 single-model law**: the pool is ONE contract; strategy_store →
  statistics view, lessons/CBM → playbook view, recall_inject → read
  face are declared MAPPINGS — this card modifies none of them (readers
  unchanged until P2; pinned by import+shape tests).
- **A4**: every pool write and every milestone verification resolves
  through the unmodified trust spine (`verifier_integrity`); settlement
  / verifier semantics are only ever CALLED.
- **A5**: zero new human decision points.
- No touch: settlement/verifier semantics, #818 in-flight tests, eval/
  corpus (separate agent), claims_store mutation paths.

## Impact

- commits: feat: the unified RL model contract — episode schema, pool
  policy gates, derived indexers, the A1 reward switch (issue 824)
- tests: tests/test_model_contract_824.py (synthetic fixtures: schema
  reds, write-gate reds incl. the raw-log refusal, retrieval-decay
  green, determinism of both views, PE-pathology ≈ 0, trust-spine
  gating)
- registration: scripts/README.md rows + rlvr facade; baselines emitted
  first, deploy-manifest --write LAST (P1 wires no hook, so the
  manifest is expected stable — verified, not assumed)
