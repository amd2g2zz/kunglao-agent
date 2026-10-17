# recipe-arms-695 delta — issue-695-recipe-arms

## ADDED Requirements

### Requirement: Every approved dispatch records the recipe triple

Every dispatch that passes the approval tail SHALL record the
tool-chain recipe view on its q-cell observation row
(`runs/q-cell-log.jsonl`, source=dispatch): three keys — `recipe_id`
(the arm the dispatch carried), `recipe_propensity` (the sampler's
draw probability of that arm, rounded to 6dp, 0.0 outside the arm
support, null when no sampler view exists) and `recipe_source` (closed
vocabulary: `sampled` | `declared` | `none`). The view is recomputed
at dispatch time from the arm fold (anti-spoof — nothing the envelope
says can move the sampler). The keys are emitted together and only
when the view names a recipe; the none-gap row stays byte-identical to
pre-#695. Fail-open: a sampler failure degrades to the none gap with
one rate-limited warn and never blocks the observation.

#### Scenario: an on-policy dispatch

- **WHEN** the envelope declares exactly the arm the gate's sampler
  draws for the family (or declares no recipe and the sampler supplies
  one)
- **THEN** the dispatch row carries that `recipe_id`,
  `recipe_source: sampled` and the draw's propensity in (0, 1]

#### Scenario: an off-policy declaration

- **WHEN** the envelope declares a registered arm that differs from
  the gate's own draw
- **THEN** the dispatch row carries the declared `recipe_id`,
  `recipe_source: declared` and its sub-1.0 propensity under the
  sampler — the off-policy decision is visible, not silent

### Requirement: Settlement banks credit against the dispatch-recorded recipe without worker narratives

`observe_settlement` (the #678 match-and-bank face) SHALL carry the
matched dispatch row's recipe triple onto the settlement row and its
result — credit banks against the DISPATCH-RECORDED `recipe_id`
(intention-to-treat), and the recipe fold SHALL read only these
mechanically recorded rows. No worker narrative (worker-status
`steps:` lines, verify notes, facts prose — the #881 tool_value
source) is ever read by the recipe face.

#### Scenario: a lying narrative cannot move the bank

- **WHEN** a dispatch recorded recipe A settles credit 0.8 and a
  worker-status narrative claims recipe B was used
- **THEN** the settlement row carries `recipe_id` A with credit 0.8,
  the fold credits A's posterior and B gains nothing from the prose

#### Scenario: verification credit never moves the arm posterior

- **WHEN** a settlement row carries `credit_kind: verification`
  (#705's decomposition)
- **THEN** the row is recorded but the recipe fold excludes it — only
  solve credit updates the arm posterior

### Requirement: Every registered family carries at least three arms and a floor weight that is never deleted

The registry SHALL hold ≥ 3 recipe arms per registered method family,
each arm with a strictly positive cold-start `prior` (static gravity,
overturnable — never the policy). The sampling weight
`prior · max(θ, THETA_FLOOR)` SHALL be strictly positive for every arm
at all times: an arm with arbitrarily bad settled history keeps the
THETA_FLOOR weight (0.1 · prior), remains in the sampling support, and
revives on new success. Arms SHALL NEVER be removed or zeroed.

#### Scenario: a beaten arm stays samplable

- **WHEN** one arm of a family accumulates 30 settled zero-credit
  rounds against it
- **THEN** all its family's arms remain present with strictly positive
  weights, the beaten arm sits at exactly `prior · THETA_FLOOR`, and
  repeated draws still select it

### Requirement: A deviation from the sampler is a recorded decision, never a reject

A declared recipe SHALL be recorded and SHALL never reject: a
deviation from the gate's arm draw — registered or NOT — is a recorded
decision — exactly one
`recipe_deviation` event (a registered `EMIT_ACTIONS` word) lands in
the unified log carrying declared, sampled, propensity, the
`registered` flag and the prompt's `agent-reasoning:` reason when
present, and `pre_check` still returns 0. The recipe face adds no
REJECT surface and no prefix bypass; no battery gate's return contract
changes.

#### Scenario: a declared deviation passes and is recorded

- **WHEN** the envelope declares a registered arm other than the draw
- **THEN** `pre_check` returns 0 and one `recipe_deviation` event
  carries the pair and the logged propensity

#### Scenario: an unregistered recipe passes and is recorded

- **WHEN** the envelope declares a `recipe_id` outside the registry
- **THEN** `pre_check` returns 0, the dispatch row records the id with
  propensity 0.0 and `recipe_source: declared`, and the deviation
  event carries `registered: false`

### Requirement: The S2 replay reports arm-level separation before any online switch

`rlvr.recipe_arms.replay_report(ws)` SHALL be a pure offline read over
recorded history: per family it reports the current argmax arm, the
per-arm weights and the mean settled credit (arm-level separation),
plus the disagreement rate (recorded recipe ≠ current argmax over
recipe-carrying dispatch rows). It SHALL NOT move any dispatch
decision — the online switch stays outside this card.

#### Scenario: history with opposed arm outcomes

- **WHEN** one arm's dispatches settled at credit 1.0 and another's at
  0.0 across equal counts
- **THEN** the report names the credited arm as the family's argmax,
  carries both mean credits verbatim, and the disagreement rate equals
  the share of rows on the losing arm
