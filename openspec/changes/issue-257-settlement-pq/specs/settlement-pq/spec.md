# Spec Delta — issue-257-settlement-pq

## ADDED Requirements

### Requirement: Settlement writes the situational PQ categorical

The system SHALL, at oracle case settlement (a case verdict of pass or
fail), apply the case's declared PQ events to the situational
PQCategorical identified by the case's `target_pq` string (the same
string claim `answers_question` keying uses), and persist the updated
categorical in `runs/posteriors.yaml`. Cases without `target_pq`, without
a `pq_update:` declaration, or with a pending verdict SHALL NOT touch the
pqs namespace.

#### Scenario: evidence event records nonzero signed ΔH

- WHEN a case with `target_pq: q_jni_registration` and `pq_update:
  green_up: {static_xref_dlsym: 2.5}` settles pass on a ledger whose
  `ledger.pqs` holds the EXP-3 priors
  {jni_register_natives: 0.5, static_xref_dlsym: 0.3, runtime_dlopen: 0.2}
- THEN the recorded event carries `delta_h_bits == 0.069654` (6dp),
  `h_before_bits == 1.485475`, `h_after_bits == 1.415821`
- AND `runs/posteriors.yaml` persists the updated categorical

#### Scenario: elimination event is the largest single ΔH

- WHEN the EXP-3 sequence continues with `eliminate_on_pass:
  [jni_register_natives]`
- THEN the recorded event carries `delta_h_bits == 0.673333` (6dp), the
  largest of the fixture sequence (9.7x the largest evidence event)
- AND the standing entropy after the full fixture sequence is
  `h_standing_bits == 0.337290`

#### Scenario: softening records a NEGATIVE ΔH

- WHEN an evidence event with strength < 1 lands on the current leader of
  a peaked categorical (EXP-3b control: {0.9375, 0.0625}, strength 0.5)
- THEN the recorded `delta_h_bits` is NEGATIVE (−0.185269, 6dp) — the
  signed-gain convention (delta_h_bits = h_before − h_after) is preserved
  without clamping
- AND `h_standing_bits` (0.522559) is recorded as a separate field from
  the per-event delta

### Requirement: pq_id equals the priority_ratio keying string

The categorical's pq_id SHALL be exactly the case `target_pq` /
claim `answers_question` string — no derived or alternate identifier — so
`priority_ratio`'s `ledger.pqs.get(answers_question)` consumption lights
up on the first settled categorical.

#### Scenario: ranker keying matches

- WHEN a case declares `target_pq: q1` and its settlement seeds or updates
  the categorical
- THEN `PosteriorLedger.load(ws).pqs["q1"]` resolves the same categorical
  the claim whose `answers_question == "q1"` prices at LAMBDA_DH

### Requirement: settlement-side seeding is idempotent and #250-tolerant

The system SHALL seed a settled question that has no categorical in
`ledger.pqs` uniform over the task_spec `primary_questions[]` entry
whose `id` equals the pq_id and whose `candidates` list is non-empty.
An existing categorical SHALL NEVER be reseeded (the #250 mint-time
writer in plan_epistemics may have landed it first).

#### Scenario: absent pq seeds uniform from task_spec candidates

- WHEN the ledger has no `q3` categorical and task_spec declares
  `primary_questions: [{id: q3, candidates: [a, b, c]}]`
- THEN the settlement seeds `PQCategorical("q3", {a: 1.0, b: 1.0, c: 1.0})`
  (normalized uniform)

#### Scenario: existing pq is never reseeded

- WHEN the ledger already holds a `q3` categorical with settled
  non-uniform mass
- THEN a settlement on `target_pq: q3` applies its events to the EXISTING
  distribution (idempotent seed; no reset to uniform)

### Requirement: unmatched candidate names fail open with an annotation

The system SHALL skip an update naming a candidate the categorical does
not carry (KeyError from `update_evidence`/`update_eliminate`) with a
recorded annotation (`status: "skipped"` + reason, and a
`pq_posterior_update` event with the same status) and SHALL NOT crash or
abort the settlement path; remaining declared events still apply.

#### Scenario: unknown candidate is annotated, run continues

- WHEN a case's `pq_update` names candidate `ghost_candidate` absent from
  the categorical alongside a valid event
- THEN the settlement records a skipped annotation for `ghost_candidate`
  with a reason, the valid event still applies with its measured ΔH,
  and the run exits normally

### Requirement: settled PQ guard on last-candidate elimination

The system SHALL treat an elimination event on a categorical with a
single surviving (nonzero-mass) candidate as an annotated no-op
(`status: "skipped"`, reason naming the settled state) — never the
library's ValueError surfaced into the settlement path.

#### Scenario: eliminating the last survivor is an annotated no-op

- WHEN a categorical has one nonzero-mass candidate left and a settlement
  declares its elimination
- THEN the event is skipped with the settled-state reason, the ValueError
  does not propagate, and the ledger still saves any other applied events

### Requirement: PQ settlement emits the controlled-vocabulary event

Each applied or skipped PQ settlement event SHALL emit one
`pq_posterior_update` event (registered in `event_taxonomy.EMIT_ACTIONS`)
carrying case_id, pq_id, channel (evidence|eliminate), candidate name,
strength, `h_before_bits`, `h_after_bits`, `delta_h_bits`,
`h_standing_bits` (6dp), status, and reason — guarded fail-open like the
file's other observability faces.

#### Scenario: applied events carry the signed delta in the event tail

- WHEN the EXP-3 fixture sequence settles
- THEN each event's `pq_posterior_update` row carries the same
  `delta_h_bits` the ledger records (6dp) with `status: "applied"`
