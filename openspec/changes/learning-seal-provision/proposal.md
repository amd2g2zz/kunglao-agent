# Proposal

## Why

The learning channel's HMAC seal (#799) shipped complete but unarmed in
production: no `~/.claude/kunglao-learning.key` existed, so every
reward-bearing record rode legacy and the startup face warned
`learning channel UNSEALED` on every process. The 2026-11-05 workspace
audit (issue-1005) names the unarmed channel an explicit blocker — the
three surviving exploit families (launch-stash Φ inflation,
step-credit self-certification, oracle-status forgery) convert into
loud telemetry only when the channel is armed — yet there was NO
provisioning face: an operator had to hand-roll a key file with no
idempotence, no mode guarantee, and no honest status report. At the
same time the seal's largest producer, the step-credit host
(`rlvr.scalar.settle_round_credit`), still emitted its round-credit
ledger rows unsealed: producers had sealed at write since the seal
card, but the ledger rows the host emits through the rollout ledger
had no seal path at all.

## What Changes

- **`learning_seal.provision(keypath=None)`**: the keygen face
  (32 random bytes as hex text — the review-gate key-init shape) at
  `learning_seal.keyfile()` or a declared path, mode 0600, idempotent
  (an existing sufficient key is a no-op — never overwritten, since a
  re-provision would silently invalidate every seal minted under the
  old key), refusing a short/broken key file with the by-hand repair
  path. The returned status dict carries path + armed + a short
  sha256 id; the key material never reaches the status, logs, or
  stdout.
- **Step-credit host seals its rows**: the scalar module's THREE
  settlement writers — `settle_round_credit` (identity + amendment),
  `settle_workspace_scalars` (tier-scalar amendments), and
  `apply_trajectory_settlement` (trajectory/v3, the blind-settler
  score path) — pass the channel's signer into the rollout ledger's
  write faces (`rl.record` / `rl.settle`), so every emitted row is
  sealed BEFORE the ledger write. The ledger core never seals on its
  own: the signer is a producer-injected `sign` parameter (default
  None = byte-identical legacy writes for every other producer), and
  the signed row is re-validated after the callback (a schema-breaking
  signer is refused loudly).
- **The startup status face goes bidirectional**: armed, the first
  seal operation in a process emits
  `learning_seal: ARMED (<n> sealed rows)` as an INFO milestone (the
  count reads the workspace's sealed ledger rows; best-effort, honest
  zero) and clears the persisted once-marker so a LATER disarm is a
  new state transition that re-warns. Unarmed, the legacy UNSEALED
  warn is byte-unchanged. A posture memo re-opens both faces on any
  observed armed/unarmed flip mid-process.
- **Operator CLI**: `kunglao seal provision [--key-path P]` —
  provisions, prints the armed status, the key path, and a short key
  id; exits 0 armed / 1 unarmed. Never prints key material.
- **New kunglao_log faces**: a read-only `warn_workspace()` getter
  (one resolution shared by the count face) and
  `reset_once_state(op)` (the once-marker's re-arm face for a state
  transition).

## Capabilities

### New Capabilities
- `learning-seal-provision`: the provisioning face (idempotent keygen,
  declared-path honesty, short-key refusal), the step-credit host
  sealing its emitted rows through the producer-injected ledger
  signer, the bidirectional startup status face with
  disarm-re-open semantics, and the operator CLI.

### Modified Capabilities
- None (the seal's write/read contract — additive key, fail-closed
  learner filter, warn-and-ride unarmed posture — is unchanged; this
  change only adds the arming program around it).

## Impact

- `scripts/rlvr/learning_seal.py` — provision, sealed_row_count, the
  ARMED face, the posture memo; sign/verify untouched.
- `scripts/rlvr/ledger.py` — additive `sign=None` parameter on
  record/settle; every existing caller unchanged.
- `scripts/rlvr/scalar.py` — the host passes the channel signer at its
  two emission sites.
- `scripts/kunglao_log.py` — warn_workspace getter, reset_once_state.
- `scripts/kunglao.py` — the `seal provision` subcommand (no new file).
- Telemetry: one INFO row per process when armed (the #944 severity
  wrapper's registered `info` action word); the UNSEALED warn unchanged
  when unarmed.
- Tests: `tests/test_learning_seal_1005.py` (new; RED-first) plus the
  directly-affected seal/ledger/scalar suites.
