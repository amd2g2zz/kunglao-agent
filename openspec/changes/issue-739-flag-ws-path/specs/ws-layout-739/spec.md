# ws-layout-739 delta — issue-739-flag-ws-path

## ADDED Requirements

### Requirement: A dash-leading workspace arg is refused

The workspace resolver SHALL NOT resolve a dash-leading arg as a
workspace path. The strict family SHALL refuse it loudly (stderr
guidance naming the flag, exit 2); the quiet family SHALL treat it as
absent and probe. Explicit real path args SHALL continue to win.

#### Scenario: the RC1 repro writes nothing

- **WHEN** `heartbeat_touch --help` runs in a bare directory
- **THEN** it exits 2 with flag guidance and creates no directory

#### Scenario: arg-wins is untouched

- **WHEN** a marked workspace path is passed explicitly to the strict
  resolver
- **THEN** it resolves to that path exactly as before
