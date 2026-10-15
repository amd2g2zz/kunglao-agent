# design — issue-695-recipe-arms

## D1 — the arm is a rider, never a key dimension

The #432 ruling stands: "a token names the APPROACH, never the tool
chain" — the tool chain may never enter the Q key. The recipe triple
therefore rides as COLUMNS on the existing (signature_hash,
method_family) observation spine (`runs/q-cell-log.jsonl`): the dispatch
row opens the same cell it always did, now carrying which tool-chain
arm it recommended, at what propensity, and where the arm came from.
Consumers key on the columns (the arm fold, the replay); the cell math
is untouched. The 4-dim `arm_key`'s `context_recipe` (facts_snapshot
etc., #539) is the dispatch CONTEXT recipe — deliberately different
concept, different field, different fold; the two never share a name or
a namespace (the module docstring pins the split).

## D2 — source semantics: sampled | declared | none (the #691 matrix at tool grain)

The recorded `recipe_source` names the arm's provenance under the
gate-time reconciliation (the anti-spoof posture: the sampler draw is
RECOMPUTED at the approval point from the fold — nothing the envelope
says can move it):

- **sampled** — the dispatch followed the policy: the envelope
  declared exactly the gate's own draw, or declared nothing and the
  sampler supplied the recommendation (day-one until a compose face
  threads recommendations into envelopes; still the policy's
  counterfactual, recorded against the dispatch);
- **declared** — the envelope named a recipe that deviates from the
  draw (or the sampler view is unavailable): an off-policy decision
  with its propensity logged for OPE (0.0 outside the arm support —
  the honest number, not a gap; null only for the genuine no-view gap);
- **none** — no family, no registered arms, or a sampler failure: the
  explicit-null gap row, byte-identical to pre-#695 (the triple's keys
  are emitted only when the view names a recipe).

Deviation (declared ≠ draw) emits exactly one `recipe_deviation` event
(registered in `event_taxonomy.EMIT_ACTIONS`) carrying declared,
sampled, propensity, the `registered` flag and the dispatch's
`agent-reasoning:` reason — recorded, NEVER rejected. An UNREGISTERED
`recipe_id` is recorded as declared with propensity 0.0 (the draw could
never have chosen it) and still never rejected: the 2026-10-14
amendment (no new rule gate) applies to tool choice verbatim.

## D3 — floor-not-delete: `weight = prior · max(θ, THETA_FLOOR)`

Cold start is a static prior with gravity: the registry's `prior` per
arm (hand-mined tier-chain / tools/_INDEX gravity, e.g. ghidra-headless
0.6 vs radare2 0.45 under static-decompile) is the day-one weight — a
prior with mass that data overturns, never a policy. The learned part
is θ, the Beta posterior mean over SETTLED recipe-credited rounds
(fractional split: success += r, failure += 1−r, the q_cells
convention). The floor: `θ_eff = max(θ, THETA_FLOOR)` (0.1 — the same
PARK posture as `termination.ARM_FLOOR`, kept local so the sampler face
never imports the termination face). An arm hammered by 30 straight
failures still samples at `0.1 · prior` — strictly positive mass,
samplable, revivable; arms are never deleted from the registry.

## D4 — agent dimension (owner comment 2026-10-15 on this issue, MARL #705)

Posteriors are per (recipe, agent type): `arm_weights(ws, family,
agent=…)` runs the agent-local solve counts at full weight, and the
peers' pooled mass enters as a LAMBDA-tempered (0.25, meta_arms)
warm-start prior — the pooled rows minus the local subset, so nothing
is double-counted, and a COLD agent still inherits its peers at the
tempered weight (warm start, never forced pooling). Only solve credit
updates the posterior: a settlement row carrying
`credit_kind: verification` (#705's decomposition, already on the
settlement spine) is recorded for the audit trail and excluded from the
fold — verification credit ≠ solve credit.

## D5 — credit attribution: the #678 trusted chain, ITT, narrative-blind

The settlement face is the ALREADY-TRUSTED `observe_settlement`
match-and-bank: the latest pending dispatch row for the claim carries
the recipe triple, and the banked settlement row copies it. Credit
lands on what the DISPATCH recorded (intention-to-treat) — the worker
may deviate from the recommendation (it is free; that is the design)
and the credit still banks against the declared/sampled arm the
dispatch carried, which is exactly the arm the policy can learn from.
The fold reads only these mechanically recorded rows; a worker-written
`steps:` narrative (the #881 tool_value source) is never opened — the
RED test plants a LYING narrative claiming a different arm and pins
that the bank ignores it.

## D6 — replay before any online switch (S2 shape)

`replay_report(ws)` reruns the CURRENT weights over recorded history
(the S2 shape the v0.1.6 plan used for families: rerun the sampler vs
the recorded choice, report the disagreement rate) and reports
arm-level separation: per-recipe mean settled credit and the argmax
arm per family. It is a pure read — no dispatch decision moves on it.
The online switch remains the v0.2 loop's (#50/#13) call, gated on
this offline evidence.

## D7 — fail-open telemetry, stable schema

Every recipe face degrades the same way: a sampler/fold/emit failure
is ONE rate-limited warn (error class) and the none gap — telemetry
never turns an ALLOW into anything else and never breaks the dispatch
observation, the settlement, or the producer. The q-cell OBS schema
stays `q-cell-obs/1`: the three recipe keys ride together with explicit
nulls inside, and only when the view names a recipe — every pre-#695
writer (`observe()`, reindex faces, tests seeding history) stays
byte-identical.
