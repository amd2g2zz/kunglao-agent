# Proposal: issue-684-planning-tier — claim-economy changes become settleable actions

## Why

Issue #684: `scripts/action_space.py` registered 18 verbs and only two
touched planning — `plan_segment` (produce plan text) and `replan`
(a drift nag the policy never took). Meanwhile the codebase already
ships a full claim-economy control surface that was never a CHOSEN
action: `mint_split_claims` (mechanical split), hypothesis-arm minting,
epistemic-claim minting, PARK + wake_condition, SUPERSEDED +
superseded_by, claim_deps edge edits, and the stale-plan detector that
fired 62x in one session without "revise the plan" ever being an action
the policy could take and be credited for.

A live workspace carried 23 claims of which 12 were hypothesis arms —
the plan IS the claim economy. With mint / split / supersede / park /
rewire outside the vocabulary, the plan was fixed at intake and the
policy could only permute it: a bandit over a frozen menu, not
planning. Selecting from the candidate set and CHANGING the candidate
set are separate, unmeasured layers; only the first was registered.

## What Changes

- **The policy tier**: `action_space.py` gains a `POLICY` level with six
  settleable actions — `mint_arm` (hypothesis arms as claims),
  `split_claim` (granularity fan-out), `supersede` (successor
  replacement), `park` (DEFERRED + wake_condition), `rewire_deps`
  (claim_deps edges), `replan` (global_plan re-derivation; moved from
  orchestration, where it sat unused). Every entry REUSES the existing
  mechanism by reference — no new semantics, the tier makes the
  mechanisms choosable.
- **`ActionSpec.settleable`**: a new boolean on the spec (default
  False). Settleable actions ride the escrow/revoke attribution
  discipline: recorded with their producing step and propensity,
  revocable against that step.
- **`scripts/planning_actions.py`**: the recording face —
  `record()` appends a planning-action/1 row (action, step_ref,
  claim_ref, propensity) to runs/planning-actions.jsonl; `revoke()`
  appends a planning-revoke/1 row naming the action's PRODUCING step
  (resolved from the ledger — the caller never points the revoke
  target). Refusals are explicit (None + one warn, fail-open).
- **`plan_segment` demoted**: from an orchestrator planning verb to a
  worker-domain organizational verb (consumer `worker (plan
  authorship)`) under the plan-first contract — it sequences the
  worker's own plan steps, never the candidate set.

## Non-goals

- No controller / argmax policy that actually SAMPLES the tier (the
  estimators stay stubs; composition is the v0.2 controller's job).
- No settlement consumption of planning actions yet (pricing revoked
  actions / closing escrow lands with the controller).
- No new mint/split/park/supersede machinery — every mechanism is
  referenced, never rebuilt.
- No change to rank output: the frozen byte-equivalence capture stays
  green (the claim-category table is untouched).

## Impact

- Affected: `scripts/action_space.py`, new
  `scripts/planning_actions.py`, `tests/test_planning_tier_684.py`
  (new), `tests/test_action_space_12.py` (vocabulary pin updated).
- Consumers: `priority_ratio` (imports the category table — untouched),
  `tests/_tiers.py` (new module registered FAST), scripts/README.md
  catalog + tools/_INDEX.ext.yaml + deploy-manifest (new script
  registered).
- Risk: LOW — additive vocabulary; the registry assert moves 18 → 23
  and the orchestration set loses `replan` (no other consumer of the
  orchestration.replan key).
