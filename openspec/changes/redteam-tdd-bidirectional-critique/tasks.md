# Tasks

## 1. Schema and contract

- [ ] 1.1 Add `required_checks` and `routes` per `claim_kind` in `references/schemas/machine_check_map.yaml` (keyed on `claim_kind`, never `boundary_type` — `observation` spans reversible and non-reversible kinds) and add the `detection` + `classification` kinds beside the existing eleven; verify a parser test that every claim kind resolves to a non-empty check list and route list, and unknown kinds fail closed
- [ ] 1.2 Add the `tdd_red_green`, `round_trip`, `positive_negative_control`, `perturbation_stability`, and `replay_equality` check kinds to the contract doc and the validator's accepted-kind set; verify the map/contract parity test passes
- [ ] 1.3 Rewrite `agents/kunglao-redteam.md` core rules: mandatory TDD (RED→GREEN under `runs/rt-tests/<claim>/`), executed reproduction, bidirectional rule with the claim-kind matrix, REFUTED evidence bar, evidence-bearing findings; verify the agent-contract sync test passes
- [ ] 1.4 Write the claim-kind matrix into both the agent contract and the machine-check contract, and verify a docs-parity test guards the two copies
- [ ] 1.5 Add the record-level `claim_kind:` declaration to the verification-record schema and the agent contract (validated against the map; the exception entry's kind must match); verify missing/unknown kinds fail closed and the declared kind selects the correct matrix row

## 2. Executor and verification gate

- [ ] 2.1 Add `scripts/rt_roundtrip.py`: run a falsifier RED→GREEN and a bidirectional round-trip, refuse zero captured/matched pairs, emit `manifest.json` (test sha, log shas, command, input digest, venue); verify unit tests for RED detection, GREEN pass, one-way failure, zero-pair refusal, and mutation-must-red
- [ ] 2.2 Extend `scripts/kunglao_verify.py:machine_check_gate` to require the matrix's `required_checks` for the claim's `claim_kind` and to validate the `rt-tests` manifest; verify a reversible claim with a one-way check yields overall PARTIAL with record verdict `UNVERIFIED-WITH-GAP`, and a round-trip record yields VERIFIED
- [ ] 2.3 Harden both REFUTED paths: `scripts/register_proven_gate.py` and the `scripts/kunglao_verify.py` L2 branch (`:991-992`) must apply the TDD + machine-check evidence bar; verify PROVEN is allowed over an unbacked REFUTED, blocked over a backed one, and L2 reports an evidence gap rather than REJECTED
- [ ] 2.4 Add the execution-venue rule (host-safe offline computation vs VM-channel sample execution) to the executor and the contract; verify a sample-executing falsifier without a VM channel returns `UNVERIFIED-WITH-GAP`
- [ ] 2.5 Add the perturbation-stability executor (one-byte perturbation at N offsets, policy-constant pass rate) and verify green plus below-threshold cases
- [ ] 2.6 Document the new evidence contract in `references/contracts/machine-check-contract.md` and `agents/kunglao-redteam.md` (the RT-record section); verify the docs selection tests pass

## 3. Critique lane and arbitration

- [ ] 3.1 Add the critique row schema and writer for `runs/critiques/<claim>.json` (kind, evidence, falsifier, impact, threshold_met) and the suppression path (`critique_suppressed`); verify unit tests for the material-kind filter and the evidence bar
- [ ] 3.2 Add `scripts/critique_arbiter.py`: deterministic per-kind checks — drift repeat count, stagnation window, ROI named-path + cost ratio, detour named-path + step ratio — writing an `oracle_validation` row; verify each kind's accept/reject threshold
- [ ] 3.3 Add the orchestrator adjudication record (accept/reject + reason + `arbitration_id`) and the accepted-state transition; verify an oracle-validated but orchestrator-rejected critique cannot become accepted
- [ ] 3.4 Implement the bounded effect: an accepted critique applies only the sampler-weight demotion at `ARM_FLOOR` and records the delta with its `arbitration_id`; verify a free-form credit change is impossible
- [ ] 3.5 Register the telemetry words (`critique_emitted`, `critique_suppressed`, `critique_oracle_result`, `critique_arbitrated`) and verify the event-vocabulary suite passes
- [ ] 3.6 Document the critic lane (limited kinds, default silence, two-stage arbitration, bounded effect) in the agent contract and the orchestrator skill; verify the contract-sync tests pass

## 4. Settlement wiring

- [ ] 4.1 Wire `verifier_integrity.calibration_check` into the settlement precondition with per-verifier blocking (a one-sided verifier blocks its own claims even in a mixed corpus) and a fail-closed scan-error path (the module's telemetry posture stays fail-open; the settlement wrapper does not); verify both cases
- [ ] 4.2 Add the machine-check replay sample at settlement (`MACHINE_CHECK_REPLAY_SAMPLE` policy constant) and verify a tampered entry fails the affected credit while an untouched corpus is byte-identical
- [ ] 4.3 Bind `oracle_backed_refutation` to an actual oracle result on the artifact (not the status word) and verify a REFUTED artifact without an oracle result earns no trace credit
- [ ] 4.4 Filter settlement critiques to accepted + arbitrated rows joined by `arbitration_id`, and verify unarbitrated/rejected critiques change no credit
- [ ] 4.5 Document the settlement changes in `references/contracts/` and the RLVR README; verify the docs selection tests pass

## 5. Disposition object and classifier

- [ ] 5.1 Add the disposition schema (`runs/disposition/<episode>.json` + the unified-ledger row) with the seven dispositions and evidence references; verify schema tests for every field
- [ ] 5.2 Add the single classifier with the seven evidence gates, the total precedence, and the fall-to-next rule; verify the full matrix (solve, refusal, crash/timeout, wall, ledger exhaustion, out-of-scope, BLOCKED)
- [ ] 5.3 Add the `task_spec` authorization field and copy it into the dispatch; verify an authorized refusal is `SURRENDER` and an out-of-scope refusal is `OUT_OF_SCOPE`
- [ ] 5.4 Emit the registered disposition event and verify the event-vocabulary suite passes
- [ ] 5.5 Document the disposition object and its gates in the skill and agent contract; verify the contract-sync tests pass
- [ ] 5.6 Publish and test the legacy→disposition mapping table (session ladder terminal/censored_env/agent_death and the per-act outcomes); verify no retro-rewrite and no per-act derivation

## 6. Strategic action and stopping

- [ ] 6.1 Record `FIGHT` / `BYPASS` / `INVEST` plus propensity before termination and map an absent action to `SURRENDER`; verify both cases
- [ ] 6.2 Add the route-attempt ledger (`runs/rt-tests/<claim>/routes.json`) validated against the per-claim-kind routes and `ROUTE_ATTEMPT_BUDGET`; verify a missing ledger cannot yield `ATTEMPTED_EXHAUSTED`
- [ ] 6.3 Enforce externally checkable stopping (ledger, wall, budget only); verify a surrogate early-stop signal cannot terminate a rollout

## 7. Consumers

- [ ] 7.1 Define the reward mapping CONTRACT (`SOLVED` positive; `SURRENDER` 0.0 within the [0,1] rails plus a strategic-action failure outcome; `ATTEMPTED_EXHAUSTED` no strategy credit; `CENSORED_ENV` explicit) and verify the mapping; the meter implementation belongs to #986
- [ ] 7.2 Define the measurement mapping CONTRACT (per-disposition denominators + process metrics) and verify it against #987; the policy implementation belongs to #987
- [ ] 7.3 Map the disposition into learning signals (capability gap vs negative choice vs censoring exclusion) and verify no learning verdict comes from a single episode
- [ ] 7.4 Wire the default posture (supply/protection ON or arm-declared, per #985) and verify the arm matrix declares the switches

## 8. Integration checks

- [ ] 8.1 End-to-end: a reversible claim with TDD + round-trip + accepted critique settles with traceable arbitration; verify the run emits the expected rows
- [ ] 8.2 End-to-end: a claim with one-way success and a noisy critique (no evidence) cannot promote and the critique is suppressed; verify the verdict and telemetry
- [ ] 8.3 Regenerate `references/_INDEX.yaml` and `deploy-manifest.yaml` (manifest last); verify `deploy_manifest.py --verify` exits 0 and its reported entry count matches the regenerated manifest (the two new scripts raise it above the current 643)
