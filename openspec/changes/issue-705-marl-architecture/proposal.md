# issue-705-marl-architecture — agent-conditioned Q, knowledge transfer, agent-level credit

## Why

The RL layer is SMDP: workers are stateless tools. One global Q-cell per
`(state_signature, method_family)`, credit banked per `dispatch_id`, no
agent identity anywhere on the learning surface. Four concrete failures
follow from that (issue #705):

1. **No knowledge transfer.** Worker A learns `hypothesis-falsification`
   works for OLLVM; Worker B starts from Beta(1,1) anyway.
2. **No agent-level credit.** Settlement credits are dispatch-scoped —
   the loop cannot learn *which agent is good at what*.
3. **No cross-agent experience reuse.** A solved claim informs no other
   agent; a failed tool chain is retried by every agent.
4. **Planning is peer-blind.** Workers plan from claim context only.

Owner ruling (2026-10-15): **MARL over SMDP.** Rationale — "一个 subagent
学会了，其它没有必要从头开始学". Learning is project-scope (the RE
domain), generalizes (not case-specific), and does not overfit (learned
posteriors, never a hand-written rule table).

## What Changes

1. **Agent-conditioned Q (`agent-conditioned-q-705`).** `arm_key` gains an
   optional fifth dimension `agent_type`: `family|recipe|verif|tier|agent`.
   A `None` agent keeps the legacy 4-dim key byte-identical (the
   determinism wall). Each agent type then addresses its OWN Beta cell;
   every other agent's mass at the same family rides the SHRINK-capped
   anchor — knowledge flows through the prior, never through forced
   pooling.

2. **Knowledge transfer protocol (`knowledge-transfer-705`).** Three
   faces, one module `scripts/rlvr/marl.py`:
   - **Warm-start inheritance** — agent B's anchor includes agent A's
     evidence for a matched family (the anchor is family-aggregate minus
     the querying cell, so cross-agent mass is inherited by construction).
   - **Negative knowledge (class level)** — failed tool chains record per
     `(signature_class, agent_type, method_family)`, never per instance.
     The class is a digest over the mined *structural* feature tokens, so
     the record generalizes. Read back as failure mass that raises the
     arm's β (a dead end is a failure pseudo-count, never a deletion —
     the mean need not fall for a cell whose own failures already sit
     below the anchor mean; see design D3) and rides an additive receipt
     block under the one SHRINK_CAP.
   - **Solution broadcast (method level)** — a PROVEN claim's METHOD enters
     the shared posterior store. The answer/claim text never rides the
     row; other agents may use it as a prior but must still verify.

3. **Agent-level credit (`agent-credit-705`).** `observe_settlement`
   decomposes into `solve_credit` vs `verification_credit`. Only solve
   credit is admissible to the Beta posterior; verification credit is
   recorded (audit trail) but excluded from the fold — verification
   confirms existing knowledge, it does not produce it.

4. **Planning stays learned, not ruled.** Workers consult the Beta
   posterior (Thompson Sampling) at the planning entry — the
   "feature → methodology" mapping is learned from outcomes. No rule
   table is introduced; anti-overfit is structural (TS keeps exploring,
   ARM_FLOOR keeps every family samplable).

## Non-goals (recorded)

- **Peer-progress messaging between live workers.** The transfer is
  through the posterior/store (read at planning entry), not a live
  communication channel. The five sub-decisions of Orchestration Traces
  (spawn/communicate/…) beyond credit are out of scope.
- **Per-instance negative memory.** Negative knowledge is deliberately
  class-level; recording instance-identity failures would reintroduce the
  overfit the ruling forbids.
- **Rewriting the existing 4-dim arm-key rows.** Old rows keep folding
  exactly as before (the dual-write tolerance the repo has used since
  #539 WS1).

## Extends / Changes

- Extends #686 (crystallization → shared learned posteriors)
- Extends #695 (recipe arms → agent-conditioned recipe arms)
- Changes #690 (step grain → agent-level step credit)
