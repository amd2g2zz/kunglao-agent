# Proposal — issue-693-entropy-operators

## Why

The objective function should be uncertainty reduction over the
hypothesis space, not "compress the state". Two things were missing:
the objective, and the operators that achieve it.

The entropy term was deleted (ADR-001, the first governed removal)
with the stated reason: on all real ledgers `LAMBDA_DH × ΔH` was
mechanically inert — 612/612 rank events carried `dh_pq = 0`. The
entropy was constant zero because the hypothesis distribution was
DEGENERATE (all credit zero -> posteriors never move -> entropy never
moves). Removing the term hid the symptom instead of curing it. A
non-degenerate categorical moves entropy for free
(`PQCategorical.entropy` / `update_eliminate` were always there); what
never existed is the machinery that KEEPS the distribution
non-degenerate: invariant pruning, counterexample refinement,
layer-scoped hypotheses, and a reference constant table.

Layer conflation was actively harmful: when `md5(plaintext) != captured`
the system could not tell whether the family, the primitive, or the
composition was wrong, so option-death pushed the whole family down
even when only the concatenation was wrong, and an over-wide conclusion
("not MD5") was permanent.

## What changes

- **New module `scripts/rlvr/constants_ref.py`** — the reference hash
  constant tables (MD5 / SHA-1 / SHA-256 / SM3: IV + round constants,
  standard definitions generated from closed form and cross-checked
  against hashlib) and the mechanical `classify` diff that separates a
  reference table from a MUTATED variant while still identifying the
  family (`exact` vs `family` are separate answers).
- **New module `scripts/rlvr/invariants.py`** — the invariant-pruning
  operator: `check_candidate` / `prune` reject a candidate whose
  predictions contradict observed facts on disk (output length, loop
  bounds, alignment) BEFORE an attempt is spent; unpredicted
  dimensions are inconclusive (never a rejection); rejection reasons
  name the invariant.
- **New module `scripts/rlvr/hypotheses.py`** — layer-scoped
  hypotheses + CEGAR-shaped counterexample refinement:
  `refine_on_mismatch` localizes a recorded mismatch to the family /
  primitive / composition layer and names the re-search sub-space;
  `mint_hypothesis` registers hypotheses at their falsifiable layer;
  `layer_death_cells` keys termination accounting `(kind, family,
  layer)`; `covering_matrix` wires the t-way covering machinery
  (shared `replay_equivalence.required_combos`) into the SEARCH side.
- **Export map** — `rlvr/__init__.py` gains the three module imports
  and `__all__` names (additive only).
- **Entropy observability pin** — a test pins the ADR-001 gate: the
  frontier PQ entropy is feeds/log/TUI only; a non-degenerate
  categorical NEVER changes a priority score (re-entry follows ADR-001
  §2 with real-ledger evidence, never a drift).

## Non-goals

- No restoration of the `ΔH_PQ` score term (ADR-001 stands; this card
  supplies the non-degeneracy machinery that would make a future
  governed re-entry meaningful, it does not re-enter).
- No change to `rlvr.termination`'s landed `(kind, family)` Beta
  posterior or its sampler-floor wiring — `layer_death_cells` is the
  NEW layer-scoped accounting face in the hypotheses module; folding
  the layer into the option-death estimator is a separate governed
  change.
- No change to `hypothesis_store`'s state machine (open/refuted/
  superseded permanence stays; the refinement path mints a fresh open
  hypothesis at the named layer instead of reopening terminal ones).
- No obstacle-registry schema change (failure rows are consumed
  read-only; layer attribution arrives via the `layer_of` map).
