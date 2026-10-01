# intake-battery delta — issue-460-intake-battery

## ADDED Requirements

### Requirement: The intake probe battery runs the identification probes once at intake

The system SHALL run a probe battery — die-probe and apkid-prescan —
over the aligned `bins/` sample during intake, after the toolchain
gate and before the first claim dispatch (immediately before the
intake-promise block, so the promise's evidence-derived facts see the
fresh artifacts). The battery SHALL run unconditionally of
`KUNGLAO_PREDICT_BEFORE_TRY` (it is an instrument that produces
evidence; the flag gates selection, not evidence production). When no
aligned sample exists (non-malware lanes), the battery SHALL record
explicit absence rows and write no probe evidence.

#### Scenario: battery produces both evidence files and facts

- **WHEN** intake runs on a workspace with an aligned sample and both
  probe tools available
- **THEN** `evidence/die.json` and `evidence/apkid.json` are produced
  by the probes' own contracts and the battery ledger records one
  fact row per probe with outcome produced

#### Scenario: no sample is an explicit no-op

- **WHEN** the workspace declares a lane with no `bins/` sample
- **THEN** the battery records absent rows carrying the lane and
  writes no probe evidence, and intake proceeds

### Requirement: Probe failure records absence and never blocks intake

Every probe failure SHALL record an absence fact in the battery
ledger (with reason) and SHALL NOT change intake's exit code — tool
missing, invocation error, and negative finding all degrade the same
way. The battery entry point SHALL never raise into the init flow; an
unexpected battery defect SHALL be reported as a WARN-tier error with
an `env_incident` event, never as an init failure. `evidence/die.json`
SHALL be written only when the die probe produced a report; apkid's
fail-open unavailable/error statuses SHALL count as absent.

#### Scenario: probe CLI missing still succeeds intake

- **WHEN** neither probe tool is installed on the host
- **THEN** intake completes with its normal exit path, the battery
  ledger records both probes absent with reasons, and no usable probe
  evidence exists

#### Scenario: a negative finding is honest evidence

- **WHEN** a probe runs but produces no usable data (die exit 1,
  apkid non-APK error)
- **THEN** the ledger records the run and its negative outcome, and
  mining treats the artifact as unusable

### Requirement: Battery outputs land in the existing probe contracts and stay minable

Battery outputs SHALL land at `evidence/die.json` (die-probe CLI
`--out`) and `evidence/apkid.json` (`apkid_scanner.run`) exactly as
the existing probe contracts expect, plus the battery ledger
`evidence/intake-battery.json` (schema `intake-battery/1`) with one
fact row per probe. Battery-produced evidence SHALL be picked up by
the feature-table miner's `probe_outputs` extraction (die:
usable/detected_packer/entropy_max; apkid: usable/packers/
obfuscators) with no miner change.

#### Scenario: the mined table gains die/apkid values from run #1

- **WHEN** a workspace whose probe evidence was produced by the
  intake battery is mined into a feature table
- **THEN** its row carries the battery-fed die/apkid probe values
  (usable true, detected packers, entropy) instead of absence

### Requirement: Capability facts derived from probe evidence require usable evidence

The intake promise's probe-evidence fallback SHALL count a probe
artifact as a capability fact only when the artifact is USABLE — die:
at least one data block survived; apkid: status `ok` (the
difficulty-calibration usability rules). A fail-open or error-status
artifact SHALL leave the capability fact recorded as missing.

#### Scenario: unavailable evidence records a missing capability

- **WHEN** `evidence/apkid.json` exists with status `unavailable` and
  no toolchain item or host tool backs the tool
- **THEN** the promise's prescan capability fact for apkid is
  `missing`, not `available`
