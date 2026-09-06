---
name: loop-stage-gates
description: Analysis-loop stage discipline — the hard entry-anchor gate before "basic analysis complete" can be claimed (with the equivalent-path rule for import-table-less forms and failure-recorded-as-evidence), the clean-surface suspicion rule that forbids static-only negative capability conclusions, transition handoff economics (decision_delta plus carry_forward_refs; deterministic gates advance; ask only on real forks), and instruction feasibility negotiation when a requested step has a known blocked precondition. Use when moving a target between analysis stages, writing a stage-completion claim, or when an instructed step's precondition is known to be broken.
---

# Loop Stage Gates (stage latches + handoff discipline)

Four latches the analysis loop passes through between stages. They exist
because the two classic failure modes are symmetric: declaring progress the
evidence does not support (premature advance), and silently doing something
other than what was asked (quiet substitution). Both are gate failures, not
style issues.

## When to Use

- Before claiming "static/triage phase complete" or entering the dynamic phase.
- Before writing a negative capability conclusion ("no network", "no file I/O").
- When handing a target between stages or agents — deciding what to pass forward.
- When an instructed step has a known blocking precondition.

## Gate 1 — entry-anchor hard gate

- Static triage produces NO "basic analysis complete" claim and NO transition
  to the dynamic phase until the entry-anchor slot holds evidence.
- **Parse failure is evidence too.** A failed or unreadable parse is recorded
  as an evidence item (what was attempted, the exact failure); it is never a
  silent skip that leaves the slot empty.
- **Equivalent-path principle.** Absence of a traditional import table does
  not empty the gate — the slot is SEMANTIC (the surface that names entry
  capabilities), not a specific binary section. Fill it with the form's own
  anchor: managed runtimes use metadata references; script shells use a
  sensitive-API digest. The gate is satisfied or honestly failed; it is never
  skipped for form reasons.

## Gate 2 — clean-surface suspicion rule

- An abnormally clean call/import surface (base runtime APIs only, no
  business APIs) is NOT a finding of "no capabilities" — it is the canonical
  signature of dynamic resolution (functions fetched by name at runtime).
- Action: mark the suspicion IN the evidence, then route to dynamic capture
  (enumerate runtime-resolved APIs / inspect process memory).
- **A static surface alone can never support a negative capability
  conclusion.** Negative capability claims are confirmable only within a
  stated dynamic observation window — the static-clean surface is the
  suspicion trigger, not the verdict (falsifier family 6 in
  [falsifier-library.md](falsifier-library.md)).

## Gate 3 — transition economics (delta handoff)

- Stage handoffs carry only the **decision_delta** — decisions that change
  what the next stage does — plus **carry_forward_refs** (pointers to
  unchanged items). Unchanged context is referenced, never re-serialized.
- **Deterministic gates advance without asking.** Stop and ask the operator
  ONLY when two or more evidence-supported branches imply DIFFERENT next
  steps. An ask with a single live branch is a stall; a silent pick between
  live branches is a substitution.

## Gate 4 — instruction feasibility negotiation

When an instructed step has a known blocked precondition (the shell is still
on, so the static import table is unreadable — yet "check the import table
first" is the instruction):

1. **Execute and annotate honestly.** Run what is runnable, record the named
   step's outcome with its true quality (e.g. `quality=unreadable`) — never
   present a precondition artifact as the named step's evidence.
2. **Never silently substitute.** Doing a different useful step and reporting
   it as the requested one is a gate failure even when the substitute was
   better.
3. **Negotiate the order.** Surface the blocker, propose the recommended
   sequence (e.g. unpack first, then the import-table check), and ask for
   confirmation.
4. **Precondition completion is not the named step.** "Unpacked" is not
   "import table checked" — report each as what it is.

## Few-shot — gate-check execution skeleton (synthetic)

```python
def stage_gate_check(anchors, evidence):
    # Gate 1: anchor slots — non-empty AND recorded; failure counts as content
    for slot, probe in anchors.items():
        item = evidence.get(slot)
        if item is None:
            evidence.record(slot, probe(), quality="failed")  # NOT a silent skip
    if any(e.quality == "failed" for e in evidence):
        return {"advance": False, "claim_blocked": "static-complete"}
    # Gate 2: clean surface -> suspicion note, never a negative conclusion
    if surface_is_clean(anchors["imports"]):
        evidence.note("clean surface -> dynamic resolution suspected")
        return {"advance": True, "next": "dynamic-api-capture",
                "negative_claims": "forbidden-on-static"}
    # Gate 3: handoff shape — delta + refs only
    return {"advance": True,
            "handoff": {"decision_delta": delta_only(),          # decisions that change next actions
                        "carry_forward_refs": refs_to_unchanged()},
            "ask_operator": len(open_branches()) >= 2}           # only on a real fork
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Anchor slot | Evidence present OR honest failure recorded — never empty-by-skip |
| Capability claim | No negative capability conclusion rests on a static surface alone |
| Stage handoff | decision_delta + carry_forward_refs; unchanged context referenced, not re-serialized |
| Instructed step | Executed-and-annotated, or blocker surfaced + order negotiated — never silently substituted |

## Cross-references

- Static-clean as a suspicion trigger, not a conclusion: [falsifier-library.md](falsifier-library.md)
- Evidence typing at write time (what an item's type may move): [verification-safety.md](verification-safety.md#evidence-type-vocabulary)
- Phase structure these gates sit between: [malware-analysis.md](malware-analysis.md#six-phase-analysis-flow)
- Anchors for packed/hardened forms: [stacked-protections.md](stacked-protections.md)
