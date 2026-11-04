# Design

## Context

See `proposal.md` — Why. Current mechanics that shape this design:

- `scripts/kunglao_verify.py:600-679` validates `machine_check` **structure**
  and the `passed` boolean; it never re-executes the command.
- `scripts/verifier_integrity.py:226` defines `calibration_check` but no
  production module calls it (tests only).
- `scripts/rlvr/scalar.py:1185-1187` derives `oracle_backed_refutation` from
  `status ∈ {NEGATIVE, REFUTED}` — no oracle participates.
- `scripts/register_proven_gate.py:464` blocks PROVEN on any REFUTED with no
  evidence requirement.
- No critic face exists (`scripts/rlvr/direction.py:7` — "NO critic").
- Reusable infrastructure: `scripts/replay_equivalence.py` (execute + schema +
  mutation-must-red), `scripts/eval_targets.py` (`replay-roundtrip` oracle),
  `scripts/oracle_runner.py` / `scripts/oracle_cadence.py`,
  `references/schemas/machine_check_map.yaml` (`boundary_type_map`).

## Goals / Non-Goals

**Goals:**
- Bind verification to **executed** evidence, not self-reported records.
- Make one-way success insufficient for reversible claims.
- Make an unbacked REFUTED unable to block promotion.
- Add a default-silent critic lane whose output is inert until arbitrated.

