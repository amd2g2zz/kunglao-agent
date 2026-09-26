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

Verdict algebra: `derivation complete ⇔ every invariant has a named
enforcement site (mechanism / app-check / test)`; `unfaithful mapping ⇒ a
deviation entry {what diverges, why, compensating control} exists`; `failed
verification ⇒ concrete counterexample (input, expected, actual), never a
bare false`.

```text
// crossing a representation boundary (distill, generate, migrate, translate):
for property in preserved_properties(artifact):
    site = enforcement_site(property)        # where is it checked NOW?
    if site is None:
        record_deviation(property,           # what diverges
                         reason,             # why the target cannot express it
                         compensating)       # the control that covers the gap
assert no_orphan_invariants()                # derivation INCOMPLETE otherwise
```

Why: silent fidelity loss at representation boundaries survives because
nothing was REQUIRED to name where the property now lives — a card
"summarizes" away its guardrails, an index regenerates away its symptom
routes, a migration drops an invariant. The ledger makes the loss a
first-class artifact: visible, addressed, and auditable.

## Mapping onto kunglao's contracts

| Our contract | Overlap | Delta this card adds |
|---|---|---|
| machine-check-contract | every claim's verification carries machine_check {command, expected, actual, passed} | extends from "each check passes" to "the property survives the boundary": distillations/mappings/migrations name where each preserved property IS enforced — the parity tests pinning contract docs to YAML maps are this pattern, generalized to every cross-boundary artifact |
| error-response-taxonomy | forced-response table governs deviations' compensating controls | deviations are pre-declared tolerance, not runtime errors |
| wal-protocol / claim-register | deviation entries are facts like any other (status per the schema; never silently dropped) | the ledger form: loss recorded with a named compensating site |

## When to use

```text
use when:
  - a knowledge-carrier artifact (distillate card, generated index, migrated
    schema) cannot faithfully carry a source property
  - an audit asks "which mechanism guarantees rule R?"
      -> traceability table answers with a site name,
         or the audit fails with an orphan list
  - a verification fails -> discharge as a concrete counterexample per the
    machine-check contract's exception path
```

The self-inspiring move: at every boundary you cross — distill, generate,
migrate, translate — ask "what does this boundary lose, and which named site
compensates for it?"

Companions: [machine-check-contract.md](../machine-check-contract.md),
[error-response-taxonomy.md](../error-response-taxonomy.md),
[wal-protocol.md](../wal-protocol.md).
