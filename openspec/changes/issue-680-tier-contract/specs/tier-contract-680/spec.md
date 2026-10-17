# tier-contract-680 delta — issue-680-tier-contract

## ADDED Requirements

### Requirement: The dispatch envelope's tier shall match the claim's action_tier

The tier-consistency gate SHALL compare the dispatch envelope's declared
`tier` against `priority_ratio.action_tier(claim)`
(`min(evidence_tier_attempted+1, 3)`), via
`worker_budget_gates.check_tier_consistency(reg_path, claim_id, tier,
prompt)`. A mismatch SHALL REJECT the dispatch with the correct derived
tier in the guidance, with exactly three exceptions: (a) the dispatch
prompt carries a recorded deviation (`agent-reasoning:` prefix), in
which case the deviation is recorded on stderr and the dispatch
proceeds; (b) the dispatch is a verifier-remediation dispatch (a
verifier-class agent for a PROVEN claim — the #237 D2 pass-through), in
which case the gate is skipped entirely, because a redteam/verdict-
scorer tier is not the claim's evidence-ladder step and gating it would
re-create the blocked-remediation deadlock class; (c) the shape is
uncheckable (no claim id, claim not in the register, priority_ratio
unavailable), which allows. The gate SHALL run before the tier-ladder
gate in the `pre_check` battery.

#### Scenario: envelope tier above the claim's action_tier is rejected

- **WHEN** a claim with `evidence_tier_attempted=0` (action_tier=1) is
  dispatched with an envelope declaring `tier=2`
- **THEN** pre_check REJECTs with `tiercons` and names tier=1 as the
  correct value

#### Scenario: a recorded deviation allows the mismatch

- **WHEN** the same mismatched dispatch prompt carries
  `agent-reasoning: <why>`
- **THEN** pre_check allows the dispatch and prints
  `TIER (deviation recorded)` on stderr

#### Scenario: a verifier-remediation dispatch is never gated on tier

- **WHEN** a kunglao-redteam dispatch for a PROVEN claim (the #237 D2
  remediation) carries a tier that differs from the claim's action_tier
- **THEN** pre_check does NOT reject with `tiercons` (the gate is
  skipped, same pass-through as the drift gate)

#### Scenario: a consistent envelope passes

- **WHEN** the envelope's tier equals `min(eta+1, 3)` for the target claim
- **THEN** the tiercons gate passes (and the breadth-first ladder gate
  still applies independently)

### Requirement: Every ALLOW dispatch shall raise the claim's evidence_tier_attempted

`worker_budget_sinks._write_eta_at_dispatch(paths, cid, tier)` SHALL, at
the pre_check ALLOW tail (the approval point), raise the dispatched
claim's `evidence_tier_attempted` to `max(current_eta, tier)` — the
monotonic ATTEMPTED-semantics writer the ladder gate always lacked. The
write SHALL use the ws_yaml canonical renderer (single-writer discipline)
and SHALL be fail-open (absent register or unknown claim is a no-op; the
dispatch verdict never changes).

#### Scenario: an ALLOW dispatch climbs the ladder

- **WHEN** a claim with eta=0 is dispatched at tier=1 and pre_check
  returns 0
- **THEN** the register carries `evidence_tier_attempted: 1` for that
  claim

#### Scenario: a cheaper re-dispatch never lowers attempt history

- **WHEN** a claim with eta=2 is dispatched at tier=1 (via a recorded
  deviation) and pre_check returns 0
- **THEN** the claim's `evidence_tier_attempted` remains 2

### Requirement: The rank_feeds payload shall carry the per-claim tier

`priority_ratio._emit_rank_feeds` SHALL include an additive `tiers` key
(claim id -> `action_tier`) in the rank_feeds payload; existing keys
(`feeds`, `scores`, `ranked_order`, `input_fingerprint`) SHALL remain
byte-identical in meaning. `Action.to_dict()` SHALL include the `tier`
field (additive).#### Scenario: the decision face can read the derived tier

- **WHEN** a priority_ratio run emits its rank_feeds event
- **THEN** the payload's `tiers` maps each ranked claim to
  `min(eta+1, 3)` and every pre-#680 key is still present

#### Scenario: --json consumers see the tier

- **WHEN** an `Action` with tier=2 is serialized via `to_dict()`
- **THEN** the dict carries `"tier": 2` alongside the existing keys
