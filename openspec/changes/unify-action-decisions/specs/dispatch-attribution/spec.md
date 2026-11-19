## ADDED Requirements

### Requirement: Dispatch attribution is truthful

The dispatch record SHALL identify the actual method, sampled method, decision source, override rationale when available, and candidate provenance from the same decision. A sampler's conditional weights SHALL be distinct from the behavior probability of an external declaration. Independent credit SHALL join to the dispatch identity and replay without increasing credit twice.

#### Scenario: Adopted recommendation

- **GIVEN** a dispatch request omits the method and the sampler recommends an eligible method
- **WHEN** the gate adopts the recommendation and execution is approved
- **THEN** the worker receives the adopted method and the execution observation records that same method and its source. Later credit joins to its dispatch ID.

#### Scenario: Explicit declaration and override

- **GIVEN** a caller explicitly declares a currently authorized method
- **WHEN** the declaration matches or differs from the recommendation
- **THEN** the record retains both methods, records the declaration or override source, and leaves unknown behavior probability unknown. An absent override rationale or an absence of sampler support is recorded without rejecting the declaration on those grounds.

#### Scenario: Ineligible method

- **GIVEN** a method fails the current vocabulary, admission or authorization check
- **WHEN** the method is declared or adopted
- **THEN** the dispatch is rejected and creates no accepted-action observation.

#### Scenario: Interrupted trajectory

- **GIVEN** a verified observation from the first action, an unknown outcome for the second, and a third action that never started
- **WHEN** the trajectory stops
- **THEN** the confirmed result and observed costs remain available, the second outcome remains unknown, and the third action contributes no experience. Subsequent verification can settle against the original action identity.

#### Scenario: Host rejects or changes the accepted input

- **GIVEN** the hook has staged a method decision for one host tool call
- **WHEN** the host declines execution, or reports an input that differs from the accepted input
- **THEN** the staged decision contributes no Q-cell observation. A rejected journal entry cannot displace the producer of verified evidence.
