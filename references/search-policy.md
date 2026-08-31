
**Heuristic**: are you about to dispatch a worker without searching first? If yes -> STOP. Run 1+ doc search and record in `## search_before_work` before dispatching (see F-2 in failure-modes-*-monitoring.md).
# Search Policy: Claim-driven dispatch + computed-priority best-first + tier-gated deepening (DESIGN §8.5)

RE is a search problem (state = fact base, operators = workers, goal = C0-C7).
Three layers, each real and machine-checkable:

1. **Claim-dependency graph** (`claim_deps.yaml`) - gates dispatch order. A claim is
   dispatchable only when every claim it `depends_on` is terminal. Refutation
   propagates along the same edges (§9 rule 4b). This is the CORE.
2. **Computed-priority greedy best-first** - among dispatchable open claims, the
   orchestrator dispatches the highest-priority one first. Priority is the VoI
   proxy computed by `scripts/priority_ratio.py` (NOT LLM free judgment; #499):

       score(C) = [0.45*L + 0.30*D + 0.25*N] / TIER_COST[tier]
         L leverage      : downstream OPEN claims normalized; claim with a terminal fact -> 0
         D discriminator : live competitor_group (>=2 OPEN) = 1.0 / answers_question = 0.5 / else 0.2
         N novelty       : 1 - same-category terminal-facts saturation (facts/_INDEX driven)
         TIER_COST       : {1: 1.0, 2: 3.0, 3: 10.0} (deeper tier -> smaller ratio)

   Weights are spec-frozen (specs/phase-4/contract.md §1) - no runtime override.
   A claim is DISPATCHABLE when: status non-terminal AND promotion_attempts<3 AND
   every depends_on[C] is terminal.
3. **Iterative-deepening tier gate** (`worker_budget.check_tier_gate`) - tier N needs
   all open claims at `evidence_tier_attempted >= N-1`. Broad cheap (T1) on every
   claim before any expensive (T3) on one. Structurally enforced by the PreToolUse hook.

## Tiers (evidence cost ladder)

| tier | operations | gate |
|---|---|---|
| 1 (cheap) | grep / strings / DIE / CTI read / decompile | none |
| 2 (medium) | emulation (malware-framework) / cross-ref tracing | all open claims `evidence_tier_attempted >= 1` |
| 3 (expensive) | VM detonation (vmr-shell) / Frida real-run | all open claims `evidence_tier_attempted >= 2` |

## Per-round loop (the orchestrator runs this each iteration)

1. `python scripts/priority_ratio.py` <ws> (or `--json`) -> ranked action queue (claim_id / action / score).
2. Dispatch the top claim(s), respecting `<=3 workers` + tier gate. Deviate from rank #1 only with a recorded reason in `reasoning`.
3. Workers gather evidence; verify (`verify-static-vs-dynamic`); update `claim-register.yaml` (status / `evidence_tier_attempted` / `promotion_attempts`).
4. Re-plan only on: verified finding / refutation via `claim_deps` / task_spec external update (§9 rule 4). Back to step 1.

## Dispatch format

```
[T<N> tools=<comma-separated>] claim <C-NN> <task description>
```
`hooks/worker_budget.py::parse_dispatch()` parses; `check_tier_gate()` enforces layer 3.

## Why this combo

- **RE cost asymmetry**: cheap ~1x, expensive ~100x; cheap evidence is highly informative (strings + DIE usually characterize the sample). -> broad cheap first.
- **Computed priority** beats free judgment on a wide-shallow claim DAG: it consistently fronts PRIMARY + high-leverage + cheap claims instead of whatever the LLM notices first, and it is auditable (the score breakdown is on disk).
- **Iterative deepening** prevents premature expensive ops before cheap exploration refines the picture - structurally, not heuristic-dependent.
- Rejected: A* (no admissible heuristic in RE), MCTS (rollout = full analysis, too expensive), full beam (wasteful for most claims).

## Competing hypotheses (v1.7) nest inside the priority

`need: model_selection` questions expand to K mutually-exclusive claims (`competitor_group`). They score `value=0.6` and accumulate evidence that prunes losers - an internal greedy tactic, not a third search algorithm.

recall_useful: pending
