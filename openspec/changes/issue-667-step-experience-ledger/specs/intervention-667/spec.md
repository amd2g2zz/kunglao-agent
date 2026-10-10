# intervention-667 delta — issue-667-step-experience-ledger

## ADDED Requirements

### Requirement: Interventions log shadow-only with hashed subjects

`record_intervention` SHALL append one `intervention/1` row (schema, ts,
trigger, actor, subject_sha, note_sha) — subject and note ride only as
sha256. Fail-open: an unwritable workspace yields no row and never a
raise.

#### Scenario: an intervention lands a hashed row

- **WHEN** an operator intervention is recorded with a subject path and
  a note
- **THEN** the row carries the trigger, actor, and the two shas — and
  neither the subject text nor the note text appears in the file
