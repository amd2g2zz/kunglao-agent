# issue-686-crystallization-writeback — the settlement writes knowledge back

## Why

The transfer protocol's READ side is fully wired: class-level dead ends
thread into the method-family sampler (`_negative_pool_kwargs`), the
cross-task broadcast feeds the knowledge query's answer face, and the
rank path consumes the planner's advisory factors. The WRITE side is
dead — `record_negative` and `broadcast_solution` have zero production
callers, so a live analysis session never crystallizes anything, and no
derived row carries the provenance the acceptance demands ("carries
provenance to its producing step and can be revoked with it"). The loop
re-derives every discrimination from scratch: the exact failure the card
names.

## What Changes

1. **`crystallize.py`** — a new settlement write-back face:
   `crystallize_settlement` resolves the claim's method (and tool chain)
   from the usage log, then on a failed step records ONE class-level
   negative (deduped per step) and on a completed step with a certified
   answer + a banked step credit broadcasts the method (never the
   answer). Honest gaps write nothing.
2. **Provenance on negative rows** — `record_negative` gains optional
   `claim_ref` / `step_ref` kwargs, emitted only-when-present (the same
   additive shape the agent-conditioned columns use on the posterior
   store row). Schema stays `marl-negative/1`; readers are unchanged.
3. **`revoke_claim`** — an atomic rewrite of both derived stores that
   drops every row attributed to the claim (negatives by `claim_ref`,
   broadcasts by `claim`). The derived stores are caches: the evidence
   lives in the step/transition ledgers, so removal needs no tombstone.
4. **The settlement cage** — `settle_step` invokes the write-back in its
   own fail-open cage after the credit face (a crystallization failure
   never undoes a settled step), exactly the pattern the step-credit
   banking established.
5. **The amendment hook** — when a pair flip lands in
   `reconcile_case_settlements`, the flipped claim's derived rows are
   revoked (the discriminant dies with the settlement it was derived
   from); re-derivation waits for the next real settlement.

## Out of scope (named)

- No new action kind: crystallization is the settlement fold's
  write-back, not a policy action (the distillation-action question
  stays with the distillation-engine card).
- No re-crystallization on a positive flip: a positive flip has no
  settle context to derive from; the next settlement re-derives.
- The claim-terminal refutation face (a completed step later REFUTED)
  is not a second negative writer — the amendment hook revokes and the
  next settlement re-records.
