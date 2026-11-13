## ADDED Requirements

### Requirement: Real Stop terminal settlement

The active production Stop hook SHALL settle a mission only after every applicable completion check succeeds and an independently verified terminal outcome is established.

#### Scenario: Successful terminal

- **WHEN** an active Stop passes the oracle, notes and summary checks and has a real independent checker record for the completed mission
- **THEN** its settlement and episode are persisted once and the episode's derived view is readable

#### Scenario: Release without eligibility

- **WHEN** Stop is absent, inactive, fail-open on oracle I/O, blocked, interrupted, or released by a sanction that does not establish all completion checks and an independently verified terminal outcome
- **THEN** no successful terminal settlement is fabricated

#### Scenario: Verified failure

- **WHEN** the mission has a real terminal failure with independent verification and attribution
- **THEN** it may settle as a failure without being recorded as success

#### Scenario: Retry and concurrency

- **WHEN** terminal settlement is retried, interrupted, or invoked concurrently
- **THEN** verified facts are preserved, duplicate accounting is prevented, and an actionable durable recovery record is consumed by a real recovery entry point

### Requirement: Independent observability

The system SHALL distinguish maker, checker, settlement and mission terminal spans from persisted settlement facts and SHALL avoid storing sensitive content.

#### Scenario: Independent failures

- **WHEN** either span persistence or ledger persistence fails independently
- **THEN** the other surface does not falsely certify it and an actual consumer can report the failure

### Requirement: Terminal certification postconditions

Terminal certification SHALL distinguish unknown obligations, invalid learning seals and missing committed-dispatch credit from successful completion, and SHALL persist a diagnostic retry state for recoverable postcondition failures.

#### Scenario: Obligations cannot be read

- **WHEN** the notes queue exists but cannot be read or parsed, including errors internally swallowed by the legacy notes consumer
- **THEN** production Stop SHALL block terminal certification, preserve a retry checkpoint naming the unreadable obligation surface, and create no episode or reward settlement

#### Scenario: Invalid persisted learning seal

- **WHEN** participating persisted round-credit or Q-cell credit facts carry an invalid seal, or an armed channel requires a seal that is absent
- **THEN** production Stop SHALL verify through the learning-seal owner, preserve the original facts and key unchanged, and retain a diagnostic retry state without certifying completion

#### Scenario: Missing dispatch credit cannot be repaired

- **WHEN** a committed dispatch has a settled round-credit fact but its Q-cell bank remains missing or unreadable after the existing recovery owner runs
- **THEN** production Stop SHALL block with a retry checkpoint even when the recovery owner swallowed its write failure, and a later successful retry SHALL recover without duplicate credit
