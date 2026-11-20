## ADDED Requirements

### Requirement: Attribute downstream use to the completed checker
When the learning seal is armed, the runtime SHALL credit downstream use only from sealed records bound to the current workspace and emitted from a completed, fresh checker dispatch initiated by the orchestrator. Existing checks on fact and deliverable content SHALL still apply.

#### Scenario: A distinct checker confirms use
- **WHEN** the host reports completion and the checker confirms use for the fact and deliverable in its assignment
- **THEN** the orchestrator hook records the host child identity and settlement can credit the fact producer once

#### Scenario: A record lacks author binding
- **WHEN** a workspace record has a self-reported checker identity without a valid seal and host binding
- **THEN** settlement treats its use as unknown when the learning seal is armed
