# arming-shape-733 delta — issue-733-arming-shape-law

## ADDED Requirements

### Requirement: ONE shape law governs oracle-case `expected`

The system SHALL define the `expected` shape law exactly once — in the
executor (`oracle_runner.expected_shape_error`): a non-empty list of
mappings, each carrying a non-empty string `field` and a `value`, where
every entry is either an explicit `pending-observation` or anchors its
expectation with at least one `evidence_refs` entry. Every other
consumer of case docs SHALL read that law rather than re-derive a rival
shape definition.

#### Scenario: the parse and the predicate agree

- **WHEN** any `expected` payload is probed (valid, empty, non-list,
  missing value, missing field, blank field, refs-less, pending)
- **THEN** the predicate flags exactly the payloads the parse refuses,
  with the same fault message

#### Scenario: the law is not copied

- **WHEN** a consumer needs the shape verdict
- **THEN** it calls the executor's predicate; no module re-derives the
  definition

### Requirement: Arming requires the canonical shape

The arming gate's `expected` requirement SHALL be the same predicate: a
doc whose `expected` is not the canonical entry list SHALL NOT be armed,
regardless of its other fields. A doc carrying the canonical shape with
all other arming fields SHALL be armed.

#### Scenario: the legacy mapping shape is not armed

- **WHEN** a case doc carries `expected` as a mapping (the shape the
  gate used to accept) with every other arming field present
- **THEN** the doc is not armed and the posterior legs observe nothing
  against it

#### Scenario: the canonical shape arms

- **WHEN** a case doc carries `expected` as the canonical entry list
  with every other arming field present
- **THEN** the doc is armed and the posterior legs observe it normally

### Requirement: The parse keeps its raise semantics

Delegating the shape half SHALL NOT change the parse's observable
refusals: the same payloads are refused, the first fault wins, and each
refusal keeps the `{case_path.name}: case {cid!r}` wrapping with the
same fault text. The #126 workspace-resolution half SHALL be unchanged.

#### Scenario: refusals are text-identical

- **WHEN** the parse runs over the shape probe matrix
- **THEN** every refused payload raises `OracleCaseError` whose message
  contains the predicate's fault text wrapped in the same prefix
