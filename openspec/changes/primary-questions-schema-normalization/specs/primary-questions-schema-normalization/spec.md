## ADDED Requirements

### Requirement: primary_questions SHALL be parsed by one canonical loader

`scripts/convergence_check.py::_parse_primary_questions(task_spec) -> (list[(qid, need)], error)` SHALL be the single canonical parse of `task_spec.yaml#primary_questions`, returning a list of `(qid, need)` tuples (`need` is `None` when unspecified) and an `error` string that is `None` on success. The parse SHALL accept exactly these forms, deterministically:

- key absent, `[]`, or `{}` → feature unused: `([], None)`;
- plain string item (`- q1`) → `("q1", None)`;
- canonical dict item with a non-empty string `id` key (`- id: q1` plus optional `need`/`q`/`candidates`) → `("q1", need)`;
- legacy one-key mapping item without `id` and with exactly one string key (`- q1: sample family`) → `("q1", None)` (the value is a description, not a `need` enum; `None` value is also accepted);
- top-level non-empty mapping (`primary_questions: {q1: family}`) → one `(qid, None)` per string key.

Every other non-empty shape SHALL be a parse error with a reason naming the offending index/field: a dict item without `id` and with zero or multiple keys, a dict item whose `id` value is not a non-empty string, a legacy mapping whose value is neither a string nor `None`, a non-str/non-dict item (int, bool, list, null), a top-level `primary_questions` that is neither a list nor a mapping, a non-string top-level mapping key, and duplicate question ids. On error the function SHALL return `([], error)`.

#### Scenario: canonical dict form parses
- **WHEN** task_spec contains `primary_questions: [{id: q1, need: yes_no_with_evidence}]`
- **THEN** `_parse_primary_questions` returns `([("q1", "yes_no_with_evidence")], None)`

#### Scenario: plain string form parses
- **WHEN** task_spec contains `primary_questions: [q1]`
- **THEN** `_parse_primary_questions` returns `([("q1", None)], None)`

#### Scenario: legacy one-key mapping parses
- **WHEN** task_spec contains `primary_questions: [{q1: sample family}]`
- **THEN** `_parse_primary_questions` returns `([("q1", None)], None)` — the mapping value is a description, not a `need`

#### Scenario: explicit empty list means feature unused
- **WHEN** task_spec contains `primary_questions: []` (or the key is absent, or `{}`)
- **THEN** `_parse_primary_questions` returns `([], None)` and the orphan check stays skipped

#### Scenario: two-key mapping without id is malformed
- **WHEN** task_spec contains `primary_questions: [{q1: family, q2: c2}]`
- **THEN** `_parse_primary_questions` returns `([], error)` with a reason naming item 0

#### Scenario: non-string id is malformed
- **WHEN** task_spec contains `primary_questions: [{id: 123}]`
- **THEN** `_parse_primary_questions` returns `([], error)` naming the `id` field

#### Scenario: non-str/non-dict item is malformed
- **WHEN** task_spec contains `primary_questions: [q1, 42]`
- **THEN** `_parse_primary_questions` returns `([], error)` naming item 1

#### Scenario: duplicate question ids are malformed
- **WHEN** task_spec contains `primary_questions: [q1, {id: q1}]`
- **THEN** `_parse_primary_questions` returns `([], error)` naming the duplicate `q1`

#### Scenario: top-level non-empty mapping parses as question ids
- **WHEN** task_spec contains `primary_questions: {q1: family}`
- **THEN** `_parse_primary_questions` returns `([("q1", None)], None)` — behavior preserved from the pre-regression string-key iteration

### Requirement: every completeness gate SHALL consume the same parsed question set

`decide()` SHALL call `_parse_primary_questions` exactly once per invocation and derive `pq_ids`, the orphan check (`_orphan_terminal_claims`), the unanswered-question check (`_unverified_primary_questions`), and the note-layer check (`_note_layer_gaps`) from that single parsed representation. `_pq_ids()` SHALL remain a thin wrapper over the canonical parse (returning the id set, or `set()` on error) so existing callers and tests keep working. A question set parsed from a legacy one-key mapping MUST NOT be empty.

#### Scenario: legacy mapping feeds the orphan gate
- **WHEN** task_spec uses `[{q1: sample family}]` and a terminal claim has no `answers_question`
- **THEN** the orphan check sees `q1` and the claim is reported as an orphan

#### Scenario: legacy mapping feeds the unanswered-question gate
- **WHEN** task_spec uses `[{q1: sample family}]` and the only answering claim is `STAMP`
- **THEN** `_unverified_primary_questions` reports `q1` as unverified

#### Scenario: legacy mapping feeds the note-layer gate
- **WHEN** task_spec uses `[{q1: sample family}]` and a `verify_status=passes` note links a claim answering `q1`
- **THEN** `_note_layer_gaps` does not list `q1`

### Requirement: non-empty malformed primary_questions SHALL yield INVALID, never CONVERGED

When `_parse_primary_questions` returns an error, `decide()` SHALL return decision `INVALID` with exit code `EXIT_BLOCKED` (4), an `action` message containing the parsing reason, and a new `pq_parse_error` diagnostic field carrying the reason. The `INVALID` branch SHALL be evaluated before the rest of the decision matrix — an invalid task spec blocks dispatch decisions too, because the run's convergence target is undefined. A non-empty malformed, mixed-with-malformed, or unrecognized `primary_questions` SHALL NEVER yield `CONVERGED` or exit code 0.

#### Scenario: malformed mapping cannot converge
- **WHEN** task_spec contains a two-key mapping without `id` and all claims are terminal
- **THEN** `decide()` returns decision `INVALID`, exit code 4, and `action` contains the parsing reason

#### Scenario: mixed list with a malformed item cannot converge
- **WHEN** task_spec contains `[q1, 42]` and all claims are terminal
- **THEN** `decide()` returns decision `INVALID` and exit code 4 — the set is NOT silently reduced to `{q1}`

#### Scenario: invalid spec blocks dispatch too
- **WHEN** task_spec is malformed AND open claims exist with free slots
- **THEN** `decide()` still returns `INVALID` (exit 4), not `DISPATCH`

#### Scenario: explicit empty list still converges
- **WHEN** task_spec contains `primary_questions: []` and all claims are terminal with no partial facts
- **THEN** `decide()` returns `CONVERGED` / exit 0 (feature unused — backward compatible)

### Requirement: the happy path with every question PROVEN SHALL keep converging

A valid canonical spec in which every mandatory primary question has an answering claim in an appropriate terminal status (`PROVEN` for non-yes-no needs; `PROVEN`/`VERIFIED`/`NEGATIVE`/`REFUTED` for `yes_no_with_evidence`) and zero orphan terminal claims exist SHALL keep returning `CONVERGED` / exit 0 when the note-layer gate is satisfied (or notes/ is absent). No existing test in `tests/test_convergence_completeness.py` SHALL regress.

#### Scenario: all canonical questions PROVEN converges
- **WHEN** task_spec uses canonical `[{id: q1, need: yes_no_with_evidence}, {id: q2}]`, both questions have `PROVEN` answering claims, and no orphans exist
- **THEN** `decide()` returns `CONVERGED` with exit code 0

#### Scenario: legacy one-key mapping happy path converges
- **WHEN** task_spec uses `[{q1: family}, {q2: c2 config}]`, both questions have `PROVEN` answering claims, and no orphans exist
- **THEN** `decide()` returns `CONVERGED` with exit code 0
