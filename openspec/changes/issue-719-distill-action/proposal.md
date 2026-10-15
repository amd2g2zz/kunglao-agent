# Proposal — issue-719-distill-action

## Why

`scripts/online_distill.py` (issue-458) is a complete online-distillation
engine: trigger scan (shelf-miss marker / unknown-format probe failure),
re-library → web retrieval → anchored-sample validation → run-local shelf
landing, budgeted by `runs/distill-budget.json`. But it has NO policy
surface: it is not in `scripts/action_space.py`, so the L1 policy cannot
CHOOSE to distill. Distillation only fires reactively — when a miss has
already happened. The policy can never decide "the shelf is thin, invest
in capability now".

Owner ruling (2026-10-16): the L1 action list must include distillation
("不是有在线蒸馏？这个需要加上"). Distinction held: online_distill (#458,
this card) is TOOL acquisition; crystallize (#686) is KNOWLEDGE
distillation — separate, still suspended.

## What Changes

One new orchestration-level action plus its budget linkage:

1. **`orchestration.distill` in `scripts/action_space.py`** — level
   ORCHESTRATION (alongside `osint` — both are workspace capability
   acquisition), cost 5 (a budgeted act — the distill budget ledger is
   the hard cap), precondition "the shelf has no viable candidate OR
   the policy decides proactive acquisition" (an availability condition,
   NEVER a trigger rule), references naming `scripts/online_distill.py`
   and `runs/distill-budget.json` (the machinery is REUSED, not
   rebuilt). Vocabulary count 23 → 24 (9 + 6 + 6 + 3).
2. **`actuate_distill` budget seam** — the policy's distill choice
   reserves ONE budgeted act through online_distill's EXISTING guards
   (`reserve_act`: per-run cap, duplicate-token refusal, fail-closed
   corrupt ledger, never-loosen clamp). One call, one receipt (or an
   explicit refusal via `refuse_reason`). The scan/retrieve/oracle/land
   halves stay on the engine's existing faces.
3. **Reactive path unchanged (defense-in-depth)** — the shelf-miss
   marker auto-fire (`checkpoints._maybe_distill` tick step + the
   SubagentStop closure) keeps its own entry to the same budget guards.
   The policy face ADDS a choice; it never gates the marker path.

## Design principle (critical)

The policy learns WHEN distillation is worth its cost (value/cost per
the unified architecture; learning state ∈ s). NO trigger rules — no
"if shelf thin then distill". The trigger markers stay reactive
defense-in-depth only. 蒸馏频率不许增 (owner ruling) holds as the BUDGET
CAP, never as a rule blocking the action.

## Non-goals

- No trigger rules or capability-matching tables driving the policy
  choice (the #458 rules-based-selection rejection stands).
- No new distillation mechanics: retrieval, oracle, landing, budget
  algebra all stay in `online_distill.py` verbatim.
- No full orchestrator wiring of a proactive scan/land round-trip
  (documented seam in design.md D3 — the action entry + budget linkage
  is this card's scope).
- No crystallize (#686) knowledge distillation — out of scope.