**Non-Goals:**
- Replacing the LLM checker with a deterministic solver.
- Running dynamic analysis on the host (Hard prohibition #5 stands).
- Retroactively re-verifying already-promoted claims.
- Learning the critique threshold from data (policy constants only, matching
  the `rlvr` ZERO LEARNING POSTURE).

## Decisions

### D1. TDD artifacts live in the workspace under `runs/rt-tests/<claim>/`
Each claim gets `test.py` (or a lane-appropriate falsifier), `red.log`,
`green.log`, and `manifest.json` (test sha256, log sha256s, command, inputs
digest). Rationale: the evaluation unit is the black-box workspace; repo
`tests/` would couple every engagement to the repo and cross-contaminate
claims. Alternative rejected: embedding test code in the red-team markdown —
unexecutable and unhashable.

### D2. A single executor emits a re-checkable manifest
A new `scripts/rt_roundtrip.py` (extending the `replay_equivalence` grammar,
consumed not rebuilt) runs the falsifier and the bidirectional comparison and
writes the manifest. The gate validates the manifest; settlement re-executes a
policy-sampled subset (`MACHINE_CHECK_REPLAY_SAMPLE`) and fails the affected
credit when a sampled entry does not reproduce. Alternative rejected: trust the
JSON (current hole); full re-execution of every check (cost).

### D3. The claim-kind matrix is keyed on `claim_kind`, not `boundary_type`
`references/schemas/machine_check_map.yaml` gains `required_checks` per
`claim_kind` (the map's existing first section). `boundary_type` is a
container that spans mixed kinds — `observation` covers both `decryption_key`
(reversible) and `numeric`/`static_constant` (not) — so keying there would
mis-gate half the claims. The matrix:

- `decryption_key` → `tdd_red_green` + `round_trip`.
- `input_bypass` → `tdd_red_green` + `positive_negative_control`.
- `detection` and `classification` (NEW kinds, added to the map beside the
  existing eleven) → `tdd_red_green` + `perturbation_stability` +
  `replay_equality`.
- `static_constant` / `numeric` / `string` / `structure` → `tdd_red_green` +
  their existing `check_type` (+ `replay_equality` when captured pairs exist).
  These are deterministic byte checks, NOT gap-only: they are verifiable
  without a round trip.
- `negative_result` → `tdd_red_green` + `bounded_search`.
- `capability` → `tdd_red_green` + `vm_execution`.
- `cti_correlation` / `attribution` / `external_source` → the existing
  `machine_check: none` exception path; this is the ONLY waiver of TDD, and
  the record must declare `claim_kind` + reason per the mapping table.

A claim whose kind has no matrix row is fail-closed: `UNVERIFIED-WITH-GAP`.
The matrix key is declared on the verification record itself: a `claim_kind:`
field validated against the map (the existing exception entry's `claim_kind`
must match it); facts and claim-register entries keep their `boundary_type`,
which is NOT used for the matrix.
Rationale: one source of truth for the agent contract, the verifier gate, and
the tests.

### D4. REFUTED requires the same evidence bar as CONFIRMED
`register_proven_gate` parses the latest red-team record through the same
`machine_check` + TDD validator. An unbacked REFUTED is downgraded to
`UNVERIFIED-WITH-GAP` for promotion purposes (the record itself is not
rewritten; the gate's effective verdict changes). Alternative rejected:
letting any REFUTED block blindly (current false-negative pressure).

### D5. The critique lane emits machine-readable rows, not prose only
The red-team report gains `## CRITIQUE` (human) and
`runs/critiques/<claim>.json` (machine): `{id, claim, kind, evidence,
falsifier, impact, threshold_met}` with `kind ∈ {method-detour, roi, drift,
stagnation}`. Non-material observations never reach this file; they go to
`critique_suppressed` telemetry. Rationale: arbitration needs a stable unit;
prose cannot be filtered or joined.

### D6. Two-stage arbitration with deterministic criteria and bounded effects
- Oracle stage: a deterministic validator (`scripts/critique_arbiter.py`,
  or an `oracle_runner` entry) checks evidence presence and the kind's
  policy-constant criterion, then writes an `oracle_validation` row:
  - `drift`: the same failure class repeats ≥ `DRIFT_REPEAT_MIN`, or zero
    progress across the observation window.
  - `stagnation`: no new claim/fact progress over `STAGNATION_TICKS`.
  - `roi`: a NAMED cheaper registered path with the same outcome class and a
    measured cost ratio ≥ `ROI_RATIO_MIN`.
  - `method-detour`: a NAMED registered simpler path with the same outcome and
    a step ratio ≥ `DETOUR_STEPS_MIN`.
- Orchestrator stage: records `accept`/`reject` + reason in the decision
  ledger, keyed by the same `arbitration_id`.
- Effect is bounded: an accepted critique applies the same kind of sampler
  weight demotion used by the termination floor (`ARM_FLOOR`), never a
  free-form credit change; the settlement row carries the `arbitration_id`
  and the recorded delta.
Rationale: the owner's ruling; alternatives rejected: oracle-only (no
accountable judgment), orchestrator-only (no deterministic floor).

### D7. Settlement consumes only accepted, arbitrated critiques
`rlvr/settlement_wire` and `rlvr/scalar` read `runs/critiques/*.json` joined to
the arbitration rows; unarbitrated/rejected critiques contribute nothing. In
the same pass: `calibration_check` becomes a settlement precondition with
per-verifier blocking (a one-sided verifier blocks its own claims even in a
mixed corpus) and a fail-closed wrapper on scan error (the module's own
telemetry posture stays fail-open), the machine-check replay sample runs, and
`oracle_backed_refutation` is computed from an actual oracle result recorded
on the artifact (not the status word).

### D8. Telemetry words are registered once
`critique_emitted`, `critique_suppressed`, `critique_oracle_result`,
`critique_arbitrated` are added to `scripts/event_taxonomy.py`; no ad-hoc
strings.

### D9. Execution venue: host-safe offline computation vs sample execution
Falsifiers that only transform captured bytes offline (hash/parse/decrypt in
python/xxd) are host-safe. Anything that EXECUTES the target sample must use
the VM channel (`x64dbg` `connect_remote`, frida, or the lane emulator); the
host prohibition stands. No VM channel → `UNVERIFIED-WITH-GAP`, never a host
run. This keeps the TDD requirement compatible with the agent's hard
constraint.

### D10. Episode disposition algebra: one object, seven evidence gates, one precedence
Every rollout produces one disposition row (`runs/disposition/<episode>.json`,
mirrored into the unified ledger) carrying `{episode_id, claim, disposition,
evidence_refs, route_ledger_ref, wall_ref, authorization_ref,
strategic_action, propensity, budget, ts}`. The seven dispositions and their
gates are in the capability spec. Assignment is a total order, first match
wins: `SOLVED` > `OUT_OF_SCOPE` > `CENSORED_ENV` > `ATTEMPTED_EXHAUSTED` >
`INFRA` > `FAILED` > `SURRENDER`.

Legacy mapping (published and tested; no retro-rewrite):
- session ladder `terminal` (exit 0) with a verifier pass -> `SOLVED`; exit 0
  without a pass -> `FAILED` (unverified completion);
- `censored_env` -> `CENSORED_ENV`;
- `agent_death` (timeout_kill / nonzero_exit / liveness_lost / unknown_exit)
  -> `FAILED`;
- a per-act `BLOCKED` outcome aggregates into `INFRA` when it terminates the
  episode; a per-act `strategy` outcome aggregates upward.
The per-act outcome stays per-act (one episode has many acts) and aggregates
into the episode disposition — it is never derived from it.

Declaration surfaces (named, so classification does not guess): the
authorization/engagement context is a `task_spec` field declared at intake and
copied into the dispatch envelope; a dispatch without it is not authorized.
The route-attempt ledger is `runs/rt-tests/<claim>/routes.json` (declared
routes, per-attempt command/artifact, fixed budget, reproducibility). The
declared routes per claim kind live in
`references/schemas/machine_check_map.yaml` (`routes:` beside
`required_checks`); the fixed budget is the policy constant
`ROUTE_ATTEMPT_BUDGET`, recorded in the ledger.

### D11. Strategic action and externally checkable stopping
`FIGHT` / `BYPASS` / `INVEST` are recorded with a propensity before
termination (the vocabulary exists in `scripts/action_space.py:28-38` but is
currently uncomposed); an episode with no recorded action is `SURRENDER`.
Termination is allowed only on ledger exhaustion, a corroborated wall, or the
budget; surrogate early-stop signals are banned because within-task
early-failure prediction is near chance (the literature in #988). This turns
the weak-stopping-signal failure into an externally checkable state machine.

### D12. One disposition, four consumers
Reward, measurement, learning, and settlement read the same disposition:
`SOLVED` -> positive (oracle lock); `ATTEMPTED_EXHAUSTED` -> capability-gap
record, no strategy credit; `SURRENDER` -> credit stays inside the declared
[0,1] rails (0.0 without reproducible evidence) AND the episode enters
strategic-action learning as a failure outcome and stays in the capability
denominator — it is not a negative scalar; `CENSORED_ENV` -> explicit
censoring (excluded from strategy learning, censoring rate reported);
`OUT_OF_SCOPE` / `INFRA` / `FAILED` -> separate reporting, no strategic-choice
signal. Ownership: this change owns the disposition object, the classifier,
the strategic action/stopping, and the consumer mapping CONTRACT; the
reward-meter and denominator implementation live under #986/#987; the default
posture under #985.

## Risks / Trade-offs

- **Re-execution cost** → sampled replay + input-digest cache; the sample size
  is a policy constant.
- **Stricter gates may strand claims** → the mapping-table exception list and
  the explicit `UNVERIFIED-WITH-GAP` state make the failure legible; no silent
  pass.
- **Critique inflation** → default silent, evidence bar, oracle threshold, and
  orchestrator adjudication each independently suppress noise.
- **Oracle unavailable** → critiques stay unarbitrated and therefore inert
  (fail-closed for adjustment; the rollout itself is unaffected).
- **Verifier identity for TDD artifacts** → the manifest is bound to the
  verifier identity header (existing `#825` machinery); no new identity system.

## Migration Plan

1. Schema + contract: matrix, new check kinds, agent contract v2.
2. Executor + gate: `rt_roundtrip.py`, `machine_check_gate` v2, REFUTED bar.
3. Critique lane + arbitration rows + telemetry.
4. Settlement wiring: calibration precondition, replay sample, oracle binding.
5. Documents/tests; `deploy-manifest.yaml` last.
Rollback: revert this change's commits; existing claims keep their prior
promotions (no retroactive rewrite), new promotions fall back to the old gate
only if the change is reverted as a whole.

## Open Questions

- The replay sample rate (policy constant) — can be tuned after the first
  campaign; it does not change any spec scenario.
- Whether arbitration rows live in `claims_store` or the unified ledger — an
  implementation choice; the spec only requires a recorded, traceable decision.
