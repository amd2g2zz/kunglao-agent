# crystallization-writeback-686 delta — issue-686-crystallization-writeback

## ADDED Requirements

### Requirement: A failed step crystallizes one class-level negative with provenance

`crystallize_settlement` SHALL resolve the settled claim's method family
and tool chain from the workspace's usage log (the claim's last usage
row) and, when the step settled as a dispatch failure
(`blocked` / `failed` / `error`), record ONE class-level negative via
the shared negative store. The row SHALL carry the producing claim and
step as `claim_ref` / `step_ref`. A claim with no usage row SHALL write
nothing (the honest gap — no fabricated method).

#### Scenario: a blocked step lands an attributed dead end

- **WHEN** a step for claim `C-007` settles `blocked`, the usage log's
  last row for `C-007` declares family `upx-unpack` with tools
  `["upx", "strings"]`, and the store holds no row for
  (class, `upx-unpack`, `C-007`, the step id)
- **THEN** the negative store gains one `marl-negative/1` row with
  `method_family: "upx-unpack"`, the structural tool-chain token,
  `claim_ref: "C-007"` and `step_ref` set to the settling step
- **AND** `negative_pools` for the class reports failure mass for
  `upx-unpack` (the sampler's β rises at the next planning entry)

#### Scenario: replaying the same settlement writes nothing

- **WHEN** the same (claim, step, outcome) settlement is crystallized a
  second time
- **THEN** no row is appended (the dedupe key
  `(signature_class, method_family, claim_ref, step_ref)` is already
  present) and the receipt reports the duplicate

### Requirement: A completed certified step SHALL broadcast the method, never the answer

When a step settles `completed`, the substrate reports a certified
answer for the claim (knowledge strength at the certified value), the
register carries no decisive failure status for the claim, and the
settle banked a POSITIVE step credit, `crystallize_settlement` SHALL
broadcast the method family through the solution-broadcast face with
that credit, the claim id, and the step id as the dispatch provenance.
ONE broadcast SHALL exist per (claim, method family) — a later
certified step on the same claim is a duplicate, never fresh prior
mass. The broadcast SHALL NOT carry the answer text.

#### Scenario: the final step of a proven claim broadcasts its method

- **WHEN** a step for claim `C-003` settles `completed` with banked
  credit `0.8`, the facts index holds a PROVEN fact answering `C-003`,
  and no broadcast exists for (`C-003`, the family, the step)
- **THEN** the posterior store gains one row with `status: "proven"`,
  the family as `method_family`, `credit: 0.8`, `claim: "C-003"` and
  `provenance.dispatch_id` set to the step id
- **AND** another workspace solving the same claim sees it through the
  cross-task face (the reuse candidate joins its planning set)

### Requirement: Revocation removes every derived row attributed to the claim

`revoke_claim` SHALL atomically rewrite the negative store and the
posterior store without the rows attributed to the claim (negatives by
`claim_ref`, broadcasts by `claim`) and SHALL report per-store removal
counts. Rows attributed to other claims SHALL be byte-identical after
the rewrite.

#### Scenario: a settlement correction kills its discriminants

- **WHEN** the amendment reconcile flips a pair's outcome for claim
  `C-007` (an amendment row lands) and derived rows for `C-007` exist
  in both stores
- **THEN** both stores are rewritten without their `C-007` rows, a
  sibling claim's rows survive untouched, and the reconcile result
  reports the revocation

#### Scenario: revoking a claim with no derived rows is a no-op

- **WHEN** `revoke_claim` runs for a claim with no attributed rows
- **THEN** both stores are unchanged and the counts are zero
