# spec — init channel default (#727)

## Requirement: init never dead-ends on channel availability

Init SHALL resolve a channel decision (`vmr|ssh|docker|adb|local`) after the
toolchain preflight and before scaffold. When no remote channel is reachable
and no explicit `KUNGLAO_CHANNEL` is set, the resolved channel SHALL be
`local` with `defaulted_to_local=true` and a WARN event recorded. An explicit
`KUNGLAO_CHANNEL` SHALL never be auto-switched; unavailability SHALL produce
a guidance WARN while keeping the explicit value.

### Scenario: all remote channels unavailable

- WHEN all four remote probes report unavailable
- THEN the decision selects `local`, flags `defaulted_to_local`
- AND a `channel_default` WARN event lands in `runs/logs/kunglao-*.jsonl`

### Scenario: a remote channel is reachable

- WHEN the ssh probe succeeds (others unavailable)
- THEN the decision selects `ssh` with `defaulted_to_local=false`
- AND no degradation WARN is required

### Scenario: explicit channel unavailable

- WHEN `KUNGLAO_CHANNEL=ssh` is set and the ssh probe reports unavailable
- THEN the decision keeps `ssh`, sets `defaulted_to_local=false`
- AND the WARN detail carries fix guidance (environment or channel choice)

### Scenario: logging must never break init

- WHEN the kunglao_log emit raises for any reason
- THEN resolution still returns the decision (fail-open)

### Scenario: workspace record

- WHEN init writes `runs/.init-report.json`
- THEN the document carries a top-level `channel` block
  (`{selected, defaulted_to_local, probes}`) on success and error paths alike
- AND reports written without a decision omit the key (backward compatible)
