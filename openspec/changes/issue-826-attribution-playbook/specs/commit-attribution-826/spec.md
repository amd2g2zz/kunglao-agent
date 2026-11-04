# issue-826-attribution-playbook — delta spec (the P3 senior-expert faces)

P3 of the #806 axis: the attribution model (learned, deterministic
statistics over the pool), the tune/switch commit semantics with the
required attribution reference and the dead-path gate, the playbook
compression under the distillation quality axioms, the surprise ->
re-examination loop, and the four-knob component ablation.

## ADDED Requirements

### Requirement: Attribution reports feature-level causes, not a binary flag

`attribution.feature_importance(ws)` SHALL rank context features by
their failure contrast computed from the P1 pool's episode outcomes
(deterministic counting statistics; presence lift against the pool's
base failure rate). `attribution.method_attribution(ws, doc)` SHALL
return a method verdict over the vocabulary hypothesis_wrong /
tool_mismatch / depth_insufficient, with the per-signal evidence and
the learned features named — never a bare accident/failure boolean.
Features with no outcome contrast SHALL be reported as exogenous noise
(prior input, not causes — the #421 demotion).

#### Scenario: two synthetic failures attribute differently

- **WHEN** the pool holds verified successes under feature set S, a
  failure carrying a capability-failure feature never seen in a
  success (tool-missing fixture), and a failure whose features exactly
  match S (hypothesis-wrong fixture)
- **THEN** the tool-missing fixture attributes tool_mismatch, the
  hypothesis-wrong fixture attributes hypothesis_wrong, and both
  reports carry feature evidence (distinct methods, no binary flag)

#### Scenario: exogenous features are demoted to noise

- **WHEN** a feature appears at the same rate in failures and
  successes (no contrast)
- **THEN** the report lists it under `exogenous` and it never ranks as
  a failure cause

### Requirement: Switch carries an attribution reference; tune carries a delta

A `switch` commit entry SHALL be refused (`CommitError`) without a
non-empty `attribution_ref` and `to_class` — a blind lane change is
RED. A `tune` commit entry SHALL be refused without a parameter/tool
delta (`param_changes` or `tool_changes`) on the SAME class.

#### Scenario: no-attribution switch is red

- **WHEN** a switch commit entry lacks `attribution_ref`
- **THEN** `validate_switch_commit` raises CommitError naming the
  missing field

#### Scenario: delta-less tune is red

- **WHEN** a tune commit entry carries no `param_changes` and no
  `tool_changes`
- **THEN** `validate_tune_commit` raises CommitError

### Requirement: The 9x dead-path re-probe shape is red

`commit_semantics.validate_commit_history(doc)` SHALL refuse an
episode whose consecutive same-class commit attempts reach
DEAD_PATH_CAP (9) without an intervening tune/switch, and surface the
reading additively in the envelope block.

#### Scenario: nine same-class re-probes refused

- **WHEN** an episode holds 9 consecutive same-class attempts
- **THEN** `validate_commit_history` raises CommitError; 8 attempts
  followed by a tune passes

### Requirement: Playbook compression applies the quality axioms

`playbook.compressed_view(ws)` SHALL derive from the P1 playbook view
(called, not modified) and REFUSE case-specific fragments (claim ids,
fact ids, long hex digests, artifact paths); keep self-starting
verb-bearing fragments; rank by cross-episode support. The view SHALL
own no storage and be reached through the P2 retrieval face.

#### Scenario: case-specific compression is refused

- **WHEN** a verified completion's fragment carries a claim id / hex
  digest / artifact path
- **THEN** the compressed view excludes it; a method-shaped fragment
  from the same episode rides

### Requirement: Surprise triggers a re-examination commit

`commit_semantics.surprise_check` SHALL flag a verified outcome that
contradicts the value table's expectation for its committed class, and
`reexamination_block` SHALL produce the forced re-examination commit
payload for it.

#### Scenario: contradiction fixture generates the re-exam commit

- **WHEN** a verified-completed episode's class cell expects a
  negative mean reward (or a verified failure's expects positive)
- **THEN** surprise_check flags it and reexamination_block yields a
  commit payload with action `verify` and the contradiction evidence

### Requirement: Component ablation covers four knobs, each priced

With `KUNGLAO_META_PLAYBOOK=0` no playbook group rides the envelope
context; with `KUNGLAO_META_ATTRIBUTION=0` no attribution evidence
rides tune/switch commits. `price_ablations` SHALL report, in output
terms, what each of the four switches (retrieval, value_table,
attribution, playbook) removes.

#### Scenario: playbook ablated removes the ride-along

- **WHEN** KUNGLAO_META_PLAYBOOK=0
- **THEN** `meta_retrieval.assemble` returns no playbook groups and the
  pool's retrieval counters are the only other change

#### Scenario: the ablation price is reported

- **WHEN** `price_ablations` runs on a seeded pool
- **THEN** each of the four knobs carries an output-terms price row
