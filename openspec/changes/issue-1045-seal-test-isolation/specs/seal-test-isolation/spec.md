## ADDED Requirements

### Requirement: Independent warning workspace

The learning-seal key fixture SHALL isolate each test from previously pinned warning workspaces and restore the prior process state at teardown.

#### Scenario: Prior tool pins a warning workspace
- **WHEN** a tool test pins a workspace followed by two learning-seal warning tests
- **THEN** each seal test observes its own expected unarmed warning
- **AND** no marker from the previously pinned workspace suppresses it

#### Scenario: A seal test explicitly pins a workspace
- **WHEN** the test explicitly pins a workspace to exercise persisted once-marker behavior
- **THEN** real logging suppression and changed-state rearming remain observable
