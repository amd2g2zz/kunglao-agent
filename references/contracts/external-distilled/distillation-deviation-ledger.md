---
name: distillation-deviation-ledger
description: 'Deviation ledger + enforcement-site traceability for knowledge-carrier artifacts (external-distilled,
  S7): a property that cannot be carried faithfully across a representation or layer boundary is recorded as an
  explicit deviation entry (what diverges, why, compensating control); every invariant names its enforcement
  site; derivation is incomplete while any invariant lacks a guarantor; failed verifications discharge as
  concrete counterexamples. When a claim/fact can only be partially enforced, when distilling knowledge across
  epistemic boundaries, or when auditing that every rule in a contract has a named mechanism that checks it.'
domain: contracts
family: external-distilled
source_id: S7
source_license: MIT
retrieved: 2026-09-23
epistemic: external-derived
distill_bar: general+heuristic
dedup: overlap(machine-check-contract)
---

# Deviation ledger & enforcement traceability (external-distilled)

> External-derived methodology (never directly PROVEN). Generalized paraphrase;
> provenance = S-id list above (agent-contract formality source). The
> machine-check contract already requires every verification to carry
> {command, expected, actual, passed}; this card adds the boundary discipline
> the machine-check record does not cover: what happens when a property
> CANNOT be carried faithfully.

## The pattern

Formal derivation has a rule worth stealing whole: when a property cannot be
mapped faithfully across a representation boundary (formal spec → storage
schema is the canonical case), do not hide the loss — **record a deviation
entry** (what diverges, why the target representation cannot express it, and
the compensating control that covers the gap), and give every invariant a
**named enforcement site** (mechanism-level constraint / application-layer
check / test). Derivation is INCOMPLETE while any invariant lacks a
guarantor. A failed proof discharges as a concrete counterexample — a
specific value that violates the property — not a bare false.

## Mapping onto kunglao's contracts

- **machine-check-contract** (our card): every claim's verification carries a
  machine_check record. The ledger pattern extends this from "each check
  passes" to "the property survives the boundary": distillations, mappings
  and migrations are incomplete while any property they should preserve
  (recall hits, byte-exact index rows, provenance fields) lacks a named
  checking site. The parity tests that pin contract docs to YAML maps are
  this pattern already — the card generalizes it to every cross-boundary
  artifact.
- **error-response-taxonomy** (our card): deviations are pre-declared
  tolerance, not runtime errors; the taxonomy's forced-response table governs
  the compensating controls.
- **wal-protocol / claim-register**: deviation entries are facts like any
  other (status per the schema; never silently dropped).

## When to use

- A knowledge-carrier artifact (distillate card, generated index, migrated
  schema) cannot faithfully carry a source property — record the deviation +
  compensating control; name where each preserved property IS enforced.
- An audit asks "which mechanism guarantees rule R?" — the traceability
  table answers with a site name, or the audit fails with an orphan list.
- A verification fails — the discharge is a concrete counterexample (input,
  expected, actual) reusable as a test fixture, per the machine-check
  contract's exception path.

## Failure mode addressed

Silent fidelity loss at representation boundaries: a card "summarizes" a
methodology and drops its guardrails; an index regenerates and drops
symptom routes; a migration drops an invariant — each survives because
nothing was REQUIRED to name where the property now lives. The ledger makes
the loss a first-class artifact: visible, addressed, and auditable — and the
self-inspiring move is to ask, for every boundary you cross (distill,
generate, migrate, translate), "what does this boundary lose, and which
named site compensates for it?"

Companions: [machine-check-contract.md](../machine-check-contract.md),
[error-response-taxonomy.md](../error-response-taxonomy.md),
[wal-protocol.md](../wal-protocol.md).
