# issue-461-attribution-state — spec delta: attribution-state

## ADDED Requirements

### Requirement: Obstacle object schema obstacle/1

A failed act's attribution SHALL be a structured file
`runs/obstacles/OBS-<n>.json` of schema `obstacle/1` with fields
kind, cause, evidence_path, method_family, ts (plus id and schema
framing; claim / dispatch_id are optional join keys). The registry
lives under runs/ (beside the q-cell log, posterior store, and
situation stream — kernel telemetry, NOT under evidence/: the
evidence-index pipeline sweeps evidence/ as raw evidence and an
obstacle row is a derivation from its probe artifact, so an
evidence/ placement would invert the raw/derived hierarchy). kind
SHALL be one of the closed enum missing_env_entry / detection_trigger
/ encryption_layer / tool_limit / other. cause SHALL be a single
machine-checkable line: non-empty, no newlines, at most 200
characters. evidence_path SHALL be workspace-relative, SHALL NOT
traverse outside the workspace, SHALL cite an intervention experiment
artifact that EXISTS at record time, and the cited artifact SHALL
carry a probe-execution marker (a command / exit-code / observed-output
shape — the blocker-schema-v2 probe-marker discipline; the failing
command's own error text saved verbatim carries no such marker shape
when it records no command or exit code). ts SHALL be ISO-8601.
method_family SHALL record the failed act's declared family verbatim
(the registry gate stays the enforcement face for vocabulary — this
producer records, it never rejects on vocabulary). An obstacle row
SHALL carry no verdict semantics (no status field, no dead/terminal
conclusion) and is NOT an obstacle claim (origin failure-obstacle):
it SHALL NOT license any terminal or death declaration under the
three-state charter. The record face SHALL be loud-result fail-open
(invalid input produces a named reason and no file, never an
exception into the producer) and SHALL mint ids by exclusive create
(concurrent producers never overwrite). The read face SHALL
structurally validate rows (schema, kind, required fields) and skip
invalid ones without raising.

#### Scenario: minimal valid row mints

- **WHEN** record is called with kind detection_trigger, a one-line
  cause, an existing probe artifact path (the artifact containing a
  command/rc/output shape), method_family dynamic-trace
- **THEN** runs/obstacles/OBS-001.json exists with those fields,
  schema obstacle/1, an ISO-8601 ts, and the record result reports
  appended true

#### Scenario: unknown kind rejected

- **WHEN** kind is not in the enum
- **THEN** no file is written and the result carries a named reason

#### Scenario: missing evidence artifact rejected

- **WHEN** evidence_path cites a file that does not exist in the
  workspace
- **THEN** no file is written and the result carries a named reason —
  narration without an experiment artifact is not an obstacle

#### Scenario: artifact without probe shape rejected

- **WHEN** the cited artifact exists but contains no probe-execution
  marker (e.g. only quoted error prose)
- **THEN** no file is written and the result carries a named reason

#### Scenario: traversal and absolute paths rejected

- **WHEN** evidence_path is absolute or contains a parent segment
- **THEN** no file is written and the result carries a named reason

#### Scenario: empty, multiline, or over-long cause rejected

- **WHEN** cause is empty, contains a newline, or exceeds 200
  characters
- **THEN** no file is written and the result carries a named reason

#### Scenario: tolerant read never breaks

- **WHEN** the registry holds a corrupt JSON row or a row with an
  unknown schema
- **THEN** read returns the structurally valid rows, sorted by parsed
  id number, and skips the invalid one without raising

#### Scenario: concurrent mint never overwrites

- **WHEN** two record calls race for the same next id
- **THEN** exclusive-create minting gives each its own id and neither
  row is lost or overwritten

### Requirement: Obstacles enter the state signature

The state face SHALL read the obstacle registry tolerantly, expose a
digest {present, count, kinds} in the canonical snapshot document, and
carry an `ob=` segment in the canonical signature string: the
sorted `kind=count` pattern (claim-pattern idiom), `-` when the
workspace holds no structurally valid obstacle rows. The signature
schema tag SHALL advance to state-sig/2 for the eight-segment form
(the ob= segment inserts before the reserved sides tail, so sides
never re-keys; the historical seven-segment rows keep their own tag in
the append-only streams). Cause-bearing failure states SHALL therefore
be discriminable signature keys (different obstacle kinds produce
different signatures); the ob= pattern is cumulative by design (the
attributed-dead-end inventory grows), so consumers joining
dispatch-time signatures SHALL expect signature drift as attribution
accumulates — the q-cell fold joins under each row's recorded hash and
is unaffected, and compose-time cell counts on failure-rich sessions
reading zero is the disclosed Phase-2 feed material, not a defect. The
deterministic V(s) anchor SHALL remain unchanged — attribution is
evidence, not progress, and no obstacle term enters the weighted
mean. Phase 1 is recording-only: no dispatch, gate, or settlement face
SHALL import the obstacle module (the 396 freeze wall, extended with
full-module-string checks), and no face SHALL reject, block, or
re-rank anything on obstacle presence. [Phase-2 amendment, change
issue-461-option-death, 2026-09-30: the recording-only clause was the
Phase-1 boundary, not a permanent bar — Phase 2 adds exactly ONE
consumption face, the learned option-death termination posterior
(rlvr.termination), whose sole actuation is the DTS sampler floor
(dead options sampled at floor weight, never removed). Re-ranking via
that posterior is licensed; rejecting, blocking, gating, or any
verdict-face enforcement on obstacle presence stays barred forever,
and the dispatch/gate/settlement enforcement faces stay
obstacle-import-clean (the freeze wall as pinned).]

