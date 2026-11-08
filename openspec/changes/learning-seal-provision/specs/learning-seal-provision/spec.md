# Spec Delta

## Purpose

Defines the learning channel's arming program: provisioning the HMAC
key (idempotent, never-destructive, key-silent), the step-credit host
sealing every emitted round-credit row before the ledger write, and
the startup status face that tells the operator the truth in both
postures — armed reports one INFO milestone with the sealed-row count
(replacing the UNSEALED warn), unarmed keeps the legacy warn, and a
disarm is a state transition that re-warns.

## ADDED Requirements

### Requirement: Provisioning is idempotent and never destructive

`learning_seal.provision(keypath=None)` MUST generate the key (32
random bytes as hex text) at the module's key path, or at a declared
path, with the mode applied AT CREATION (an `os.open` create-mode of
0600 — no crash window ever leaves a wider key file on disk) and
parent directories created; the returned status dict MUST carry
{path, created, armed, key_id, note} and MUST NOT carry key material
in any field. An existing sufficient key is a no-op: `created: false`,
bytes untouched, the note names the no-op, and its MODE is hardened to
0600 when a wider file is found. A hardening chmod that fails MUST
report `armed: false` with the loud note — the status never claims an
armed channel whose key mode could not be guaranteed. An existing key
below the byte minimum is refused with the by-hand removal path —
never auto-overwritten. The channel arms iff the module's own key path
resolves a sufficient key; a declared path that is not the module's
key path MUST report the live channel's (unarmed) posture honestly. A
declared path inside a git work tree MUST be called out in the note
(the fixed key path lives outside the repo; an in-repo key must never
enter history).

#### Scenario: Fresh host arms

- **WHEN** the module's key path has no key file
- **THEN** `provision()` creates it (00600 hex material, status
  `created: true, armed: true`) and `armed()` flips true

#### Scenario: Re-provision is a no-op

- **WHEN** a sufficient key already exists at the target path
- **THEN** the status reports `created: false` with the untouched
  bytes, the note names the no-op, and `armed()` stays true

#### Scenario: Short key refused

- **WHEN** the target path holds a key below the byte minimum
- **THEN** provisioning refuses: `created: false, armed: false`, the
  bytes stay untouched, and the note names the by-hand removal path
  (never an auto-overwrite — a silent key rotation would orphan every
  seal minted under the old key)

#### Scenario: A wide existing key is hardened

- **WHEN** the target path holds a sufficient key whose mode carries
  group or other bits
- **THEN** provisioning hardens the mode to 0600 (bytes untouched),
  the note names the hardening, and the channel stays armed

#### Scenario: A failed hardening never reports armed

- **WHEN** the hardening chmod fails
- **THEN** the status reports `armed: false` with the loud note naming
  the by-hand repair — the key bytes stay intact and the channel is
  never reported armed over a failed guard

#### Scenario: Declared path reports the live posture honestly

- **WHEN** provisioning writes a declared path that is not the
  module's key path
- **THEN** the file is created (0600) and the status reports the LIVE
  channel's unarmed posture — only a declared path that IS the
  module's key path arms the channel (a split resolution — signing
  under one key, checking under another — is the exact failure the
  fixed-path posture prevents)

#### Scenario: An in-repo declared path is called out

- **WHEN** a declared path sits inside a git work tree
- **THEN** the note names the risk (the key must never be committed;
  the fixed key path lives outside the repo)

### Requirement: The settlement writers seal their emitted rows

The scalar module's THREE settlement writers — `settle_round_credit`
(the identity row and the settlement amendment), and the amendment
writers `settle_workspace_scalars` (tier scalars) and
`apply_trajectory_settlement` (trajectory/v3, the blind-settler score
path) — MUST pass the channel's signer into the rollout ledger's write
faces, so every emitted row is sealed BEFORE the ledger write when the
channel is armed. The ledger core MUST NOT seal on its own: the signer
is a producer-injected `sign` parameter on `rl.record` / `rl.settle`
(default None = byte-identical legacy writes for every other producer),
and the signed row is RE-VALIDATED after the callback (a signer that
breaks the row schema gets one loud warn and a refused write). Unarmed,
the writers' rows ride unsealed with exactly ONE notice and settlement
MUST NOT be gated on arming.

