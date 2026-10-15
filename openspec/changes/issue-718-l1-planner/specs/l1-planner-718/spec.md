# l1-planner-718 delta — issue-718-l1-planner

## ADDED Requirements

### Requirement: The rollout return is computed and stored at claim terminal

`rlvr.l1_value.compute_rollout_return` SHALL define the return as the
discounted SUM `R(τ) = Σ γ^t·r_t` over the claim's transition rewards in
append order plus the terminal ladder credit at the last step's weight
(the shipped γ = 1.0 calibration face: the exact sum, never the mean —
no mean-based learning target exists on this surface), and
`rlvr.scalar.settle_round_credit` SHALL, on the FIRST successful
settlement of a dispatch (`banked`), store ONE observation row in
`runs/l1-value-log.jsonl` (schema `l1-value-obs/1`) carrying the return,
the transition count, the undiscounted chain sum, the terminal credit
and the DISPATCH-time state signature (the matched dispatch row's
recorded signature). A replay or late-cite amendment SHALL add no
second row, a settle without a dispatch-time signature SHALL store no
row (ONE warn — the honest gap), and every L1 failure SHALL be
fail-open (the settlement result is unchanged).

#### Scenario: the return lands at the first settlement

- **WHEN** a claim with two closed transitions (r_incr +0.4 and −0.1)
  settles with the full ladder credit 1.0 and a pending dispatch row
  exists
- **THEN** runs/l1-value-log.jsonl gains exactly one row whose return is
  1.3, whose components name transitions_sum 0.3 and terminal 1.0, and
  whose state_signature equals the dispatch row's recorded signature

#### Scenario: replay adds nothing

- **WHEN** the settlement runs a second time for the same claim
- **THEN** the value log still holds exactly one row for that claim

### Requirement: The L1 value function learns from rollout returns

`rlvr.l1_value` SHALL keep (state_signature, action_kind) Beta cells
folded from the stored returns — a POSITIVE return banks success mass,
a NEGATIVE return banks failure mass, 0.0 banks no mass but counts as
an observation — under the imported DTS discount schedule (the SHIPPED
default; an explicit constant γ selects the exact-count calibration
face), and `cell_posterior` SHALL return the wide Beta(1,1) for a
nowhere-observed cell. `sample_value` SHALL draw θ ~ Beta(cell
posterior) and `seed_state` SHALL return the f(store, round) digest seed
(the sample moves when evidence moves or the round advances; no wall
clock). Failure patterns SHALL enter only through the canonical state
signature's features — no failure-count trigger exists.

#### Scenario: terminal returns move the cells

- **WHEN** a claim's terminal return is 1.25 at signature s
- **THEN** the folded cell (s, "dispatch") holds success mass 1.25, and
  a store of 20 negative dispatch returns with 20 positive split
  returns draws θ near 0 for dispatch and near 1 for split

### Requirement: The planner chooses by value/cost over DTS draws

`rlvr.l1_planner.plan` SHALL sample one DTS draw per candidate from its
(s, action_kind) cell and choose the argmax of value / cost, where a
candidate's value is the draw times VALUE_SCALE — except a candidate
carrying a `value_hint` (a KNOWN value, e.g. the knowledge strength),
whose value SHALL be the hint itself (the cell's draw is still reported
in the receipt for audit, but its value is never sampled: you do not
pretend uncertainty about a fact). The action vocabulary SHALL be
exactly dispatch / park / split / verify / reuse, a non-park candidate
with cost ≤ 0 SHALL be refused at the candidate boundary, park SHALL be
the do-nothing baseline (cost 0, value 0, ratio 0.0), and a candidate
set without any positive ratio SHALL select park (else the first
candidate) — cheapness alone never wins.

#### Scenario: learned value moves the choice

- **WHEN** the (s, dispatch) cell carries 20 negative returns and the
  (s, split) cell 20 positive ones, both at cost 1.0
- **THEN** the chosen action is split and its receipt value/ratio exceed
  dispatch's

#### Scenario: the cost model overrules a high value

- **WHEN** dispatch draws the lower value at cost 0.2 and split the
  higher value at cost 100.0
- **THEN** dispatch is chosen — the criterion is value per unit cost

### Requirement: Solved claims are reused unless a re-attempt's ratio beats the replay's

`rlvr.l1_planner.knowledge_query` SHALL grade the knowledge substrate
(claim register; facts index — verified answers; cross-task posterior
store rows carrying the claim id with credit > 0) into a strength, each
face fail-open with ONE warn, and SHALL report `answer_strength` over
the ANSWER faces only (facts index / cross-task — the register reports
lifecycle). `plan_for_claim` SHALL offer the `reuse` action (cost
REUSE_COST ≈ 0.1) with the knowledge strength as its value whenever the
claim is solved, so reuse wins by default on value/cost — and a
re-attempt whose value/cost EXCEEDS the replay's SHALL be chosen: no
rule forbids re-dispatching a solved claim.

#### Scenario: certified knowledge wins

- **WHEN** the facts index records a PROVEN fact naming the claim and
  the re-dispatch costs the tier cost
- **THEN** the chosen action is reuse with ratio above the dispatch's

#### Scenario: a superior re-attempt flips the comparison

- **WHEN** the recorded answer is weak (strength 0.3 at cost 0.1) and a
  re-attempt candidate carries value 2.0 at cost 0.5
- **THEN** the re-attempt is chosen — the comparison decided, not a rule

### Requirement: Step credit flows to L2 only

The rollout return SHALL read only the transition chain
(`rlvr.incremental_reward` rows) plus the terminal ladder credit; the
step-credit stream (`credit_kind: step` rows in the q-cell log) SHALL
NOT enter the L1 store, and the L1 bank SHALL NOT write the q-cell
store (the #712 terminal residual calibration remains the L2 face's own
row). A workspace carrying only an L2 step credit SHALL fold no L1
cells.

#### Scenario: two stores, two signals

- **WHEN** a claim banks one step credit (1.0), closes one transition
  (r_incr 0.2) and settles with ladder 1.0
- **THEN** the L1 row's return is 1.2, carries no step-credit column,
  and the q-cell log's settlement kinds are exactly the L2 kinds
  (step, step_calibration)

### Requirement: The rank face consumes the planner additively and is dormant while unlearned

`rlvr.l1_planner.advisory_factors` SHALL return {} while the value store
holds no observations, and scripts/priority_ratio.priority_ratio SHALL
then produce its pre-#718 ranking and payload byte-identically (no
planner feed, no planner payload key, no score change). Once learned,
it SHALL return the planner's dispatch share per claim (∈ (0, 1]) for
claims with an answer on record, `priority_ratio` SHALL multiply those
claims' scores by the factor and carry a per-claim `planner` feed plus
an additive `planner` payload block (outside `input_fingerprint`), and
claims at exactly 1.0 SHALL keep their score and feeds untouched.

#### Scenario: dormant while empty

- **WHEN** the value store is empty (or the value log is absent)
- **THEN** advisory_factors is {} and the rank output carries no planner
  signal at all

#### Scenario: the drag wakes up with learning

- **WHEN** the value store holds one observation and one candidate claim
  has a verified fact on record
- **THEN** that claim's factor is strictly below 1.0, the other claims'
  factors are exactly 1.0, and the ranked score of the answer-bearing
  claim is strictly lower than in the unlearned run
