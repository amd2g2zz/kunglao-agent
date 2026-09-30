# feature-mining delta — issue-460-feature-mining (Part A)

## ADDED Requirements

### Requirement: Feature-table row extraction anchored on run-state

The miner SHALL mine each explicitly-named root's
`runs/e2e/<run_id>/` directories, treating a parseable
`run-state.json` as the run anchor, and SHALL emit exactly one
`feature-table/1` row per anchored run joining its recorded pointers:
the workspace (`ws`: task_spec difficulty block, promise prescan
states, claim register, evidence/{die,apkid,difficulty}.json, rollout
ledger, runs/logs/e2e-audit.jsonl) and the corpus task dir
(`task_dir`: task.yaml workspace_scaffold). Pointer paths SHALL
resolve verbatim when absolute (live shape) and against the mining
root when relative (fixture shape). Row identity SHALL come from
run-state fields: run_id from `run_id` (authority over the directory
name), family from `family`, task_id from `unit`. Inputs SHALL be
read-only: the miner mutates nothing under any input root.

#### Scenario: complete run mines a full row

- **WHEN** a run dir carries run-state.json, its ws carries task_spec
  + claim-register + audit stream, and task_dir carries task.yaml
- **THEN** one row is emitted with run_id/family/task_id from
  run-state, features from the joined sources, and one outcome entry
  per dispatch attempt

#### Scenario: relative pointers resolve against the mining root

- **WHEN** run-state.json records ws or task_dir as a relative path
- **THEN** the pointer resolves against the root argument, not CWD

#### Scenario: inputs are never written

- **WHEN** the miner runs over a root
- **THEN** no file under any input root is created or modified (only
  the --out path is written)

### Requirement: Instance signature hash over the features object

The row's `signature_hash` SHALL be the first 12 hex characters of
sha256 over the canonical JSON serialization (sort_keys=True,
separators=(",", ":"), ensure_ascii=False, UTF-8) of the features
object. The features object SHALL carry exactly the instance-level
keys — lane, project_type, target_kind, packer_flags,
difficulty_factors, probe_outputs — with no run-progress state, no
timestamps, and no free-text notes, so two runs of the same task with
the same evidence produce the same signature_hash while their
outcomes lists differ. This hash is the instance-signature namespace
and is documented as distinct from state_signature's pre-dispatch
progress-state hash. Within the features object:
`difficulty_factors` SHALL be the MOUNTED calibration block (task_spec
`difficulty:` block, fallback `evidence/difficulty.json`; both
absent → null) and SHALL NOT be recomputed from raw scanner evidence;
`target_kind.entry_suffix` SHALL be the lowercased entry path suffix
with its leading dot (".apk"); `packer_flags.detected_packers` SHALL
be the sorted unique union of die's `derived.detected_packer` and
apkid's `summary.packer`; `probe_outputs` SHALL carry always-present
die/apkid sub-objects whose inner fields (prescan_state, usable,
detected_packer, entropy_max / prescan_state, usable, packers,
obfuscators) degrade to nulls or empty lists when the source is
absent.

#### Scenario: same task, two runs, same signature

- **WHEN** two mined runs share family/task_id and identical joined
  features
- **THEN** their rows carry equal signature_hash and (generally)
  different outcomes lists

#### Scenario: changed features change the hash

- **WHEN** one run's evidence yields a die-detected packer and the
  other's does not
- **THEN** the two rows' signature_hash values differ

### Requirement: Per-act outcomes joined from the audit stream

Each row's `outcomes` SHALL contain one entry per dispatch attempt in
audit stream order, each carrying `claim` (join/trace key),
`method_family_or_claim_source`, `act_result`, `settled`, `credit`.
Pairing SHALL be FIFO per claim: each attempt pairs with the earliest
LATER dispatch_result row carrying the same claim; an attempt with no
later result row → act_result `unknown`. `act_result` SHALL come from
the closed vocabulary {landed, timeout, blocked, unknown}, computed
from the result row's detail payload (a JSON-encoded string): rc 0
and not timed_out → landed; timed_out or rc -1 → timeout; any other
non-zero rc → blocked; rc null in a present result row → unknown.
`method_family_or_claim_source` SHALL reuse the #432 dual-face
declaration contract (envelope `method_family` field first, v0
`method-family:` prose marker second, via method_families'
declared_value) read from `<run_dir>/dispatch-prompt-{claim}.md`,
else the claim register's `source` for that claim, else null —
attribution is never fabricated, and the per-claim prompt file being
last-write-wins across that claim's attempts is a disclosed
approximation. `settled`/`credit` SHALL come from the rollout ledger
fold of rollout_id `task/<claim>` (a settlement row → settled true
and credit = its reward; none → settled false, credit null). Runs
whose workspace predates the unified audit stream SHALL mine with an
empty outcomes list (their per-act data survives only in
checkpoint/report acts[]; a fallback for that face is a declared
follow-up, not this change).

