# constraint-witness delta — issue-692-constraint-witness

## ADDED Requirements

### Requirement: Every not_done row binds a mechanical witness at intake

The goal-operationalization document SHALL carry a `constraint_witness`
block with `schema: constraint-witness/1` whenever its `not_done` list is
non-empty. The block's `witnesses` mapping SHALL bind each declared
`not_done` row verbatim (1:1) to a witness spec that carries exactly one
of `check:` (a non-empty shell command; exit 0 means the constraint holds
at the delivered workspace) or `none:` (a non-empty reason declaring the
row mechanically unwitnessable). The validator SHALL refuse a document
where any row lacks a witness, where a witness key does not correspond to
a declared row, where a spec carries both or neither form, or where the
block carries a foreign schema — exiting non-zero instead of reporting a
clean lint.

#### Scenario: a not_done row with no witness block is refused

- **WHEN** `goal_operationalization.py` validates a document with a
  non-empty `not_done` and no `constraint_witness` block
- **THEN** the process exits non-zero and the report names the missing
  witness requirement

#### Scenario: partial coverage is refused

- **WHEN** the witness mapping covers only one of two declared rows
- **THEN** the process exits non-zero naming the uncovered row

#### Scenario: full check/none coverage lints clean

- **WHEN** every row binds exactly one valid `check:` or `none:` spec
  under `schema: constraint-witness/1`
- **THEN** the validator reports no errors and exits zero

#### Scenario: orphan and malformed witnesses are refused

- **WHEN** a witness key is not a declared `not_done` row, or a spec maps
  to both `check:` and `none:` (or neither, or a non-mapping)
- **THEN** the validator reports an error and exits non-zero

### Requirement: Dispatch refuses to stamp an unwitnessed constitution

`--stamp-dispatch` SHALL refuse to freeze a document whose validation
report carries errors, including witness errors — the constitution it
writes SHALL include a deep copy of the witness mapping under
`constitution.constraint_witness`, and post-dispatch validation SHALL
refuse withdrawal of the whole witness block or any change (removal or
re-spec, notably `check:` degrading to `none:`) of a frozen row's witness.
Appends of new witnessed rows remain legal post-dispatch.

#### Scenario: stamping the bare document raises

- **WHEN** `stamp_dispatch` is called on a document whose `not_done` rows
  have no witnesses
- **THEN** it raises the validator's loud-rejection error and writes no
  stamp

#### Scenario: post-dispatch witness weakening is refused

- **WHEN** a stamped document's frozen witness spec changes (or its block
  disappears) and the document is re-validated
- **THEN** the report carries a witness withdrawal/weakening refusal

### Requirement: The oracle verdict is witness AND outcome

The e2e ORACLE checkpoint SHALL evaluate the workspace's declared
constraint-witness block against the delivered workspace and SHALL
compose the checkpoint status as `verdict = witness AND outcome`: any
witness check that ran and exited non-zero makes the checkpoint FAIL even
when the outcome checker is green (VERDICT PASS, ratio met, uncontaminated),
and a green witness leg never rescues a failed outcome. The evaluated
envelope SHALL be recorded in the checkpoint detail under
`constraint_witness`.

#### Scenario: degraded solution with a green outcome turns RED

- **WHEN** the outcome leg passes but a declared `check:` witness exits
  non-zero in the delivered workspace
- **THEN** the ORACLE checkpoint status is FAIL and the detail names the
  violated constraint row

#### Scenario: clean witness plus green outcome stays PASS

- **WHEN** every check exits zero (and `none:` rows are declared) and the
  outcome leg passes
- **THEN** the ORACLE checkpoint status is PASS

#### Scenario: a failed outcome is never rescued by a clean witness

- **WHEN** the outcome leg fails and the witness leg evaluates PASS
- **THEN** the ORACLE checkpoint status remains FAIL

### Requirement: Settlement-time evaluation fails open with warnings

The witness evaluation face SHALL fail open (never block) with a recorded
warning for postures that are not evidence of a violation: the workspace
carries no goal-operationalization file, the document is unreadable, no
`constraint_witness` block is declared, `not_done` is empty, a row's spec
is unusable, or a check could not be executed (spawn error, timeout, rc
-1). Such rows SHALL be recorded as `error` (or the whole envelope as
`UNDECLARED`) in the detail — never as a silent pass and never as a red.
The hard refusal belongs to the intake lint and the dispatch gate, which
re-validate the document fail-closed.

#### Scenario: pre-contract workspace warns and keeps the outcome verdict

- **WHEN** the workspace has no goal-operationalization file (or no
  witness block)
- **THEN** the evaluation returns `UNDECLARED` with warnings and the
  composed verdict equals the outcome verdict

#### Scenario: an unrunnable check is an error entry, not a red

- **WHEN** a declared `check:` times out or fails to spawn
- **THEN** the row is recorded as `error` with a warning and the witness
  status does not become FAIL on that basis

### Requirement: Witness checks execute in the workspace with both roots

Each `check:` SHALL execute as `sh -c` with the workspace as the working
directory and `KUNGLAO_WS` / `KUNGLAO_REPO` exported, bounded by a hard
timeout (60 s default) and routed through the caller's command seam when
one is supplied. Exit 0 SHALL record the row as `holds`; any other exit
code SHALL record `violation`; `none:` rows SHALL record
`declared-none` with their reason.

#### Scenario: a check runs against the delivered workspace

- **WHEN** a row binds `check: test ! -e browser.dep` and the delivered
  workspace contains `browser.dep`
- **THEN** the row records `violation` with rc 1 and the witness status
  is FAIL

#### Scenario: environment roots are visible to the probe

- **WHEN** a check command references `$KUNGLAO_WS` or `$KUNGLAO_REPO`
- **THEN** the command executes with both variables exported to the
  workspace and repository paths
