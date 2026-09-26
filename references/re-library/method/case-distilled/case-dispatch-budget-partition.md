---
name: case-dispatch-budget-partition
description: 'EXP-4 chain-wave distillate (desensitized): governance rules for orchestrated
  analysis on layered targets, mined from a measured two-arm campaign (7 layered units x 2 arms).
  Situation→action rules: dispatch-decomposition budget partition (orchestrators that analyze solo
  first dispatch too late to matter), verifier-channel-outage fallback via independent
  re-implementation in a second runtime, and checkpoint-immediately-on-peel discipline for any
  grader that scores partial progress. Read before tuning orchestrator dispatch timing or
  designing partial-credit eval surfaces.'
domain: method
family: case-distilled
source_id: EXP4
source_license: internal
retrieved: 2026-09-24
epistemic: evidence-derived
distill_bar: general+heuristic
dedup: new
---

# Dispatch budget partition on layered targets (EXP-4 chain wave)

Measured basis: internal two-arm campaign, 7 constructed layered units × 2 arms
(orchestrated loop arm vs plain single-session arm), wall/budget capped per
unit. Item ids are internal (unit tier + language only). All numbers below are
from that campaign's run ledgers; campaign log stays in untracked scratch.

## Rule 1 — partition the budget before analysis starts (dispatch timing)

| Situation | Next action |
|---|---|
| Orchestrator with claim→worker→verify machinery; layered target where each layer is solo-tractable | Reserve the first dispatch for ≤50% of wall budget. If decomposition is worth anything, workers need remaining budget to finish AND a checker pass needs remaining budget after them. |
| First maker worker would start in the final third of the budget | Treat as a smell: solo analysis has already consumed the window where workers could have converged in parallel. Either dispatch immediately or commit to solo explicitly (and skip the dispatch theater). |
| Task family where a plain single session already solves units N times cheaper | The machinery's edge can only be in quality (verification depth), not speed. Do not spend wall on dispatch rounds that only re-verify scaffold claims; send red-team workers at actual analysis claims. |

Why-this-design (measured): in the campaign, 6/7 orchestrated sessions did
solo analysis first and dispatched maker workers only at 60–90% wall. The two
hardest units still PASSED — but only because a maker happened to finish its
peel inside the residual window and the graded candidate turned out to be the
worker's artifact. One unit failed on the same pattern: the maker never
finished before the wall. Dispatch timing, not decomposition power, was the
binding constraint.

## Rule 2 — verifier-channel outage: independent re-implementation

| Situation | Next action |
|---|---|
| A peel/recovery result needs independent verification but the checker/subagent channel is unavailable in-session | Re-derive the result a SECOND time in a different runtime or language, from raw input only; compare digests/outputs. Two independent derivations agreeing is the strongest in-session substitute for an external checker. |
| Only one runtime available | At minimum replay from serialized raw bytes (not from in-memory state), and record the derivation script as the reproduce handle. |

Why: the only fast, fully-converged PASS in the campaign used exactly this
(Node re-derivation + original-runtime exec cross-check, digests recorded as
expected/verified pairs). Delta vs the falsifier library's independent
re-derivation rule (which resolves conflicts between two EXISTING facts):
here re-derivation is proactive verification of ONE result — no conflict
exists yet; the second derivation creates the missing second opinion.

## Rule 3 — checkpoint every completed peel immediately

| Situation | Next action |
|---|---|
| The grader/scorer awards partial credit for layer checkpoints, and the artifact convention (paths, formats) is knowable | Write the checkpoint artifact the moment a layer peels — digest it, then proceed. Never batch checkpoints at the end; a wall/budget death before assembly then still scores partial progress. |
| Designing the eval surface (harness-side rule) | State the checkpoint convention IN the task surface. In the campaign, 12/14 sessions earned zero partial credit — not because layers were unpeeled, but because the checkpoint directory convention was invisible to sessions and every session invented its own artifact layout. |

Why: partial-credit curves are the experiment signal for layered work; an
unstated convention silently zeroes it, which both starves the reward channel
and hides real progress from the selector.