#### Scenario: timeout dispatch

- **WHEN** a dispatch_result row carries rc -1 with timed_out true
- **THEN** that attempt's act_result is "timeout"

#### Scenario: rc-null result row is unknown, not blocked

- **WHEN** a dispatch_result row is present with rc null (the
  orchestrator/dry face)
- **THEN** that attempt's act_result is "unknown"

#### Scenario: envelope family wins over register source

- **WHEN** a dispatch prompt declares method_family
  "static-decompile" (a registered #432 token) while the claim
  register's source for that claim is "synthesis"
- **THEN** the outcome's method_family_or_claim_source is
  "static-decompile"

#### Scenario: ledger settlement feeds credit

- **WHEN** the workspace ledger folds a settlement of reward 0.0 for
  rollout_id task/C-005 and C-005 has dispatch attempts
- **THEN** every C-005 outcome entry carries settled true, credit 0.0

#### Scenario: unpaired attempt stays unknown

- **WHEN** an audit stream ends with a dispatch_attempt whose claim
  has no later dispatch_result row
- **THEN** that attempt's outcome entry carries act_result "unknown"

#### Scenario: no attribution material stays null

- **WHEN** a dispatch has no envelope method_family and its claim is
  absent from an unparseable register
- **THEN** method_family_or_claim_source is null, never guessed

### Requirement: Deterministic byte-identical emission

Mining the same input set SHALL emit byte-identical output: rows
sorted by (family, task_id, run_id, root) — the root term makes the
bytes independent of CLI argument order and disambiguates the same
run_id mined from two different roots (both rows ship) — each row
serialized as sorted-key UTF-8 JSON with a trailing newline, floats
passed through from their parsed values, and no wall-clock or
miner-run timestamps in any row. Duplicate roots SHALL be deduplicated
by resolved path before scanning. The default output path is
`runs/feature-table.jsonl` (overridable with --out); the miner prints
a one-line JSON summary {roots, runs, rows, skipped} to stdout.

#### Scenario: byte-identical remine

- **WHEN** the miner runs twice over the same fixture root
- **THEN** the two output files hash equal, and both equal the
  committed golden sha256

#### Scenario: root order does not change bytes

- **WHEN** the same two roots are passed in either order
- **THEN** the emitted bytes are identical

### Requirement: Malformed-source tolerance

A run whose run-state.json is missing, unparseable, or undecodable SHALL
be skipped with a stderr warn, not abort the table (invalid UTF-8
counts as undecodable — decode errors are data problems, the #438
lesson). Dangling or malformed joined sources (missing
workspace, unparseable or undecodable task_spec/claim-register,
absent evidence or ledger or audit stream) SHALL degrade the affected
feature or attribution fields to documented nulls/empties while the
row still ships — malformed FIELD VALUES (mixed-type probe lists,
non-numeric entropy, scalar family entries) degrade the field, never
abort the table — and a parseable run-state whose emitted row fails
the feature-table/1 shape (absent identity fields, non-string scalars)
SHALL be skipped the same way: the miner never ships a row its own
validator rejects. The exit code stays 0 with every skipped run
counted in the summary.

#### Scenario: corrupt run-state skips one run

- **WHEN** one run dir's run-state.json is corrupt JSON among healthy
  runs
- **THEN** the healthy runs' rows all emit, the corrupt run is
  counted in skipped, and the process exits 0

#### Scenario: missing workspace degrades features

- **WHEN** run-state's ws path does not exist
- **THEN** the row still emits with lane/project_type from
  run-state and null-valued difficulty/probe features and an empty
  outcomes list

### Requirement: Schema-validated rows

Every emitted row SHALL satisfy the feature-table/1 shape: schema
exactly "feature-table/1"; run_id/family/task_id strings;
signature_hash exactly 12 lowercase hex; features an object with the
six documented keys at their documented types (lane/project_type
string-or-null; target_kind {language, entry_suffix} string-or-null
each; packer_flags {packing, obfuscation, anti_analysis,
surface_reduction} booleans + detected_packers/detected_obfuscators
sorted string lists; difficulty_factors {tier, score,
dominant_factor, factors name→score, families name→bool, coverage
{die, apkid}} or null; probe_outputs {die, apkid} sub-objects with
their enumerated inner fields); outcomes a possibly-empty list of
entries with the four documented fields plus claim. The validator
SHALL be importable and SHALL be the same check the regression tests
apply.

#### Scenario: fixture rows validate

- **WHEN** the validator runs over every row mined from the pinned
  fixture root
- **THEN** all rows pass, including the degraded run's null-valued
  row

#### Scenario: junk row is rejected

- **WHEN** the validator sees a row with signature_hash "xyz" or
  act_result "exploded"
- **THEN** the row is rejected with a field-precise error
