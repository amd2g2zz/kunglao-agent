# Spec Delta — issue-255-event-schema

## ADDED Requirements

### Requirement: Every event carries the single tick axis

The unified event log SHALL stamp every emitted event with the workspace's
current tick: the convergence ledger's RAW snapshot-row count (round :=
tick alias). The tick accessor SHALL count rows whose parsed value is a
mapping with no "type" key that carries "open_count", SHALL skip
unparseable lines, SHALL return 0 for an absent ledger (a real cold-start
tick), and SHALL return None only when the ledger cannot be read. The
accessor's ledger name SHALL equal the writer's constant. When an event's
epoch kwarg is omitted, emit SHALL inherit the current tick; an explicit
kwarg SHALL win. Only an unreadable ledger SHALL leave the field null,
documented as `tick_ledger_unreadable`. No module other than the schema
face and the ledger-snapshot passthrough MAY name an epoch producer — a
second counter is forbidden; derived views only.

#### Scenario: events carry the tick by construction

- **WHEN** a workspace's convergence ledger holds 2 snapshot rows and an
  event emits without an epoch kwarg
- **THEN** the row's `epoch` is 2 and its `null_reasons` carries no epoch
  key

#### Scenario: explicit epoch wins

- **WHEN** an event emits with `epoch=7` while the ledger holds 2 snapshot
  rows
- **THEN** the row's `epoch` is 7

#### Scenario: cold start is a real tick, not a fabricated value

- **WHEN** no convergence ledger exists and an event emits
- **THEN** the row's `epoch` is 0 with no epoch reason

#### Scenario: unreadable ledger is honest, never faked

- **WHEN** the ledger path cannot be read (e.g. a directory at the path)
  and an event emits
- **THEN** the row's `epoch` is null and `null_reasons["epoch"]` is
  `tick_ledger_unreadable`

#### Scenario: no second counter

- **WHEN** the producer audit scans emit-producing modules for an `epoch=`
  kwarg producer
- **THEN** only the schema face and the ledger-snapshot passthrough match

### Requirement: The epoch column carries only the tick axis

The event log's epoch column SHALL carry the tick (or the documented
unreadable-ledger null) and nothing else. The audit exemption list SHALL
be pinned by contract, not by absence of callers: the schema face
(kunglao_log) MUST define the tick accessor, and the ledger-snapshot
passthrough (mission_ledger) MUST forward epoch as the literal
passthrough shape only — any computed assignment in an exempted module
SHALL fail the audit. A future module naming an epoch producer SHALL fail
the audit until it is registered with its justification.

#### Scenario: a new producer file appears unregistered

- **WHEN** a module under scripts/ or hooks/ (at any depth) names an
  `epoch=` kwarg without being in the exemption list
- **THEN** the single-axis audit test fails naming the file

#### Scenario: the passthrough exemption cannot silently become a counter

- **WHEN** the exempted passthrough module assigns epoch anything other
  than the literal passthrough of its own parameter
- **THEN** the exemption-shape pin fails

### Requirement: Mandatory fields populate from execution structure

The event schema's rot fields SHALL be populated mechanically from
execution structure at the sites that structurally know them: the five
fields are duration_ms, arm, epoch, hypothesis_ref and matched_rule.
`rank_feeds` SHALL carry the selected arm (the rank-#1 claim id; empty
ranking = honest null), `verify` SHALL carry a measured duration_ms
(monotonic clock pair around the bounded verification work), and
`claim_settled` SHALL carry the claim's latest hypothesis id from the
hypothesis store (missing store = honest null). Population SHALL never be
fabricated: a site that cannot know a field keeps the documented null.

#### Scenario: rank_feeds carries its arm

- **WHEN** the ranker emits a rank_feeds event for a non-empty ranked
  action list
- **THEN** the row's `arm` equals the rank-#1 claim id

#### Scenario: verify carries a measured duration

- **WHEN** the verification face emits its verify event
- **THEN** `duration_ms` is a non-null integer measured around the work

#### Scenario: settlement carries its hypothesis

- **WHEN** a claim settles while the claim's hypothesis store holds its
  hypotheses
- **THEN** the claim_settled row's `hypothesis_ref` is the latest
  hypothesis id for that claim

#### Scenario: unknowable stays honest

- **WHEN** an emit site structurally cannot know a mandatory field (no
  actor/action arm context, no timing wrap, no settlement store)
- **THEN** the field lands null with its documented reason and no value is
  fabricated

### Requirement: The auto-documented null set shrinks only by earned shrinkage

A field SHALL leave AUTO_NULL_FIELDS only when it is populated-by-
construction at every site that emits it. epoch SHALL leave the set via
the tick axis; duration_ms, arm, hypothesis_ref and matched_rule SHALL
stay (caller-side execution structure is their only source). The
null_reasons sidecar SHALL remain for genuinely-unknowable cases.

#### Scenario: epoch leaves the starved set

- **WHEN** an event emits without arm / duration_ms / hypothesis_ref /
  matched_rule on a cold-start workspace
- **THEN** `AUTO_NULL_FIELDS` equals (duration_ms, arm, hypothesis_ref,
  matched_rule), the row's epoch is the real tick 0, and the four
  unknowable fields keep their documented `omitted` reasons