#### Scenario: Armed host emits sealed rows

- **WHEN** the channel is armed and a scalar settlement writer settles
- **THEN** every emitted row carries the additive seal block,
  `verify_row` passes on each, and the learner filter reads the rows
  back with zero refusals

#### Scenario: Unarmed host rides legacy with one notice

- **WHEN** the channel is unarmed and the host settles a dispatch
- **THEN** every emitted row rides unsealed (byte-identical legacy
  shape), exactly one UNSEALED notice fires for the process, and the
  settlement still lands (never gated on arming)

#### Scenario: Sealed amendments dedupe like unsealed ones

- **WHEN** the host re-runs over an already-settled dispatch
- **THEN** the ledger dedupe compares the settlement block only, so
  the sealed amendment dedupes against its unsealed predecessor —
  no ledger churn across an arming boundary

### Requirement: The startup status face reports the truth in both postures

Armed, the first seal operation in a process MUST emit one INFO
milestone `learning_seal: ARMED (<n> sealed rows)` — the count reads
the workspace's seal-stamped rows across the learning ledger families
(best-effort: ANY family-read failure degrades the WHOLE count to the
honest zero, never a partial count) — and MUST clear the persisted
once-marker's entry for the seal op, so a LATER disarm is a new state
transition that re-warns. The marker reset MUST resolve its workspace
even in the UNPINNED production shape (explicit workspace, then the
pinned registration, then the same cwd walk-up the diagnostics ledger
face already trusts) — a previously-pinned warn's stale state key must
not survive an unpinned armed period. Unarmed, the legacy UNSEALED
warn MUST stay byte-unchanged. A posture memo MUST re-open both faces
on any observed armed/unarmed flip, so a mid-process key removal warns
again; the key material MUST NOT appear in any face or output.

#### Scenario: Armed replaces the warn

- **WHEN** the channel arms and the first seal operation runs
- **THEN** one INFO milestone with the sealed-row count appears, and
  the UNSEALED warn never re-fires while armed

#### Scenario: Disarm re-opens the warn

- **WHEN** the key file is removed after an armed period (mid-process
  or in a fresh process)
- **THEN** the rows ride unsealed again and the UNSEALED warn returns
  (the marker's stale silence is cleared by the armed face), never a
  crash

#### Scenario: Once per process

- **WHEN** armed signs repeat within one process
- **THEN** the ARMED face fires exactly once (the count may change,
  the face does not repeat)

#### Scenario: The count is best-effort

- **WHEN** no workspace is resolvable, or a family read fails
- **THEN** the count reads the honest zero and the face still fires

### Requirement: The operator CLI is key-silent and honest

`kunglao seal provision [--key-path P] [--workspace W]` MUST print the
armed status, the key path, and a short sha256 key id — never the key
material — and MUST exit 0 only when the live channel is armed (a
declared-path provisioning, a short-key refusal, or a failed mode
hardening exits 1 with the note naming the repair). The sealed-row
count line MUST name the workspace it counted (an explicit --workspace
first, else the resolvable one) so a wrong-tree count can never pose
as the live number.

#### Scenario: Provision arms and stays key-silent

- **WHEN** the operator provisions the fixed key path on a fresh host
- **THEN** the CLI prints the ARMED status, the path, and a short key
  id (no 64-hex material anywhere in the output), and exits 0

#### Scenario: Declared path exits honest

- **WHEN** the operator provisions a declared path that is not the
  fixed key path
- **THEN** the file is created (0600) and the CLI reports UNARMED with
  exit 1 (the live channel reads the fixed path; the note names the
  honest state)
