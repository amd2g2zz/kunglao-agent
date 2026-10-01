# workspace-state

## ADDED Requirements

### Requirement: crashed-decision-loud-stop
When the convergence decision is CRASHED on N consecutive ticks (default 3), the loop SHALL stop with a recorded BLOCKED result whose detail surfaces the decision and the failing stderr tail — passive spinning is a contract violation.

#### Scenario: three crashed ticks in a row
- **WHEN** the decision is CRASHED on three consecutive loop ticks
- **THEN** the loop stops with stop_class "convergence-crashed" and the detail carries the stderr tail
- **AND** fewer than three consecutive CRASHED ticks do not stop the loop

### Requirement: resume-resets-noop-breaker
The resume path SHALL reset the workspace noop-breaker counter to zero before the first tick.

#### Scenario: resume after breaker trip
- **WHEN** a run resumes a workspace whose .heartbeat-noop.json count is at/above the threshold
- **THEN** the first tick runs (count reset to 0), not an instant idle-circuit-breaker BLOCKED

### Requirement: yaml-safe-state-writer
scripts/ws_yaml.py SHALL provide get/set/del on YAML workspace state files via safe_load + safe_dump, refusing anything that would produce invalid YAML (round-trip validation), exit 0 on success / 2 on usage / 3 on unreadable target.

#### Scenario: set a prose value containing a colon
- **WHEN** ws_yaml.py set claim-register.yaml claims.3.evidence "mapped (facts/F007: 0x19d68)"
- **THEN** the file re-reads as valid YAML with the exact value round-tripped
