# Design — issue-719-distill-action

## Context

`scripts/online_distill.py` (issue-458) is complete: trigger scan,
budget ledger (`runs/distill-budget.json`), report validation,
anchored-sample oracle, tier-1 landing. Its only entry today is
REACTIVE — `checkpoints._maybe_distill` (e2e tick step) and the
SubagentStop closure hook fire on shelf-miss markers / unknown-format
probe failures. `scripts/action_space.py` (issue-12, extended by #684's
policy tier) is the L1 vocabulary: every entry is metadata (cost /
precondition / proof-power / consumer / ΔV-stub) plus a references list
naming the machinery it REUSES. Distillation is missing from that
vocabulary, so the policy can never price it.

Constraints that shape this design:

- **No trigger rules** (owner + the #458 rules-based-selection
  rejection): the entry's precondition is an availability condition,
  not a firing rule. The policy learns WHEN via value/cost; the
  markers stay reactive defense-in-depth.
- **蒸馏频率不许增 lives as budget**: the restraint ruling is the
  per-run act/hop cap in `distill-budget.json` (never-loosen clamp),
  not a gate refusing the action. The action's cost (5) is the
  planning constant; the ledger is the hard cap.
- **Reuse, never rebuild**: the budget guards, scan, oracle, and
  landing are online_distill's. The policy face is a reservation seam,
  a second entry into the same critical section the marker path uses.
- **Byte-equivalence baseline**: the registry's claim-category table
  and rank output stay untouched; only the vocabulary grows (23 → 24).

## Goal / Non-Goal

- Goal: (a) `orchestration.distill` is a registered, fully-specified
  action; (b) the policy's choice actuates through online_distill's
  budget guards (`actuate_distill` → `reserve_act`); (c) the reactive
  marker path is provably unchanged.
- Non-Goal: full orchestrator wiring of a proactive scan/land
  round-trip; new distillation mechanics; crystallize (#686) knowledge
  distillation; trigger-rule heuristics of any kind.

## Decisions

### D1. Level ORCHESTRATION, cost 5, alongside osint

Both `osint` and `distill` acquire workspace capability from outside
the current evidence set (external sources vs. the tool shelf), so
both sit at the orchestration tier — the loop's teeth. Cost 5 matches
the "budgeted act" shape (cheaper than deepen=6, dearer than expand=3):
expensive enough for the policy to price, cheap enough to be choosable.
The entry is NOT settleable (it changes the tool shelf, never the
claim economy's candidate set — that is the policy tier's exclusive
role).

### D2. The precondition is availability, not a trigger

"the shelf has no viable candidate for the task at hand OR the policy
decides proactive capability acquisition (a costed choice, never a
trigger rule — the budget ledger is the hard cap)". Two-sided
disjunction: reactive-style availability (shelf thin) OR pure policy
initiative (proactive acquisition). Nothing in the registry, the
seam, or the engine consults this string mechanically — it orients
the policy, exactly like every other precondition in the registry.

### D3. `actuate_distill` is the budget linkage only

`action_space.actuate_distill(ws, token, ...)` lazily delegates to
`online_distill.reserve_act` — the same flock-guarded check-and-debit
the marker path uses (per-run cap, duplicate-token refusal,
fail-closed corruption, never-loosen clamp). It returns the engine
receipt or None; refusals diagnose via `online_distill.refuse_reason`.
The reserved act's scan/retrieve/oracle/land halves stay on the
engine's existing faces (the e2e tick step for reactive acts). Full
orchestrator wiring of a proactive act's execution is a documented
seam for the dispatch-actuation work — out of this card's scope.

### D4. The reactive path gets no new gate

`checkpoints._maybe_distill` keeps calling `od.scan_triggers` +
`od.reserve_act` directly. The policy seam is a second caller of the
same guards, never a precondition on the marker path. Test pin: the
marker scan still fires from the tick step with zero action_space
involvement.
