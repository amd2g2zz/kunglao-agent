# candidate-resolution-681 delta — issue-681-completion-judgment

## ADDED Requirements

### Requirement: The candidate path is declared or diagnosed, never silently .py-fallback

The candidate resolver SHALL prefer the unit's own
`checker.candidate` declaration (ws-relative) verbatim. Without a
declaration it SHALL fall back to `artifacts/derive_reimpl.py`, and
when that default's suffix mismatches the family's contract suffix
(`eval_contract.candidate_suffix` — the same face the checker grades
against) it SHALL emit exactly one typed `candidate-undeclared` event
(task_id, family, expected suffix, default rel) on the caller's event
sink plus one warn, while still returning the default path (fail-open:
no raise into the pipeline). For a .py-family unit the default matches
by construction and no event SHALL be emitted. An unregistered family
SHALL fail open without an event.

#### Scenario: a declared path wins over the default

- **WHEN** task.yaml declares `checker.candidate: client.js` for a
  js-sign unit
- **THEN** the resolver returns `<ws>/client.js` and no event is
  emitted

#### Scenario: an undeclared .js unit is diagnosed, not guessed

- **WHEN** a js-sign unit declares no `checker.candidate` and the
  workspace has no artifacts/derive_reimpl.py
- **THEN** the resolver returns the default path AND appends one
  `candidate-undeclared` event naming the expected `.js` suffix; the
  ORACLE evidence detail carries the event (the BLOCKED stop becomes
  diagnosable)

#### Scenario: a .py unit stays silent on the default

- **WHEN** a py-derive unit declares no `checker.candidate`
- **THEN** the resolver returns `<ws>/artifacts/derive_reimpl.py` and
  no event is emitted (the default matches the family contract)

#### Scenario: a non-string declaration is a validation error

- **WHEN** a unit's task.yaml declares `checker.candidate` with a
  non-string value (e.g. an integer)
- **THEN** task validation fails with a `checker.candidate` error —
  the declaration never silently falls through to the default path

### Requirement: Every non-.py unit declares its contract path

Every tracked eval unit whose family grades a non-.py candidate SHALL
declare `checker.candidate` in its task.yaml, and every declared path's
suffix SHALL equal the family's contract suffix. The declarations use
`client{suffix}` for re-implementation families, `verdict.json` for
misdirection verdict-document families, and `answer.txt` for toolflex
answer-document families; toolflex task.yamls SHALL remain
generator-owned (re-mint byte-identical).

#### Scenario: declarations obey the family contract

- **WHEN** the tracked task.yaml set is scanned
- **THEN** no declared `checker.candidate` path has a suffix other
  than its family's `eval_contract` suffix, and no non-.py family unit
  lacks a declaration

#### Scenario: toolflex re-mint stays byte-identical

- **WHEN** `eval_toolflex.build_unit` re-mints a toolflex unit
- **THEN** the rendered task.yaml is byte-identical to the tracked file
  (the `candidate: answer.txt` declaration rides the generator)
