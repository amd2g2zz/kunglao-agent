# design — issue-705-marl-architecture

## D1 — the agent dimension is additive, and the legacy key is the wall

`arm_key(family, recipe, verif, tier, agent_type=None)`. `agent_type`
falsy → the exact 4-dim string the repo has written since #539 WS1
(test_action_space_539 pins it; every golden that pins an arm key stays
byte-identical). `agent_type` present → `family|recipe|verif|tier|agent`.
Tier still buckets through `int(tier)` with the `0` fallback.

`family_of_action` splits on the FIRST `|`, so a 5-dim key is already
family-addressed for `Fold.family_mass` / `termination.alive` with no
change. A new `agent_of_action` reads the fifth segment (legacy keys →
`None`).

## D2 — the anchor is the transfer channel, not a pool merge

`cell_posterior` computes the anchor as
`family_mass(family) − local`. With agent-conditioned keys this is
ALREADY the cross-agent warm start: `family_mass` sums every cell of the
family — agent A's cell included — and the leave-one-out subtraction
removes only the *querying* cell. So agent B's cold cell borrows agent
A's evidence through the SHRINK_CAP (8.0 pseudo-observations) with no new
plumbing and no forced pooling.

One carve-out: the existing "legacy family-keyed cell pools into local"
tolerance applies to 4-dim keys only. For a 5-dim key the 4-dim cell of
the SAME arm stays in the anchor — it is shared prior, not this agent's
own evidence (owner: sharing via warm-start priors, not forced pooling).

## D3 — class-level negative knowledge

`signature_class(ws)` is a digest over the mined *structural* feature
tokens (`feature_prior.features_from_workspace` → `feature_tokens`), not
over the instance signature. Two workspaces with the same structural
shape (same obfuscator family, same target kind) collide; two instances
of the same binary at different loop phases do not. No mined features →
the inert `"unknown"` class (fail-open, never a fabricated bucket).

`record_negative` appends `marl-negative/1` rows:
`(signature_class, agent_type, method_family, tool_chain, fails)`.
`negative_pools(ws, families, *, agent_type=None, signature_class=None)`
reads back the shared store's rows for THIS workspace's class (or an
explicit class override — the cross-workspace read) — pooled across
agent types, because the whole point is that when one agent learns a
dead end the others inherit it — and returns duck-typed
`FeaturePool(success=0.0, failure=λ·fails)` per family.

Threading: `cell_posterior(..., negative_pool=)` and
`sample_method_family(..., negative_pools=)` add the failure mass to the
anchor face under the same single SHRINK_CAP as every other anchor
source, with an additive `negative_knowledge` receipt block. The
guaranteed effect is a HIGHER posterior β — a dead end is a failure
pseudo-count, never a deletion. The mean does NOT always fall: the
borrowed anchor's mean is `(BASE_ALPHA + s_anchor) / (BASE_ALPHA +
BASE_BETA + n_anchor)`, so for a cell whose own failures already sit
below that anchor mean the shrink can lift the mean slightly. The pin is
β-higher + receipt (and the ARM_FLOOR keeps the arm samplable), never
"mean always falls". Absent/empty → byte-identical draw.

## D4 — solve vs verification credit

`observe_settlement(ws, dispatch_id, credit, *, phi_delta=None,
credit_kind="solve")`. `credit_kind="solve"` is today's behavior
(bit-identical). `credit_kind="verification"` still matches the dispatch
row and still appends a settlement row (the audit trail must show the
verification happened) but the row carries `credit_kind: "verification"`,
and `fold()` treats it as inadmissible: it contributes to neither
success, failure, nor `n_pending`. Result dict gains `beta_updated:
bool` so the settlement hook can report the decomposition.

Why the fold, not the writer: the log is append-only and the credit IS
real (the verifier did the work) — dropping the row would lie about
history; folding it would poison the arm's solve posterior with
confirmation noise. Excluding it at the read face keeps both truths.

`strategy_store.warm_pools` applies the same admission filter, so the
cross-task store never warms an arm from verification-only evidence.

## D5 — solution broadcast is method-only

`broadcast_solution(ws, *, method_family, agent_type, claim, credit)`
appends one `posterior-store/1` row via the existing `append_store_row`
(holdout filter, fail-open telemetry, the guarded store root — all
inherited). The row carries the METHOD family, the agent type, the claim
ID, and the credit. The claim's *text* — the answer — never rides the
row. The test pins this: after broadcasting a proven claim whose text is
a distinctive literal, the store's serialized form contains the method
token and does NOT contain the answer literal.

## D6 — five registrations, one validate

Three spec deltas under the change; `openspec validate
issue-705-marl-architecture` exits 0. The RED tests in
`tests/test_marl_architecture_705.py` are derived from the Requirements'
Scenarios (spec → tests → impl), never reverse-engineered from the
implementation.
