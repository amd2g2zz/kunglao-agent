## ADDED Requirements

### Requirement: Heartbeat tests use execution-time reference
The durable heartbeat tests SHALL construct their synthetic records from a single UTC timestamp captured when each test executes.

#### Scenario: Collection precedes execution by over one hour
- **GIVEN** collection occurred at least 61 minutes before execution
- **WHEN** recent and expired records are built using the execution-time reference
- **THEN** the real heartbeat evaluator reports recent records alive and expired records stale.
