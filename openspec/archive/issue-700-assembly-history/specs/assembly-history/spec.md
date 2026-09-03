# Spec — assembly history (#700)

## Requirement: init-report archive rotation

The init report writer SHALL archive any existing report to
`runs/.init-report.{n}.json` before writing a fresh
`runs/.init-report.json`, where n is one greater than the highest
existing archive number (starting at 1).

### Scenario: second init preserves first report

- **WHEN** `runs/.init-report.json` exists with content A
- **AND** `write_init_report` writes content B
- **THEN** `runs/.init-report.json` contains B
- **AND** `runs/.init-report.1.json` contains A
- **AND** exactly one stderr line announces the archive

### Scenario: rotation bounded to KEEP archives

- **WHEN** the number of archives would exceed `KUNGLAO_INIT_REPORT_KEEP`
  (default 5)
- **THEN** the oldest archives are deleted so at most KEEP remain

### Scenario: rotation never breaks init

- **WHEN** archiving fails (I/O error, pathological sibling)
- **THEN** the fresh report is still written and `write_init_report`
  returns the target path

## Requirement: per-item install events

`ask_then_install` SHALL emit, per HARD-FAIL item with an install plan,
events to the kunglao_log channel with `actor="toolchain_install"`:

- `install_attempt` with `tool=<item>` and `detail="via <plan.kind>"`
  after consent, before the plan runs
- `install_failed` with `tool=<item>` and `detail=<head of error>` when
  a consented install returns non-zero
- `install_declined` with `tool=<item>` and a reason on the no-consent
  headless degrade and the IDA mcp_url non-auto-installable degrade

### Scenario: timeline answers "which tool was attempted when"

- **GIVEN** a report where `die` is HARD-FAIL and consent is granted
- **WHEN** the install command fails with a multi-line error
- **THEN** the day's `runs/logs/kunglao-<date>.jsonl` contains an
  `install_attempt` line then an `install_failed` line for tool `die`,
  the failed detail carrying the first error line

### Scenario: observability is fail-open

- **WHEN** the emit machinery raises
- **THEN** the install loop completes unaffected

## Constraint

All three action words are registered in
`event_taxonomy.EMIT_ACTIONS` (sorted, unique) before any call site
ships; no new event schema fields beyond existing kwarg reuse.
