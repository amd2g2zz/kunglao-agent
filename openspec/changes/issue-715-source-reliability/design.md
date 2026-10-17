# design — issue-715-source-reliability

## D1 — labels key the posterior; they never rank trust

Evidence carries `source` (tool name) and `reference_class` in the
closed taxonomy `raw > derived > inferred`. The source-class key is
`source_class = "<source>|<reference_class>"`. The tier ordering is
vocabulary documentation (distance from the reference frame), NOT a
prior: every class is born Beta(1, 1) and only invalidation events move
it. The same tool in two frames (a raw listing vs decompiled pseudocode)
gets two independent cells — the pseudocode-vs-assembly split is a CELL
split, learned apart, never ruled apart. `reference_class` outside the
taxonomy is refused at the write boundary (loud result, no row).

## D2 — invalidation events are the only teacher

`record_refutation(evidence, refuted_by=...)` -> beta += 1 for the
REFUTED evidence's source class (the source produced evidence later
evidence overturned). `record_confirmation(evidence, confirmed_by=...)`
-> alpha += 1. A refuter is NEVER auto-credited — it is confirmed when
IT is confirmed; `refuted_by`/`confirmed_by` ride the row as audit
(eid strings only, no content). Rows are append-only
(`source-reliability.jsonl`, schema `source-reliability/1`); the fold is
a read-face property (raw rows are never rewritten) — the same ledger
discipline as `rlvr.posteriors`.

## D3 — backoff, not shrinkage: generalization across contexts

Read rule: the exact `(source_class, context_class)` cell when it has
observations; else the source-class marginal pooled across ALL contexts;
else Beta(1, 1). Contexts are caller labels (a task phase, a target
family, anything); a NEW context inherits everything learned about the
source elsewhere. Declared simplification: cells do not shrink toward
the marginal — the backoff is all-or-nothing; partial pooling is the
named refinement if measured cells overfit.

## D4 — Thompson sampling is the exploration engine

`theta` = one stdlib `betavariate(alpha, beta)` draw from the read
posterior (`rng=None` -> `random.Random(0)`, the anchor-deterministic
default of the q_cells sampler). Exploration is a property of the
posterior width, not a policy: an uncertain source's draws reach high
values and occasionally beat a settled mediocre source, while a
settled-bad source's draws effectively cannot. The "cross-validation
trigger" is therefore learned — nothing enumerates when to doubt which
frame.

## D5 — the credit-weighting composition rides ON TOP of the step score

`weighted_step_credit(items)` = the mean of per-item
`item_credit(meta) × theta(meta)`, where theta is a Thompson draw from
the learned source-reliability Beta — 1.0 when the item carries no
source labels ("weighted ... if available"), so an unlabeled window
scores byte-identical to the pre-discount step score. The step-credit
module routes its `step_credit` entry through the composition, so the
production settle path carries the learned discount; the store is read
only when a labeled item is present (no I/O for unlabeled windows).

Interfaces with the step-credit module's OWN ruled credibility lookup
(the Admiralty letter carried in an item's provenance): the learned
face neither reads nor feeds it. The two modulations compose
multiplicatively — the learned Beta is the learning layer this change
adds; retiring the letter table is that module's own conversation,
not silently done here.

## D6 — store posture: shared, fail-open, auditable

Store root = `strategy_store.store_root()` (env
`KUNGLAO_POSTERIOR_STORE` override) — SHARED, not per-workspace: tool
trust is cross-engagement knowledge, so a second workspace inherits what
the first learned about a source; the per-context backoff keeps that
generalization explicit rather than silent. Reads are tolerant
(missing/dirty store -> the prior face; schema-violating rows skip);
writes are loud-result dicts through the shared append primitive
(`q_cells._append_row`, the marl precedent) and never raise into the
producer.

## D7 — what is deliberately NOT built here

- No tie between the learned Beta and the Admiralty letter field
  (seeding the prior from A..F would be exactly the ruled enumeration
  the owner rejected).
- No producer-side stamping of `source`/`reference_class` into fact
  frontmatter (the worker-protocol wiring is a follow-up; the label
  contract and the learning faces land here).
- No canonical-state-signature coupling (frozen hashing surface).
- No new selection policy — consumers that pick between reference
  frames draw `theta` per candidate and take the max; that is the
  recorded TS contract, not a rule table.
