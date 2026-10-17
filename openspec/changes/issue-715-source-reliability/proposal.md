# issue-715-source-reliability — learn which evidence sources to trust from invalidation patterns

## Why

Evidence carries no LEARNED source reliability. The evidence DAG view
(`scripts/evidence_dag.py`) renders a `source_reliability` field whose
producer is a mechanical Admiralty default table (`build_evidence_index`
assigns A1/B3/... by file type) — a hand-written ranking, not knowledge.
Nothing consumes it as credit trust, no refutation teaches it, and the
failure classes stay undetectable: pseudocode vs assembly
inconsistency, a hook trace vs syscall conflict, a MITM capture
diverging from the server-side record. Wrong-source evidence gets
PROVEN and then pollutes the Beta posterior.

Owner ruling (2026-10-15): rule enumeration does not work
("这种规则是枚举不完的"). Humans learn reliable reference frames from
massive experience. The system must learn the same way: from
invalidation patterns, never from a hand-written trust table.

## What Changes

1. **Evidence labels.** Evidence items carry `source` (the producing
   tool: `ghidra-pseudo`, `raw-asm`, `frida-trace`, `mitm-capture`, ...)
   and `reference_class` — the reference frame, one of `raw`, `derived`,
   `inferred`. The taxonomy is a label vocabulary keyed into the
   posterior; it never ranks trust (no prior differentiates the
   classes).

2. **The learned source-reliability Beta (`source-reliability-715`).**
   One new module `scripts/rlvr/source_reliability.py`. The reliability
   of a labeled source class is

       Beta(alpha, beta | source_class, context_class)

   folded from append-only invalidation events — the only teacher:
   evidence REFUTED by later evidence -> beta += 1; evidence CONFIRMED
   -> alpha += 1. No event about a source -> Beta(1, 1) uniform: every
   source is equally plausible until data arrives (the uniform prior is
   the absence of a rule). Reads back off — the (source_class,
   context_class) cell when it has observations, else the source-class
   marginal pooled across contexts (reliability learned for a source in
   one context applies to that source in new contexts — the
   generalization face), else the prior.

3. **Thompson sampling as the exploration engine.** `theta` draws from
   the read posterior. High-variance (thinly observed) sources draw
   wide — the sampler naturally explores uncertain reference frames;
   settled sources draw tight. No rule says "check assembly when
   pseudocode is suspicious"; the cross-validation pressure falls out
   of the posterior width.

4. **Credit weighting (`source-credit-weighting-715`).** The step-credit
   module (`scripts/rlvr/step_credit.py`) gains `weighted_step_credit`:
   each evidence item's credit multiplied by its source's learned
   theta — `step_credit = item_credit × source_reliability_theta` — and
   the module's `step_credit` entry routes through the composition, so
   the production settle path carries the learned discount. Credit from
   low-reliability sources is discounted automatically; unlabeled
   evidence weights 1.0 ("weighted ... if available"), keeping every
   pre-existing fixture byte-identical.

## Non-goals (recorded)

- **No trust rule table, anywhere.** The pre-existing Admiralty
  defaults in the evidence index builder are untouched (an ICD-203
  label face); the learned Beta never reads them, and no new mapping
  from source identity to trust is introduced.
- **No state-signature coupling.** The reliability Beta is knowledge
  state with a plain read face; it does not enter the canonical state
  signature (the recording face is frozen — its hashing surface stays
  untouched).
- **No producer wiring in this change.** Stamping the labels into fact
  frontmatter and recording refutation/confirmation events at the
  red-team / verify faces are follow-up wiring on top of the recorded
  API.

## Extends / Changes

- Extends #705 (learned-state family — same fold discipline, same
  shared-store posture as the class-level negative knowledge).
- Depends on #712 (step-level credit — the per-item composition this
  weighting rides).
- Extends #687 / #690 (settlement grain: the step is the credit unit).
