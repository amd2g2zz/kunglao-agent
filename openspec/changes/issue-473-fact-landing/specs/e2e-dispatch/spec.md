# e2e-dispatch

## ADDED Requirements

### Requirement: REQ-ENVELOPE-FACT-LANDING
The dispatch envelope SHALL instruct the worker that intermediate findings (mapped structure, pinned constants with partial verification, decoded case semantics) are written as facts with boundary_type positive_observation immediately upon establishment, and that final numeric claims upgrade later facts rather than waiting for full verification.

#### Scenario: skeleton decoded mid-act
- **WHEN** a worker establishes the control-flow case semantics during an act
- **THEN** the envelope it received contains that incremental-facts instruction
- **AND** the instruction names positive_observation as the boundary type

### Requirement: REQ-ENVELOPE-STATUS-PROTOCOL
The dispatch envelope SHALL require the worker to end its final message with a line `STATUS: DONE` or `STATUS: BLOCKED` so the outcome parser can classify precisely (prose fallback stays).

#### Scenario: envelope carries protocol
- **WHEN** a dispatch prompt is minted
- **THEN** it contains the STATUS line requirement

### Requirement: REQ-ACT-TIMEOUT-ENV
The act timeout SHALL be read from the KUNGLAO_E2E_ACT_TIMEOUT_S environment variable when set and parseable as a positive int, defaulting to 1800 otherwise (garbage → default).

#### Scenario: env override
- **WHEN** KUNGLAO_E2E_ACT_TIMEOUT_S=3600
- **THEN** dispatch acts use a 3600s timeout
- **WHEN** the variable holds garbage
- **THEN** the timeout falls back to 1800