#### Scenario: obstacle-free signature re-pinned

- **WHEN** a bare workspace is snapshotted
- **THEN** the signature string is the state-sig/2 form ending
  `|ob=-|sd=-` and the snapshot obstacles digest is {present false,
  count 0, kinds ""}

#### Scenario: two obstacles produce the canonical pattern

- **WHEN** the registry holds one detection_trigger row and one
  missing_env_entry row
- **THEN** the signature carries `ob=detection_trigger=1|missing_env_entry=1`
  (sorted, kind-counted) and the digest count is 2

#### Scenario: different causes different signatures

- **WHEN** two workspaces differ only in obstacle kinds (one
  detection_trigger, one encryption_layer)
- **THEN** their signature strings differ in the ob segment and their
  signature hashes differ

#### Scenario: V anchor untouched

- **WHEN** obstacles are added to a workspace
- **THEN** v_anchor over the snapshot's other dims is unchanged by
  obstacle presence (no obstacle term, no weight)

### Requirement: Worker intervention protocol at act failure

The worker contract SHALL require intervention-based attribution when
an act fails: run an isolation probe that discriminates the suspected
cause, save the probe artifact (command, exit code, verbatim output)
under runs/probes/, record the obstacle row citing that artifact as
evidence_path via the helper CLI, and cite the OBS id in the `## failure`
block. The artifact SHALL be an experiment result, not prose; one
probe artifact MAY serve both an obstacle row's evidence_path and a
blocker's probe_evidence when the same experiment backs an ESCALATE.
The protocol SHALL NOT be enforced by any gate in Phase 1: a
cause-free failure remains legal output and is the learning system's
problem to outgrow (attribution dispatch), never a rejection reason;
write_guard does not adjudicate obstacle files (the helper is the
sanctioned producer, not the only possible writer).

#### Scenario: three canonical failure signatures

- **WHEN** a worker hits a missing env entry, an anti-analysis
  trigger, or an encrypted layer failure
- **THEN** each records an obstacle row of the matching kind
  (missing_env_entry / detection_trigger / encryption_layer) with a
  one-line cause, a probe artifact, and the failed act's method_family

#### Scenario: helper is the sanctioned producer

- **WHEN** the protocol's record step runs through the helper CLI
- **THEN** the row lands in runs/obstacles/ with the same validation
  as the library face (one validation path shared by CLI and library)

#### Scenario: worker contract pinned

- **WHEN** agents/kunglao-worker.md is read
- **THEN** the intervention protocol section names the obstacle kinds,
  the probe-artifact shape (command + exit code + verbatim output),
  the helper invocation, and the OBS citation rule for the failure
  block

### Requirement: Trap trajectory experiment data for Phase 2

The trap trajectory experiment SHALL be a declared-synthetic
five-step scenario replayed through the real record and state faces,
producing exactly one obstacle row per failing step (four rows) with
the expected (kind, method_family) sequence over REGISTERED family
tokens (the production Q-key vocabulary: dynamic-trace,
replay-harness-verification, static-decompile, obfuscation-peeling,
crypto-core-identification — frida-detected, unidbg-env-error,
static-tool-limit, encrypted-layer, breakthrough-at-decryptor), and no
obstacle row on the breakthrough step. The replay SHALL be
deterministic and its results (expected obstacle sequence plus the
per-step signature evolution) recorded as the Phase-2 termination
estimator's training shape.

#### Scenario: expected sequence produced

- **WHEN** the trap scenario replays on a fresh synthetic workspace
- **THEN** the obstacle sequence is detection_trigger/dynamic-trace,
  missing_env_entry/replay-harness-verification,
  tool_limit/static-decompile, encryption_layer/obfuscation-peeling,
  in order, and no fifth row (the crypto-core-identification
  breakthrough records none)

#### Scenario: signatures move at every failure

- **WHEN** the signature is taken after each step
- **THEN** every failing step changes the ob segment (the state the
  Phase-2 estimator conditions on), and the breakthrough step's
  signature equals the post-encrypted step's signature plus no new
  obstacle

#### Scenario: determinism pinned

- **WHEN** the replay runs twice
- **THEN** the result document is byte-identical (fixed ts values,
  sorted iteration)
