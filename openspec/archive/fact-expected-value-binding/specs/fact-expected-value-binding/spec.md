## ADDED Requirements

### Requirement: Assignment-class expected MUST bind concrete value assertions

A fact whose `expected:` field contains assignment-class content (field names, `=` assignments, hex immediates, register references, or offset references) SHALL list concrete value assertions - each binding a field/variable to a specific value with its offset/register/immediate source - so that `kunglao_verify.py::l1_mechanical` has byte-exact targets to compare against. API-call sequences alone are insufficient when the subject of the fact includes assignments.

#### Scenario: NVENC initialization fact with assignments
- **WHEN** a fact documents encoder initialization with field assignments (e.g., NV_ENC_INITIALIZE_ENCODER: frameRateNum, frameRateDen, averageBitRate, maxBitRate, gopLength)
- **THEN** the `expected:` field MUST list each assignment with its concrete value and source (e.g., `frameRateNum=fps; frameRateDen=1; averageBitRate=bitrate; maxBitRate=bitrate; gopLength=0xFFFFFFFF`), not only the API call sequence

#### Scenario: pure API-sequence fact unaffected
- **WHEN** the `expected:` field contains only an API call sequence with no assignment indicators
- **THEN** the value-assertion requirement does NOT apply; the fact is not assignment-class and is verified by existing rules

### Requirement: Assignment-class expected without value assertions MUST be rejected

`kunglao_verify.py` SHALL refuse to promote (lint-reject) any assignment-class fact whose `expected:` lacks concrete value assertions. The rejection MUST identify that assignment-class tokens were detected and that no value assertions followed.

#### Scenario: F015-style expected with API sequence only
- **WHEN** the `expected:` field lists an API call sequence for a function that performs field assignments, but omits the field=value bindings
- **THEN** `kunglao_verify.py` rejects the fact (not promoted to PROVEN/VERIFIED), reporting that assignment-class content requires value assertions

#### Scenario: a2b5e25c regression
- **WHEN** F015 (nvenc_create_d3d11_encoder) is verified under the new rule with the original API-sequence-only `expected:`
- **THEN** F015 is rejected; after backfilling correct value assertions (frameRateNum=fps, frameRateDen=1, averageBitRate=bitrate, maxBitRate=bitrate, gopLength=0xFFFFFFFF), F015 passes byte-exact verification

### Requirement: byte-exact compare SHALL target value assertions individually

When the `expected:` field contains value assertions, `kunglao_verify.py::l1_mechanical` SHALL compare each value assertion against the reproduce output / fixture at the field level, NOT reduce the entire `expected:` blob to a single sha256 of semantic text. A fact passes only when every value assertion matches.

#### Scenario: one wrong assignment among several
- **WHEN** the `expected:` field lists five field assignments and the reproduce output matches four but differs on one (e.g., gopLength=0xFFFFFFFF expected, 0 observed)
- **THEN** verification FAILS, reporting the mismatched field, rather than passing because the API sequence matched
