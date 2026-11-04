# Proposal

## Why

The red-team layer currently binds **records**, not **execution**. `machine_check`
entries are self-reported JSON — the gate validates their shape and the
`passed` boolean but never re-runs the command; `verifier_integrity.calibration_check`
(the per-verifier anti-surrender floor) has **no production caller**; and
`rlvr.scalar` derives `oracle_backed_refutation` from the status word alone.
A lazy or noisy checker can therefore pass the gate without doing the work,
block PROVEN with an unbacked REFUTED, or flood the loop with non-issues. There
is also no critic face at all (`rlvr/direction.py` explicitly says no critic),
so method detours and ROI drift go unremarked. Because red-team output feeds
settlement, this is a trust hole in the learning loop.

The owner ruling (2026-11-04): red-team must do TDD and independent
reproduction; a successful reverse-engineering result must work in **both**
directions (reverse and forward), not one-way; it must not be led by the
rollout's narrative; it must not emit noise; it takes on **part** of the
critic role (method detour / poor ROI / drift / stagnation) but only for
obvious, material cases; and any critique must be **arbitrated** before it can
change anything or enter settlement.

## What Changes

- **TDD is mandatory**: every load-bearing conclusion carries an executable
  falsifier written RED first, then executed to GREEN. Artifacts live in the
  workspace at `runs/rt-tests/<claim>/` (test file + RED/GREEN log + command);
  a record without them cannot be CONFIRMED.
- **Bidirectional reproduction (claim-kind matrix)**:
  - reversible claims (decode/decrypt/encode/sign/replay): reverse **and**
    forward must both succeed and compose to byte-identity on the captured
    pairs; one-way success caps the verdict at `UNVERIFIED-WITH-GAP`.
  - detection/classification claims: perturbation stability + replay equality
    against captured inputs.
  - irreversible claims: replay-equivalence only, explicitly
    `UNVERIFIED-WITH-GAP` unless the mapping table grants an exception.
- **Unbacked REFUTED cannot block**: a REFUTED verdict must carry executed
  falsifier evidence (RED→GREEN + machine check). Without it the verdict
  degrades to `UNVERIFIED-WITH-GAP` and no longer blocks PROVEN.
- **Critique lane (limited critic role)**: `kind` ∈ {`method-detour`, `roi`,
  `drift`, `stagnation`}, triggered only for material cases (obvious drift or
  stagnation); every critique needs a falsifier/evidence and an impact claim.
  Non-material items are suppressed to telemetry (`critique_suppressed`) and
  never surface as findings.
- **Two-stage arbitration**: the oracle deterministically validates the
  critique's evidence and threshold; the orchestrator adjudicates
  accept/reject with a recorded decision row. Only `accepted` critiques may
  adjust method selection or enter settlement; unarbitrated or rejected
  critiques are inert.
- **Close the three known holes**: wire `calibration_check` into the
  settlement precondition; replay a sample of `machine_check` entries at
  settlement; bind `oracle_backed_refutation` to an actual oracle result.
- **Surrender is a distinct outcome**: a stop/refusal on an AUTHORIZED target
  without a session-bound wall and without route exhaustion is `surrender`,
  not `censored_env`; an out-of-scope refusal is the separate
  `refusal_out_of_scope` class; the dispatch carries the authorization
  context; a negative/impossible claim requires the route-attempt ledger. The
  reward/credit side is #986; the learning-measurement side is #987.
- **BREAKING**: reversible claims can no longer promote on a one-way
  machine check alone; an unbacked REFUTED no longer blocks PROVEN; critique
  rows without arbitration are ignored by settlement.

## Capabilities

### New Capabilities
- `redteam-verification`: the checker's evidence discipline — TDD RED→GREEN
  evidence in the workspace, execute-not-read reproduction, the bidirectional
  claim-kind matrix, and the REFUTED evidence bar.
- `critique-arbitration`: the limited critic lane and its two-stage
  arbitration (oracle validation + orchestrator adjudication), including the
  settlement filter that makes unarbitrated critiques inert.
- `rollout-surrender`: refusal/surrender as a distinct, observable outcome;
  authorization context at dispatch; evidence-backed route exhaustion. Tracks
  #986 (surrender outcome) and #987 (exhaustion is not a learning verdict).

### Modified Capabilities
- None (no pre-existing spec store; behavior is defined by this change's three
  new capability specs).

## Impact

- Agent contract: `agents/kunglao-redteam.md` (new TDD / bidirectional /
  critique / arbitration sections).
- Schemas/contracts: `references/schemas/machine_check_map.yaml`,
  `references/contracts/machine-check-contract.md` (new check kinds and the
  claim-kind matrix).
- Verification path: `scripts/kunglao_verify.py` (`machine_check_gate`),
  `scripts/replay_equivalence.py` or a new `scripts/rt_roundtrip.py` executor,
  `scripts/register_proven_gate.py` (REFUTED evidence bar).
- Settlement/learning: `scripts/verifier_integrity.py` (calibration wiring),
  `scripts/rlvr/scalar.py`, `scripts/rlvr/settlement_wire.py`,
  `scripts/rlvr/reward_signal.py`, `scripts/rlvr/episode_settle.py`,
  `scripts/rlvr/interruption.py` (surrender vs censored classification).
- Arbitration: `scripts/oracle_runner.py` / `scripts/oracle_cadence.py`
  (deterministic validation), orchestrator decision log and skill text.
- Telemetry: `scripts/event_taxonomy.py` (new words for arbitration and
  suppressed critiques).
- Tests: new command/contract pins plus the affected suites.
