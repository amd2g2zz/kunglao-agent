# Spec Delta — issue-688-decision-view

## ADDED Requirements

### Requirement: The rank_feeds payload carries four additive decision-view keys

The `rank_feeds` event payload SHALL carry, beside the existing
`feeds` / `scores` / `ranked_order` / `input_fingerprint` keys, exactly
four additive top-level keys computed as pure functions of the run's
ranked actions: `k` (the ranked candidate count), `propensity` (the
top-ranked arm's share of the total score mass, rounded to 6 decimals),
`entropy` (the Shannon entropy in bits of the normalized score
distribution over the ranked candidates, rounded to 6 decimals), and
`tiers` (a `{claim_id: tier}` map over the ranked candidates). The
`input_fingerprint` document SHALL remain exactly the four input fields
(`claims_hash`, `evidence_hash`, `rng_base`, `round`) plus its hash —
the new keys SHALL NOT enter the fingerprint. Same-seed runs SHALL
produce identical values for all four keys (payload replay equality),
and degenerate runs SHALL degrade honestly: an empty ranking yields
`k=0`, `entropy=null`, `propensity=null`, `tiers={}`; a single-candidate
ranking yields `entropy=0.0` and `propensity=1.0`; a multi-candidate
ranking whose scores sum to zero yields `entropy=null` and
`propensity=null`. The emit SHALL remain silent fail-open: a crash
inside the payload build still marks the emit-failure marker and never
reaches the ranking result.

#### Scenario: a normal run persists all four keys

- **WHEN** a rank run ranks two or more candidates with positive scores
- **THEN** the payload carries `k` equal to the ranked candidate count,
  `tiers` mapping every ranked claim id to its action tier,
  `propensity` equal to the top score divided by the total score, and
  `entropy` equal to the Shannon entropy in bits of the normalized
  score distribution

#### Scenario: the fingerprint is untouched by the new keys

- **WHEN** a rank run emits its payload
- **THEN** `input_fingerprint` contains exactly `claims_hash`,
  `evidence_hash`, `rng_base`, `round`, and `fingerprint`, and the
  hash still equals the SHA-256 of the first four fields

#### Scenario: same seed replays identical view keys

- **WHEN** the ranker runs twice with the same rng seed and inputs
- **THEN** the two payloads are byte-equal, including `entropy`,
  `propensity`, `k`, and `tiers`

#### Scenario: an empty ranking degrades honestly

- **WHEN** the emit runs with zero actions
- **THEN** the payload carries `k=0`, `entropy=null`,
  `propensity=null`, and `tiers={}`

#### Scenario: a single candidate is fully determined

- **WHEN** the emit runs with exactly one action
- **THEN** `entropy` is `0.0` and `propensity` is `1.0`

#### Scenario: zero score mass cannot be normalized

- **WHEN** the emit runs with two or more actions whose scores sum to
  zero
- **THEN** `entropy` and `propensity` are both `null` while `k` and
  `tiers` still describe the ranking

### Requirement: The decision view model exposes six faces with fixed keys

The decision view model (`scripts/decision_view.py`) SHALL expose a
`SCHEMA` stamp, a `FACES` tuple of exactly the six faces
(`in_flight`, `why_this_one`, `just_settled`, `hypothesis_space`,
`budget`, `next_candidates`), a `FACE_KEYS` mapping from every face to
its required key tuple, and a `build_view(ws)` function returning
`{"schema", "faces"}`. `build_view` SHALL NEVER raise: every face
builder SHALL degrade to its documented absent shape (all required keys
present, values null/empty) when its source is missing, unreadable, or
raises. The budget face SHALL carry the three slots `tokens`,
`tool_calls`, `verify_calls` as nulls with `accounted: False` — the
documented upstream blocker, never fabricated zeros.

#### Scenario: an empty workspace still yields all six faces

- **WHEN** `build_view` runs against a workspace with no register, no
  events, no ledger, and no posteriors
- **THEN** the result carries `schema` and exactly the six `FACES`,
  each face containing every key its `FACE_KEYS` entry requires, and no
  exception escapes

#### Scenario: a broken source degrades only its own face

- **WHEN** the newest rank_feeds payload reader raises (e.g. monkeypatched
  to raise) while other sources are healthy
- **THEN** `build_view` returns normally with `why_this_one` and
  `next_candidates` in their documented absent shapes and the remaining
  faces built from their sources

#### Scenario: budget is honest about the accounting blocker

- **WHEN** `build_view` runs on any workspace
- **THEN** `budget.tokens`, `budget.tool_calls`, and
  `budget.verify_calls` are null and `budget.accounted` is `False`

### Requirement: The rationale and candidate faces read the persisted payload keys

`why_this_one` SHALL read the newest `rank_feeds` payload through the
rank-face single source: the top claim, its score, its `feeds`
diagnostic, the persisted `entropy` / `propensity` / `k` keys, and the
row's recency (ts / age_s / stale). `next_candidates` SHALL project the
payload's `ranked_order` × `scores` × `tiers` into rows of
`{claim, score, tier}` sliced to a named top-k constant. Payloads
written before this change (rows lacking the new keys) SHALL degrade
honestly: `entropy`/`propensity` null, `k` falling back to the ranked
order length, per-row `tier` null — never an exception.

#### Scenario: after a real rank run the faces carry the selection rationale

- **WHEN** a rank run emits `rank_feeds` and then `build_view` runs
- **THEN** `why_this_one.claim` equals the run's top claim,
  `why_this_one.entropy` and `why_this_one.propensity` equal the
  persisted payload values, and `why_this_one.k` equals `k`

#### Scenario: next candidates carry score and tier per row

- **WHEN** a rank run with two ranked candidates emits and
  `build_view` runs
- **THEN** `next_candidates.candidates` lists the ranked claims in
  order with their persisted scores and tiers, and
  `next_candidates.k` equals the persisted `k`

#### Scenario: legacy payloads degrade honestly

- **WHEN** the newest rank_feeds row predates the additive keys
- **THEN** `why_this_one.entropy` and `why_this_one.propensity` are
  null, `k` equals the length of `ranked_order`, and `build_view`
  does not raise

### Requirement: The settled and hypothesis-space faces read single-source ledgers

`just_settled` SHALL read the newest settled rollout through
`rlvr.ledger.settled` (anchor, kind, band, reward, ts) and degrade to
its absent shape when the ledger is empty or unreadable.
`hypothesis_space` SHALL count register claims by canonical status
class (alive = ACTIVE, parked = SUSPENDED, pruned = RETRACTED,
terminal = TERMINAL, other = anything else) and carry the frontier
entropy face (`h_bits`, `h_pq`, `h_trend`) from the entropy single
source. `in_flight` SHALL list claims whose status is in
`IN_PROGRESS_STATUSES` plus the round's leading method family from the
strategy object, absent-shape null when no strategy object exists.

#### Scenario: a settlement surfaces in the view

- **WHEN** a task rollout is recorded and settled in the ledger and
  `build_view` runs
- **THEN** `just_settled.anchor`, `just_settled.band`, and
  `just_settled.reward` equal the settled row's values

#### Scenario: register statuses bucket into the hypothesis space

- **WHEN** the register holds claims in OPEN, IN_PROGRESS, PARK,
  RETRACTED, and PROVEN statuses and `build_view` runs
- **THEN** `hypothesis_space.alive` counts OPEN+IN_PROGRESS,
  `parked` counts PARK, `pruned` counts RETRACTED, `terminal` counts
  PROVEN, and the face carries the entropy single source's keys

#### Scenario: in-flight lists the claims being worked

- **WHEN** the register holds one IN_PROGRESS claim and one OPEN claim
- **THEN** `in_flight.claims` contains exactly the IN_PROGRESS claim id
  and `in_flight.count` is 1
