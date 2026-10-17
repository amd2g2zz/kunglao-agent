# design — issue-686-crystallization-writeback

## D1 — the write trigger is the step settlement (event), not a ledger fold (batch)

**CHOSEN**: `settle_step` invokes the write-back in a fail-open cage
after the credit face. The settle context already holds every key the
derived row needs (claim, step id, outcome, banked credit), the write
lands once per real event, and the cage pattern is the established
posture (a scoring/store failure never undoes the settled row).

**REJECTED** (fold-batch derivation): a batch face over the settled
ledgers needs its own processed-marker mechanism to stay idempotent,
re-derives rows the event already had in hand, and moves the write away
from the moment the evidence was fresh. The `marl-negative/1` reader
also keys on the CURRENT workspace signature — a late batch would stamp
rows with a class the step never ran under.

## D2 — negative on step failure; the claim-terminal refutation is not a second writer

**CHOSEN**: a step settling as `blocked`/`failed`/`error` (the dispatch
failure vocabulary) records the class dead end for the method its usage
row declared. A completed step later REFUTED rides the amendment
reconcile: the flip revokes the derived rows and the next settlement
re-derives.

**REJECTED** (negative also on terminal refutation): double-counts the
same failed attempt (the blocked step already recorded it) and needs a
step-level join at claim-terminal time that the terminal face does not
carry.

## D3 — additive optional keys on `marl-negative/1`, no version bump

**CHOSEN**: `claim_ref` / `step_ref` ride the row only when present —
the exact shape the agent-conditioned columns (`agent_type` / `claim` /
`credit_kind`) use on the posterior-store row. Readers pick known keys
from tolerant dict rows; a provenance-less row and an attributed row are
the same schema.

**REJECTED** (`marl-negative/2`): a new version implies a shape break
readers must branch on; there is none — the old shape is a strict prefix
subset of the new one.

## D4 — revocation is an atomic rewrite of the derived stores, not tombstones

**CHOSEN**: `revoke_claim` rewrites each store without the claim's rows
(temp file + atomic replace) and returns per-store counts. The negative
store and the posterior store are DERIVED caches — the evidence of
record lives in the step/transition ledgers and the experience ledger's
amendment rows — so removing a cache line deletes nothing admissible.

**REJECTED** (append tombstones + read-side filtering): every reader
(negative pools, warm pools, the cross-task face, leave-one-out scans)
would carry a tombstone check forever, and the stores would grow without
bound for what is a cache correction.

## D5 — the broadcast's credit is the banked step credit; no credit, no broadcast

**CHOSEN**: the broadcast fires only when the settle banked a step
credit AND the substrate reports a certified answer (strength 1.0) —
the row's credit is that banked number. The cross-task face consumes
only `credit > 0` rows, so a None-credit broadcast would be an
unconsumable row: fabricated strength is worse than no broadcast.

**REJECTED** (broadcast with credit None "honestly"): writes a row the
consumption face structurally ignores — a write-only row is exactly the
card's complaint, moved one layer down.

## D6 — dedupe keys make replay idempotent

**CHOSEN**: negative dedupe on
`(signature_class, method_family, claim_ref, step_ref)`; broadcast
dedupe on `(claim, method_family)` — the discriminant is the claim's
method, so a re-run of the same settlement AND a later certified step
on the same claim both append nothing (a per-step key would let an
N-step claim warm a sibling workspace N times over).

**REJECTED** (append-always + fold-side dedupe): the stores are read by
faces that count mass per row (negative pools multiply by `fails`); an
append-always store silently multiplies a replayed step's failure mass.
