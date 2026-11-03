# probe-pricing-760 delta — issue-760-pricing-face

## ADDED Requirements

### Requirement: the unknown set is a computable projection

The workspace-level unknown set SHALL be a pure projection over
existing keys — primary-question ids via the canonical parse, decision
state via claim-register terminal statuses, open obstacles via the
obstacle registry's active rows — and SHALL persist nothing. An absent
or unreadable source SHALL read as an empty honest contribution (no
fabricated unknowns, no crash).

#### Scenario: undecided vs decided questions

- **WHEN** the register holds a terminal claim answering q-1 and open
  claims answering q-2, and task_spec declares q-1..q-3
- **THEN** unknown_set reports q-1 decided and q-2/q-3 undecided with
  their open-candidate counts, and the counts add up

#### Scenario: retraction is the obstacle's only resolution

- **WHEN** an obstacle row is active
- **THEN** it appears in open_obstacles; after retract() it leaves the
  set (decided knowledge), and a never-recorded id reads absent —
  never fabricated

### Requirement: an information-gathering action carries a deterministic price

price_action SHALL return gain_bits (log2 of the target's live rival
count, floored at one bit for an undecided target; exactly 0 for a
decided or absent target) decayed by REPEAT_DECAY per committed prior
dispatch joined from the issue-800 dispatch ledger, times the value
weight. The computation SHALL be pure (no wall-clock, no RNG) so the
same workspace reads yield identical rows.

#### Scenario: the repeat-probe pin

- **WHEN** a target question is already decided by a terminal claim
- **THEN** its probe's gain is 0 bits and its price is exactly 0 — a
  dead path re-probed N times is N zero-value billings

#### Scenario: high information outprices low information

- **WHEN** q-a holds four live rival candidates and q-b is cold
- **THEN** price_action(q-a) gain is 2 bits, q-b's is 1 bit, and
  q-a's price strictly exceeds q-b's

#### Scenario: the dispatch-ledger decay

- **WHEN** the ledger holds two committed dispatches on q-a's claims
- **THEN** q-a's repeat reads 2 and its price is 0.25x the fresh probe

### Requirement: price rows ride the consolidated telemetry family

Emitted price rows SHALL carry the probe-price/1 stamp, an identity ts
added at emit (never inside the pure computation), and SHALL land in
the issue-721 TELEMETRY family via the consolidation core's append
(stampless rows refused at the boundary).

#### Scenario: emit and count

- **WHEN** price rows for a decided re-probe and a fresh probe are
  emitted
- **THEN** the telemetry family holds both rows under probe-price/1,
  and probe_consumption reports probes=2, zero_info_probes=1, and the
  summed billed price

### Requirement: the consumption and dispatch faces read the price

The issue-801 cockpit consumption face SHALL carry the pricing account
as a `pricing` block (fail-open: an outage drops the block, never the
ratio), and the dispatch supply-admission face SHALL read the claim's
price on the allow path as ONE advisory `probe_price` trace — never a
gate decision; a pricing outage SHALL degrade to
`probe_price_fail_open` with the allow verdict untouched.

#### Scenario: probes are no longer free

- **WHEN** cockpit_ratio persists its face over a workspace holding one
  emitted zero-info price row
- **THEN** the persisted face carries pricing.probes == 1 and
  pricing.zero_info_probes == 1

#### Scenario: the advisory read never gates

- **WHEN** the supply-admission face resolves a linked claim on a
  workspace with a readable pricing face
- **THEN** it returns the allow verdict unchanged and rides one
  probe_price trace naming target/status/gain/repeat/price
