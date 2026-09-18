# issue-234-obstacle-ladder — target/attack-surface ladder: strategy fan-out for obstacle claims

## Why

Issue #234: the promoted obstacle claim is a ONE-LINER statement
(`scripts/failure_analysis_gate.py:579`) — samplable by TS but not actionable
(no worker knows what strategy to execute from an obstacle description). The
two recovery ladders (method-ladder / env-ladder, printed at
`scripts/ask_for_direction_gate.py:590-594`) are tool-failure-shaped; there is
no vocabulary for TARGET-imposed obstacles. And the DLQ 3-strike family is a
dead precondition: `promotion_attempts` is seeded at promotion
(`scripts/failure_analysis_gate.py:577`) but has NO live writer anywhere
(#146 removed it from the arming predicate for exactly that reason), so
`dead_letter.scan` / `check_promotion_attempts` can never fire.

## What Changes

1. **Third ladder type — target/attack-surface ladder** (new module
   `scripts/target_ladder.py`, rides the ladder primitive — no new organ):
   3 levels (T1/T2/T3, mirroring the L1/L2/L3 shape of
   `infeasible_proposal.LADDER_LEVELS`), rungs enumerated per obstacle class
   in MECHANISM FAMILIES (interception-class: hooking / repackaging /
   ca-install / proxy-interposition — the issue's example, verbatim). Levels
   are mechanism-family distinct BY CONSTRUCTION; a walked ladder with two
   same-family rungs is INVALID. Instrument availability is an annotation on
   a rung, never a filter. The vocabulary is analysis targets and attack
   surfaces — NOT tool failures.
2. **Obstacle settlement precondition (write-side gate, #236 R3 shape)**: an
   obstacle claim (`origin: failure-obstacle`) cannot settle CONFIRMED
   (register status PROVEN = "really can't") in `kunglao_record.claim_migrator`
   without its target ladder walked (no level gaps, no family repeats) AND a
   non-empty exhaustion inventory — the exhaustion standard, same shape as the
   DEFERRED inventory (`infeasible_proposal.file_proposal`). Rejection carries
   a NAMED reason (`TARGET LADDER GATE: ...`). REFUTED stays ungated — the
   #233 path-scoped closure standard depends on it.
3. **Inventory seeds strategy claims (fan-out)**: each inventory entry
   auto-registers a sibling claim — `origin: obstacle-alternative`,
   `obstacle_for` edge to the parent obstacle claim, `answers_question`
   inherited, `depends_on` edge into `claim_deps.yaml` (same construction as
   `_promote_obstacle_claim`) — immediately TS-samplable (OPEN + non-terminal
   = `priority_ratio.is_open`). Minting is idempotent per
   (obstacle_for, ladder_family). The settlement gate additionally defects an
   inventory entry whose sibling was never minted, so exhaustion means the
   alternatives are registered, not just listed.
4. **Wire the 3-strike**: `dead_letter.record_dispatch_failure(ws, claim_id)`
   is the live writer the family lacked — increments `promotion_attempts` on
   the claim and, at >= 3 strikes, escalates to the charter MUST-ASK lane
   (`blockers/must-ask-<claim>.md` + the `must_ask` event, status untouched —
   review F6: a synchronous DEAD flip would preempt the ask gate;
   `mark_dead` stays the explicit post-mortem face). Wired at the
   dispatch-failure path: `hooks/worker_budget_sinks.post_check` (the Agent
   PostToolUse completion sink) increments when the finished worker's
   terminal status is a failure (failed/blocked/error — not done). Fail-open:
   any error warns to stderr, never breaks post_check.
5. **Dual-face enforcement (review F1)**: the hook-side PROVEN backstop
   (`compare_register_change_proven_gate`) enforces the same ladder
   requirement on the direct-register-edit lane it was built to police —
   the settlement gate is enforced on BOTH faces (#15/#78 policy).
6. **Class authority (review F2)**: the obstacle class is pinned on the
   promoted claim at promotion (`--obstacle-class`); settlement and mint
   validate the artifact's declared class against the claim-pinned one
   (mismatch/unpinned/undeclared = fail-closed defect).

## Design Rulings (from the issue)

- Rides the ladder primitive: extends vocabulary, adds no new organ.
- Overthinking bounded WITHOUT new stopping math: 3 levels, siblings inherit
  the attempts<3 cap, any DEFERRED still requires the V-curve-flat
  precondition (`scripts/infeasible_signal.py`). Continue/stop emerges from
  the claim economy.
- Same-prior correlation risk is mitigated by construction-level family
  distinctness; the residual risk is accepted and red-teamed at obstacle
  settlement (the PROVEN path already forces the red-team chain — #825).

## Impact

- New: `scripts/target_ladder.py`, `tests/test_obstacle_ladder.py` (fast),
  `tests/test_obstacle_ladder_integration.py` (gate/registry integration leg).
- Modified: `scripts/kunglao_record.py` (one fail-closed gate block),
  `scripts/dead_letter.py` (the writer + must-ask escalation),
  `hooks/worker_budget_sinks.py` (one fail-open call),
  `hooks/worker_budget_gates.py` (F1 dual-face backstop),
  `scripts/failure_analysis_gate.py` (F2 class pinning at promotion),
  `tests/_tiers.py` (registry entries), `scripts/README.md` (catalog).
- Out of scope (issue): VoC / closure pricing (v0.2 #12); options / QD archive
  formalization (v0.2 #59); execution-layer competence (toolbox axis). Also
  per wave plan: #241 dispatch-time granularity gate, #249 STALLED routing.
