## ADDED Requirements

### Requirement: Measured seal fixture state isolation

The measured seal fixtures SHALL isolate the process warning workspace and restore its prior value after each test.

#### Scenario: A preceding test pins a warning workspace
- **WHEN** a previous test pins a workspace and writes an unarmed warning marker
- **THEN** the measured unarmed test emits exactly one process warning independently of that workspace
- **AND** fixture teardown restores the previous warning workspace object

### Requirement: Independent warning workspace

The learning-seal key fixture SHALL isolate each test from previously pinned warning workspaces and restore the prior process state at teardown.

#### Scenario: Prior tool pins a warning workspace
- **WHEN** a tool test pins a workspace followed by two learning-seal warning tests
- **THEN** each seal test observes its own expected unarmed warning
- **AND** no marker from the previously pinned workspace suppresses it

#### Scenario: A seal test explicitly pins a workspace
- **WHEN** the test explicitly pins a workspace to exercise persisted once-marker behavior
- **THEN** real logging suppression and changed-state rearming remain observable
