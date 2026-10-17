# intelligent-scheduling delta — issue-685-intelligent-scheduling

## ADDED Requirements

### Requirement: The scheduling vocabulary lives in the action registry

The wake-decision vocabulary SHALL be exactly the scheduling-flagged
registry entries at the orchestration level (`scripts/action_space.py`):
`sleep` / `wake_on` / `probe` / `close_loop` / `none`. The decision
recorder's constant SHALL be derived from the flagged subset in registry
order (no hand-kept parallel list). `none` SHALL be a first-class entry
with cost 0 and value 0 — the null action; every other scheduling action
SHALL carry a strictly positive cost and the standard metadata
(precondition / proof power / consumer / estimator signature stub). A
declared or injected action name outside the vocabulary — or an injected
weight that is not a finite number — SHALL be refused loudly before any
decision is recorded.

#### Scenario: registry change is the only source of vocabulary change

- **WHEN** the scheduling five are queried from the registry and from the
  decision recorder
- **THEN** both return the same five names in registry order, and
  `orchestration.none` reports cost 0.0

#### Scenario: an unknown declared action is refused

- **WHEN** a decision is requested with a declared action that is not
  registered
- **THEN** it raises before any record or signal row is written

### Requirement: Every wake decision is logged with propensity and source

Each decision SHALL record one row on the signal stream (`kind=scheduling`)
carrying `{action, propensity, source, k, selected, null_propensity,
budgets, entropy_bits, free_slots}` and persist the full record to
`runs/.scheduling-decision.json`. `source` SHALL follow the dispatch-action
trichotomy: `sampled` (the sampler chose it), `declared` (deterministic —
the behavior policy itself, propensity 1.0), `none` (the intervention IS
inaction). A sampled decision's propensity SHALL be its true sampling
probability under the candidate logits, strictly inside (0, 1].

#### Scenario: a declared sleep is deterministic

- **WHEN** `sleep` is declared at a decision point
- **THEN** the logged row carries `source=declared` and `propensity=1.0`

#### Scenario: a sampled timer action carries its sampler probability

- **WHEN** a decision is sampled under logged candidate logits
- **THEN** the row's `propensity` equals the action's sampling probability
  under those logits (0 < p <= 1), and the same action under flatter logits
  carries a smaller propensity

### Requirement: The selection width is min(free_slots, f(entropy)) — derived, never triggered

The committed width SHALL be `k = min(free_slots, f(entropy))` where
`f(entropy) = max(1, ceil(h_bits))` over the frontier entropy in bits and
`free_slots` is the slot monitor's own room count. Unknown entropy SHALL
read the conservative floor (1); unknown slot room SHALL leave the demand
unclamped; zero slot room SHALL read k = 0, the forced-null case. `k`, both
inputs, and the derived demand SHALL ride every decision record and row. No
branch in the derivation SHALL test the state against a threshold to pick
the width.

#### Scenario: slot room caps the entropy demand

- **WHEN** the frontier entropy is 2 bits and one slot is free
- **THEN** k = 1; with three slots free k = 2

#### Scenario: no room forces the null action

- **WHEN** zero slots are free
- **THEN** k = 0, the selection is the null action at propensity 1.0, and
  the row still carries the null baseline

### Requirement: The null action is selectable and every decision carries its baseline

The null action SHALL be selectable by the sampler like any other
candidate, and `k = 0` SHALL force it with propensity 1.0. EVERY decision
SHALL carry the null action's own propensity at the same decision point
(the record's `null` block, the row's `null_propensity`), with cost 0 and
value 0. No timer action may be recorded without its same-point do-nothing
baseline.

#### Scenario: the sampler can choose inaction

- **WHEN** the candidate logits favour the null action
- **THEN** the decision's action is `none`, its source is `none`, and its
  propensity is its true sampling probability

#### Scenario: the baseline is present on every row

- **WHEN** any decision is recorded
- **THEN** the row's `null_propensity` is inside (0, 1] and equals the
  record's null block propensity

### Requirement: Selection is a Gumbel top-k without replacement with exact Plackett-Luce propensities

The selection SHALL be a Gumbel top-k WITHOUT replacement over the
candidate logits — an ordered k-subset of distinct members — whose
probability is the product of the sequential Plackett-Luce terms. Under
flat logits over five candidates an ordered pair's propensity SHALL equal
1/20. Replay SHALL be deterministic for an injected rng stream.

#### Scenario: k distinct members, exact pair probability

- **WHEN** a width-3 selection runs under flat logits
- **THEN** three distinct registered members return, and the propensity of
  an ordered pair under flat logits is exactly 1/20

### Requirement: The three budgets ride every decision

The decision recorder SHALL expose `budget_face(ws)` returning exactly
`{tokens, tool_calls, verify_calls}` from single sources: cumulative spend
(the tuition curve's cost state), per-tool-call step-ledger rows, and the
signal stream's verification stamps. Absent sources SHALL read zero and
never raise. The triple SHALL ride the decision record and the logged row.

#### Scenario: seeded sources are reflected exactly

- **WHEN** spend events total 5.5, three tool-call rows exist, and two
  verification stamps are on the stream
- **THEN** the triple reads {tokens: 5.5, tool_calls: 3, verify_calls: 2}
  on the face, the record, and the row

#### Scenario: absent sources read zero

- **WHEN** a workspace carries none of the three sources
- **THEN** the triple reads zeros and no exception escapes

### Requirement: The fixed cron demotes to an armed watchdog, never deleted

Every decision record SHALL carry the cron's demoted role:
`watchdog.role = "watchdog"`, `armed = true`, the polling fallback
interval (the armed cadence interval, else the historical policy default),
and `mode` — `event_first` when the event wake rides the selection, else
`poll_fallback`. The cron registration path SHALL NOT be removed or
rewritten by the decision module; with no advice source present the
historical default interval SHALL stand (default-safe).

#### Scenario: the watchdog stays armed behind an event-first selection

- **WHEN** a decision selects `wake_on`
- **THEN** the record's watchdog block reads role watchdog, armed true,
  mode event_first, with an interval at or above the historical default

#### Scenario: the polling fallback carries a non-event decision

- **WHEN** a decision selects any non-event action
- **THEN** the record's watchdog mode reads poll_fallback and the interval
  is unchanged from the armed cadence
