# Design — issue-684-planning-tier

## D1. The tier is vocabulary, not a controller

Same scope ruling as the original registry slice ("vocabulary +
operator metadata first; composition can follow"). The policy tier
registers the six candidate-set controls with cost / precondition /
proof-power / consumer / settleable + the same unimplemented ΔV-estimator
SIGNATURE stub every other action carries. Nothing samples the tier in
this change; the stale-plan detector keeps warning (it is now the
`policy.replan` trigger, named in the precondition, never a substitute
for taking the action).

## D2. Settleability as a spec flag

`ActionSpec.settleable: bool = False` — one field, default off, so no
non-planning entry can become settleable without saying so (the
`plan_segment` demotion and the `replan` move below change metadata,
never this default). The flag is the
registry's single answer to "does this action change the candidate
set?" and `planning_actions.record` consults it (an action outside the
tier is refused at the boundary — the ledger can never carry a worker
verb).

Why a flag rather than a level check: levels group the vocabulary;
settleability is the invariant. Today they coincide (all and only
`policy.*` entries are settleable) but the flag states the rule the
guardrail cares about directly, and a future settleable entry at
another level would not need a registry reshuffle.

## D3. Attribution: the producing step, resolved from the ledger

The guardrail: "a supersede that later refutes must be revocable
against the step that proposed it — the same escrow/revoke discipline
as evidence credit". The evidence-credit face
(rlvr/step_ledger.py) resolves the revoke target from the evidence
item's `step_ref` — the verifier that confirmed is never the revoke
target. This module mirrors it: `record()` stamps the caller-supplied
`step_ref` (the producing step — the dispatch/act that chose the
planning action); `revoke()` resolves that step FROM the ledger row
and refuses unknown ids and double revokes. The caller cannot point a
revoke at a convenient step.

## D4. Propensity rides the row

Policy actions are CHOSEN, so the sampling propensity is logged beside
the choice — the same additive-column posture as the transition ledger
(`incremental_reward.record_launch`): absent = unlogged (legacy
compatibility), present = float in [0, 1], illegal values refused at
the boundary. The consumption face (IS-weighted updates) lands with
the controller; the column exists so the data is never lost.

## D5. One ledger file, two schemas

runs/planning-actions.jsonl carries both planning-action/1 rows and
planning-revoke/1 rows, distinguished by the schema stamp (the
step_ledger convention: one file, schema-tagged rows, readers filter).
Append-only; revocation never edits the original row.

## D6. Fail-open everywhere

Every refusal is an explicit None + ONE warn trace (kunglao_log.warn):
non-settleable action, empty step_ref, illegal propensity, unknown
action id, double revoke. An unreadable/corrupt ledger line is skipped
by the readers, never a crash. Observability never breaks the caller.

## D7. plan_segment demotion

`plan_segment` moves from an orchestrator planning verb to a
worker-domain organizational verb (consumer `worker (plan authorship)`).
Rationale: the plan-first contract already makes planning the worker's
first act — the worker authors runs/plan-<KEY>.md. `plan_segment`
sequences the worker's OWN plan steps; it never touches the claim
economy. Its precondition is rewritten accordingly; level and cost are
unchanged (it is still an organizational, zero-proof-power verb).
