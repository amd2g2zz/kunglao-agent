# non-silent-evidence delta — issue-472-audit-blockers

## ADDED Requirements

### Requirement: Dispatch wave act cage

The dispatch wave (`run_dispatch_parallel`) SHALL ensure every
dispatched act lands in structured evidence even when the act's
execution raises: a raising act SHALL be converted to a synthesized
`ActRecord` with outcome `ERROR` (the existing outcome vocabulary —
no new outcome words), its ATTEMPT/RESULT row pair SHALL be completed
with an explained rc-null reason, sibling acts' records SHALL be
unaffected, and the wave SHALL return normally so the tick's report is
written. The wave-of-one inline path SHALL carry the same cage.
`BaseException` classes that represent operator interrupts (e.g.
KeyboardInterrupt) SHALL still propagate.

#### Scenario: one act raises mid-wave

- **WHEN** a wave of >= 2 acts runs and one act's `run_dispatch`
  raises an Exception
- **THEN** the other acts' ActRecords land, the raising act yields an
  ERROR ActRecord preserving its claim and mode, a dispatch_result row
  is emitted whose exit-null is explained (not the orchestrator
  no-subprocess reason), and no exception escapes the wave.

#### Scenario: wave of one raises

- **WHEN** a single-act wave's `run_dispatch` raises
- **THEN** the act is caged identically and the exception does not
  propagate to the tick.

#### Scenario: unreadable prompt file on the auto face

- **WHEN** `AutoLlmFace.run_dispatch` runs with a missing or
  undecodable prompt file
- **THEN** the act returns an ERROR ActRecord and a result row whose
  null reason names the prompt-file failure — no exception escapes.

### Requirement: Claims-resolver distinguishes unreadable specs from absent anchors

`_resolve_claims` SHALL leave one rate-limited warn trace (via
`kunglao_log.warn`) whenever task_spec.yaml exists but is unreadable
or is not a mapping and the py-derive defaults are restored; a
readable mapping whose anchors are simply absent SHALL stay silent
(the documented fallback behavior), and an ABSENT spec file SHALL
likewise stay silent (no anchors to read — the same legitimate
fallback face, not corruption).

#### Scenario: corrupt spec warns

- **WHEN** task_spec.yaml exists and contains unparseable YAML or
  parses to a non-mapping
- **THEN** a warn naming the failure is emitted and the defaults are
  restored.

#### Scenario: anchors-absent stays silent

- **WHEN** the spec parses to a mapping with an empty goal anchor
- **THEN** the defaults are restored with no warn.

#### Scenario: absent spec file stays silent

- **WHEN** task_spec.yaml does not exist
- **THEN** the defaults are restored with no warn.

### Requirement: Retry-counter parse failure leaves a rate-limited trace

`read_retry_counter` SHALL warn (kunglao_log.warn, per-(op, reason)
dedupe) when the counter file exists but cannot be read or parsed,
while keeping the fail-open empty-dict return.

#### Scenario: corrupt counter file

- **WHEN** runs/.retry-counter.yaml contains unparseable content
- **THEN** the function returns {} and exactly one rate-limited warn is
  left for that reason (a repeat read with the same content does not
  warn again).

### Requirement: Emit never-raise is unconditional

`kunglao_log.emit` and `e2e.audit.emit` SHALL NOT raise on non-numeric
`duration_ms` / `exit` / `epoch` caller input — including non-finite
floats such as `inf` (an OverflowError at the coercion site) and
`nan`: such values SHALL coerce to null at the event-dict construction
site (after epoch-axis resolution, so a garbage explicit epoch is never
silently re-inherited) and the coerced null SHALL be documented in
null_reasons (`value_unparseable`); numeric values and numeric strings
SHALL coerce exactly as before.

#### Scenario: garbage numeric input

- **WHEN** emit is called with non-numeric duration_ms/exit/epoch
- **THEN** the row is written with those fields null, each carrying the
  value_unparseable reason, and emit returns without raising (both
  emit sites).

#### Scenario: non-finite floats

- **WHEN** emit is called with duration_ms=float('inf') or
  float('nan')
- **THEN** the field lands null with the value_unparseable reason and
  emit does not raise.

#### Scenario: garbage epoch is not re-inherited

- **WHEN** emit is called with a non-numeric epoch in a workspace whose
  tick ledger is readable
- **THEN** the row's epoch is null with the value_unparseable reason —
  NOT the workspace's current tick.

### Requirement: Hook exit-code registry completeness

`HOOK_EXIT_SEMANTICS` SHALL register the complete exit vocabulary of
every hook that blocks, including `completion_gate` (codes 0-7 with
their per-face meanings) and `workguard_gate`; the `ExitCode` enum
SHALL carry members for codes 4-7; the documented exit-1 block faces
SHALL be reconciled per the registry's own docstring (semantics are
per-hook and log-only) WITHOUT changing any emitted exit code; the
completion_gate shim's exit constants SHALL derive from the registry
with a fail-open literal fallback.

#### Scenario: completion_gate is registered

- **WHEN** the registry is inspected for "completion_gate"
- **THEN** codes 0/1/2/3/4/5/6/7 are each documented, exit 1 is
  documented as a deliberate fail-closed block (not a crash), and the
  members for 4-7 exist with the shim's pinned values.

#### Scenario: workguard block face is documented

- **WHEN** the registry is inspected for "workguard_gate"
- **THEN** its exit-1 block face is documented as the deliberate block
  the hook's own contract specifies.

#### Scenario: no emitted code changes

- **WHEN** the hooks run their block faces
- **THEN** the emitted exit codes are byte-identical to pre-change
  behavior.

#### Scenario: registry is the single source the shim derives from

- **WHEN** the shim's EXIT_NOTES_DUE / EXIT_NOTES_FAKE /
  EXIT_SUMMARY_FAKE constants are inspected
- **THEN** they equal the registry members' values (5/6/7), the
  fallback literals still carry the pinned substrings, and the
  pre-existing source-substring pin in test_notes_closure_762 stays
  green untouched.

### Requirement: Pipeline step cage

`run_pipeline`'s step loop SHALL convert a raising checkpoint step
into a FAIL `CheckpointResult` (via the canonical `_record` seam, with
the error and failed step in detail) such that the step's evidence
file and audit row land, the loop's FAIL handling applies, and
`finalize()` still writes the report. Operator interrupts SHALL still
propagate.

#### Scenario: checkpoint raises

- **WHEN** a checkpoint function raises an Exception mid-pipeline
- **THEN** a FAIL result is recorded for that step, the final report
  is written with EXIT_CHECKPOINT_FAIL, and no exception escapes
  run_pipeline.
