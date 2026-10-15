# reward-source-678 delta — issue-678-reward-source

## ADDED Requirements

### Requirement: The deliverable citation face SHALL have a producer

`rlvr.scalar.cited_ids_from_deliverables(ws)` SHALL return every
`F<NNN>` token named by a deliverable document under `notes/`,
`analyses/`, or `runs/deliverables/` (recursive, text/yaml suffixes,
tolerant reads that never raise). `rlvr.scalar.fact_artifacts` SHALL
invoke the producer when called with the default `cited_ids=None`; an
explicit set SHALL keep its exact membership meaning. A fact SHALL be
`cited_by_deliverable` when its id is a member of the cited set OR its
own `F<NNN>` token is a member.

#### Scenario: a deliverable naming a bare fact id marks the fact cited

- **WHEN** `notes/n-summary.md` names `F008` and `facts/F008.md`
  carries the slugged id `F008-decrypt-key`
- **THEN** `cited_ids_from_deliverables(ws) == {"F008"}` and the fact
  row's `cited_by_deliverable` is `True`

#### Scenario: an explicit cited_ids set bypasses the producer

- **WHEN** `fact_artifacts(ws, cited_ids=set())` is called in a
  workspace whose deliverables name fact ids
- **THEN** every row's `cited_by_deliverable` is `False`

### Requirement: The settlement path SHALL backfill creator-less facts or mark them non-creditable

`rlvr.scalar.backfill_artifact_creators(artifacts, dispatch_ids)` SHALL
attribute a creator-less artifact to its `claim_id` when that claim is
one of the settlement's dispatch ids, and SHALL mark every remaining
creator-less artifact `creditable: false`. Rows SHALL NOT be mutated in
place. The ws-level `rlvr.scalar.settle_round_credit` and the CLI
dry-run SHALL apply the backfill before grading.

#### Scenario: a creator-less fact on a settled claim settles credited

- **WHEN** a terminal claim C-001 has a creator-less PROVEN fact with
  `claim_id: C-001` and the settlement dispatches C-001
- **THEN** the backfilled artifact carries `creator: C-001`, the row
  reward is greater than zero, and `untraced` is empty

#### Scenario: a creator-less fact with no claim linkage stays untraced

- **WHEN** a PROVEN fact carries neither `creator` nor `claim_id`
- **THEN** it appears in `untraced` and the backfill marks it
  `creditable: false`

### Requirement: TRACE-band settlement credit SHALL not enter the Beta mass

`rlvr.q_cells.fold` SHALL add neither success nor failure mass for an
observation whose settled credit is in `(0, OBSERVATION_BAND_CEIL]`
(the TRACE observation band); the row SHALL remain in the observation
log and in the decay/schedule chain. A settled credit of exactly `0.0`
SHALL still add failure mass and a credit above the band SHALL fold as
before. The band decision SHALL key on the settled credit, never the
tiebroken one.

#### Scenario: a 0.01 credit banks no failure mass

- **WHEN** a settlement row carries credit 0.01 and folds with γ=1.0
- **THEN** its cell's success and failure masses are both 0.0

#### Scenario: a genuine zero still trains failure

- **WHEN** a settlement row carries credit 0.0
- **THEN** its cell gains 1.0 failure mass

### Requirement: Φ's fact dimension SHALL be graded and non-degenerate

`rlvr.state.fact_face` SHALL return a `weighted_fraction` beside the
byte-identical `count`/`verified` pair, grading grammar-clean facts
1.0 (certified terminal) / 0.5 (substantive non-terminal) / 0.25
(draft) and everything else 0.0 — the fact-certification farm wall
SHALL hold (junk and premature terminals lift Φ by zero).
`rlvr.incremental_reward.potential` SHALL read the graded fraction for
its facts term, and `append_transition` SHALL record an explicit
`phi_delta` column plus `claim_ref`/`action_key` from the launch stash.

#### Scenario: a non-terminal fact base yields an intermediate potential

- **WHEN** a workspace's facts are all grammar-clean INFERRED
- **THEN** `fact_face(ws)["weighted_fraction"] == 0.5` and
  `potential(ws)` is strictly between 0 and 1

#### Scenario: junk facts still lift nothing

- **WHEN** a workspace's facts are malformed junk files
- **THEN** `weighted_fraction` is 0.0

### Requirement: Armed oracle cases SHALL be visible to the settlement pass

`settle_round_credit.armed_case_ids(ws)` SHALL return the ids of
`oracle/cases/*.yaml` docs carrying every arming field
(`channel`, `hypothesis_ref`, `update_map`, `expected.evidence_refs`,
`mutations`) non-empty; every `run()` pass SHALL report `cases_armed`
and SHALL warn when the count is zero.

#### Scenario: an armed case drives the posterior ledger

- **WHEN** an armed case targets the `answers_question` of a banked
  PROVEN claim
- **THEN** `record_case_settlements` writes `runs/posteriors.yaml`
  with the case posterior updated

#### Scenario: a thin case doc is not armed

- **WHEN** a case doc carries only `id` and `target_pq`
- **THEN** `armed_case_ids(ws)` does not include it
