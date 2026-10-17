# issue-730-late-arm-oracle — a case armed after settlement never observes that claim

## Why

`record_case_settlements` (`scripts/settle_round_credit.py`) is the
ranker's live posterior-update leg — the only writer that moves a case
posterior off the wide `Beta(1,1)` prior. It keys its observations on
`banked`: the dispatches whose FIRST settlement rode the current pass.

That guard bought idempotency at the cost of ARMING ORDER. A case armed
after its claims have settled can never observe them, because their ids
never re-enter `banked`. The consequence is not a missing row — it is a
missing LEDGER: `runs/posteriors.yaml` is never created, the ranker
prices every dispatchable claim from the prior forever, and no settled
claim ever moves a case posterior, while the settlement count reads
healthy.

Reproduced against the live workspace (not inferred from code): the
register carries `C-005` PROVEN and `C-009` REFUTED, both
`answers_question: q2`; `oracle/cases/case-q2-param-generation.yaml` is
armed with `target_pq: q2` — the ideal pass/fail observation pair — and
`runs/posteriors.yaml` did not exist.

The late-arm ordering is the COMMON one: you learn what to ask after the
first claims land. This is the A-layer acceptance blocker for the v0.1.6
RL-loop closure plan ("posteriors.yaml has rows" is unmet, and the cause
is a defect, not unmerged code).

## What Changes

1. **An explicit dedup record instead of a proxy.** Every observation
   lands one auditable `case-observation/1` row
   (`{schema, ts, case_id, claim_id, passed, source}`) in the
   consolidated experience ledger. The pair `(case_id, claim_id)` is what
   "already observed" means — so an observation no longer depends on
   which pass happened to be running when the case was armed.
2. **The late-arm amendment** — `amend_case_settlements(ws)` sweeps every
   decisive-terminal claim against the ARMED cases and observes each
   un-observed pair. Idempotent at any wall-clock distance: the dedup set
   is read from the ledger's own rows, so a re-run is a no-op.
3. **One invariant across two legs**: every (ARMED case,
   decisive-terminal claim linked to its `target_pq`) pair is observed
   EXACTLY ONCE, whatever the arming order. Both legs share one entry
   builder, one write face and one dedup set, so the fresh and amended
   runs compose instead of overlapping — including on a settle-path
   RETRY that re-banks a claim an earlier amendment already observed.
4. **The amendment observes only armed cases, and skips retired ones.**
   It back-fills claims that settled before their case existed, so it
   must only write complete, deliberate question-linkages — a stub doc
   with a bare `target_pq` is not a hypothesis anybody committed to. The
   FRESH leg keeps its existing `target_pq` link — tightening it was
   attempted and reverted (it broke the module's own original suite and
   is unrelated to this card). Arming is explicitly NOT claimed to mean
   runner-loadability: the two shapes disagree on `expected`, which is a
   pre-existing defect tracked separately.
5. **The new schema registers for liveness.** `NATIVE_SCHEMAS` in
   `rlvr/consolidated_ledger.py` records schemas born in the consolidated
   file (no legacy rel to derive them from), so `liveness()` pre-seeds
   `experience:case-observation/1` at 0 — a writer that dies reads DEAD,
   never absent.

## Non-goals

- **Correcting an already-banked credit.** A ledger correction still does
  not move the learning signal (the first-settlement guard). That is the
  separate sibling card, not this one.
- **Re-observing a claim whose outcome later changes.** The dedup key is
  the pair, so a status correction needs a retraction face — again the
  sibling card.
- **Touching `runs/posteriors.yaml`'s schema.** The posterior stays
  `posteriors-schema/1`; the observation history lives in the ledger, not
  in the belief store.
