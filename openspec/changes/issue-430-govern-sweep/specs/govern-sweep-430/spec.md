# govern-sweep-430 delta — issue-430-govern-sweep

## ADDED Requirements

### Requirement: A coercing read leaves one governed trace

Every state-handling site that coerces corrupt/unreadable input to a
default SHALL emit ONE rate-limited `kunglao_log.warn` on the coercing
branch, keeping the return value unchanged. A MISSING file that is the
routine case SHALL stay silent (the cold-start split).

#### Scenario: a corrupt input warns and returns the same default

- **WHEN** any governed site reads corrupt or unreadable input
- **THEN** the default is returned exactly as before and one
  `warn(op, reason)` lands

#### Scenario: the cold start stays quiet

- **WHEN** a workspace whose optional state file simply does not exist
  yet is read
- **THEN** no warn fires

### Requirement: The sweep adds no behavior change

The sweep SHALL add warn calls only — no return-value, control-flow,
or schema changes anywhere.

#### Scenario: posture unchanged

- **WHEN** the governed sites are exercised with the same inputs as
  before the sweep
- **THEN** every return value matches its pre-sweep value
