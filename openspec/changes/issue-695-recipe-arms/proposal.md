# issue-695-recipe-arms — tool-chain recipe arms (the learned tool-choice substrate)

## Why

Issue #695: tool selection and tool-chain orchestration are first-class
actions of the controller, not static tables (owner 2026-10-11, closed
#667; owner 2026-10-14: tool value is context-dependent, no silver
bullet — the controller must learn which toolchain to plan per
situation, credited from outputs). The code state the issue verified:
the Q key has no tool dimension by policy ("a token names the APPROACH,
never the tool chain", #432); the `tool_sequence` rider column has no
writer; the #881 `tool_value` table attributes at CLAIM level from
worker-written `steps:` lines and pools context away on consumption;
the frozen model's own tool variance (the same claim dispatched four
times used 0 / ≥8 / ≥26 / ≥86 browser-MCP calls) is recorded nowhere.
Meanwhile the sibling substrate is in place: #691 logs family
propensity per dispatch, #678 makes settlement credit trusted, #690
settles at step grain, #705 decomposes solve vs verification credit.

## What Changes

1. **The arm registry** — `scripts/rlvr/recipe_arms.py`: a RECIPE arm =
   `{recipe_id, tool_class, invocation, artifact}` scoped to a method
   family, ≥3 arms per registered family (all 12 closed-vocabulary
   families), cold-start static prior with gravity (`prior` > 0,
   hand-mined from tier chains / tools/_INDEX faces) — overturnable by
   data, never the policy.
2. **The sampler** — `sample_recipe` draws proportional to
   `prior · max(θ, THETA_FLOOR)`: an arm's Beta posterior mean floored
   at 0.1 (the PARK posture) so a beaten arm keeps strictly positive
   mass, stays samplable, and revives on new success. Agent-scoped
   posteriors with LAMBDA-tempered warm start across agents (#705
   owner comment on this issue).
3. **Dispatch recording** — the q-cell dispatch row (the #691 spine at
   the tool grain) carries `{recipe_id, recipe_propensity,
   recipe_source: sampled|declared|none}`. The envelope's declared
   `recipe_id` is reconciled against the gate's OWN arm draw at
   dispatch time (anti-spoof); source=sampled means the dispatch
   followed the sampler (declared == draw, or the sampler supplied the
   recommendation), source=declared means a recorded deviation.
4. **Trusted settlement attribution** — `observe_settlement` carries
   the triple onto the settlement row: credit banks against the
   DISPATCH-RECORDED recipe (ITT via the #678 match-and-bank chain).
   No worker narrative is ever read (the #881 `steps:` anti-pattern
   stays dead). Only solve credit moves the arm posterior
   (`credit_kind: verification` rows are excluded from the fold).
5. **No new REJECT surface** — a deviation (declared ≠ draw) or an
   unregistered `recipe_id` is a recorded decision: one
   `recipe_deviation` event (registered EMIT_ACTIONS word) with the
   logged propensity, the sampler view, the registered flag and the
   dispatch's `agent-reasoning:` reason — the dispatch still passes.
6. **S2-shape replay** — `replay_report(ws)`: offline only, reruns the
   current weights over recorded history and reports arm-level
   separation (per-recipe mean settled credit + argmax per family) and
   the disagreement rate — the evidence demanded BEFORE any online
   switch (the v0.2 loop, #50/#13).

## Non-goals

- No online policy switch, no sampler enforcement — recommendation
  never restriction; the worker (frozen LLM) stays free and instrument
  availability is an annotation, never a rack trim (capture-refusal
  verdict).
- No tool chain in the Q key — `recipe_id` rides as columns on the
  existing (signature, family) spine; the 4-dim `arm_key`'s
  `context_recipe` dim is a DIFFERENT concept (dispatch context) and is
  untouched.
- No realized-toolchain gate: the worker's actual tool use stays #690
  step-grain diagnostics (`tool_call` telemetry), never a credit gate.
- No change to `method_families.yaml`, the #432 vocabulary gate, or any
  battery gate's return contract.

## Impact

- New: `scripts/rlvr/recipe_arms.py`; `tests/test_recipe_arms_695.py`.
- Extended (additive kwargs/keys only): `scripts/rlvr/q_cells.py`
  (`append_observation` recipe triple + boundary validation,
  `record_dispatch_observation` recipe view, `observe_settlement` carry)
  and `scripts/event_taxonomy.py` (`recipe_deviation`).
- Blast radius (GitNexus, `--repo kunglao-agent`): the three q_cells
  faces score LOW — their production callers (worker_budget_sinks
  `_qcell_record_dispatch`, scalar `_bank_q_cell_credit`, e2e
  checkpoints) pass keyword args that the additive signature keeps
  valid; every pre-existing writer stays byte-identical (recipe keys
  are emitted only when the view names a recipe).
