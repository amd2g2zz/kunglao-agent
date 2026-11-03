# learning-channel-seal-799 delta — issue-799-seal-learning-channel

## ADDED Requirements

### Requirement: The learning seal is the #736 construction on a dedicated key

The seal SHALL HMAC-SHA256 (NUL-joined payload, `hmac.compare_digest`
verify) a versioned schema stamp + canonical record sha, keyed at a
fixed path outside the workspace with no env override face, minimum key
length 32. Without a provisioned key the channel SHALL ride legacy
byte-identically with ONE loud per-process notice.

#### Scenario: unarmed channel is legacy

- **WHEN** no learning key is provisioned
- **THEN** stashes/rows write and settle exactly as before (positive
  control for INV-003), and the notice names the repair path once

### Requirement: Writers seal every reward-bearing record

`record_launch`, `append_transition`, `q_cells.append_observation`,
`strategy_store.append_row` and `append_workspace_credit_row` SHALL
append a valid `learning-seal/1` seal block when armed. Sealing SHALL
NOT alter any pre-existing column (additive key only).

#### Scenario: sealed write stays byte-additive

- **WHEN** a row is written armed vs unarmed with identical inputs
- **THEN** the armed row equals the unarmed row plus exactly the
  `"seal"` key

### Requirement: Learners refuse unsealed or forged rows fail-closed

Every learner input row SHALL carry a valid HMAC when armed; forged or
unsealed rows are refused with a loud telemetry event and the posterior
stores stay byte-unchanged on refusal.

#### Scenario: forged launch-stash edit banks nothing

- **WHEN** a launch stash is edited mid-flight (phi -> 0.0) and the
  settle face runs
- **THEN** `append_transition` refuses, the stash file is left intact,
  no transition row banks, and the warn names the seal failure

#### Scenario: forged q-cell row never folds

- **WHEN** a raw credit row is appended into the experience file
  without a seal and the fold runs
- **THEN** the row contributes no success/failure/pending mass and the
  file bytes are unchanged

#### Scenario: forged posterior-store row never warms a pool

- **WHEN** an unsealed `posterior-store/1` row lands in the shared
  store and `load_rows` / `warm_pools` / the refutation fold read
- **THEN** the row is dropped with one loud warn per refusal

### Requirement: Worker-typed status alone cannot settle step credit 1.0

When armed, a `credit_kind: "step"` row above the unverified floor
(0.3) SHALL bank at the floor unless the caller carries a valid seal.

#### Scenario: worker-typed PROVEN is capped

- **WHEN** a fact with `status: PROVEN` + `verify_status: passes`
  produces step credit 1.0 at an armed SubagentStop with no seal
- **THEN** the banked row carries the floor (0.3), the fold moves
  (0.3, 0.7) mass — never (1.0, 0.0) — and the warn names the cap

### Requirement: The oracle dim trusts only sealed oracle-status (#601 L7)

When armed, `potential` SHALL treat `runs/oracle-status.json` as honest
absence unless its seal verifies; the canonical shape alone is never
sufficient.

#### Scenario: full-shape forgery moves nothing

- **WHEN** a canonical all-pass oracle-status doc without a valid seal
  is planted
- **THEN** Φ renormalizes over the remaining dims (the oracle dim is
  dropped) and the warn names the unsealed face

### Requirement: Propensity rides only a receipt match (#601 L8)

A transition row's propensity SHALL survive only when it equals the
sealed sampler receipt's (source=dispatch q-cell row) recipe propensity
for the claim within 1e-6; otherwise the column is dropped with a loud
warn.

#### Scenario: fiat propensity 1.0 is dropped

- **WHEN** a stash carries `propensity: 1.0` with no matching sealed
  receipt
- **THEN** the banked row omits the propensity column (SNIPS falls
  back) and the warn names the cross-check

#### Scenario: receipt-matched propensity survives

- **WHEN** the stash propensity equals the sealed dispatch receipt's
  recipe propensity
- **THEN** the row keeps the propensity value unchanged

### Requirement: The run head anchors the build version and a mid-run change is a loud refusal

The seal channel SHALL anchor the build version (the receipt-checked
single source — `template_version.read_skill_version`, the rc2 8-surface
version mechanism) at its FIRST armed seal operation in a process (the
run head), stamp every minted seal block with that build inside the HMAC
payload (tamper-evident), and re-check the live version at every mint.
A mid-run version change SHALL refuse the mint — a loud event, never a
warn-and-continue — and a seal minted by a build other than the
anchored one SHALL fail verification (mixed-build rows never fold).
Unarmed, the channel rides legacy byte-identically (no version face).

#### Scenario: mid-run build swap refuses mints

- **WHEN** the build version source changes after the run head anchored
  (production: a web run rode two builds at once after a skill-tree
  swap mid-run)
- **THEN** `sign_row` refuses to seal with a loud warn naming both
  versions, the row rides unsealed, and armed learners refuse it —
  nothing banks

#### Scenario: cross-build seal is refused at read

- **WHEN** a seal minted by build A is verified by a process whose run
  head anchored build B
- **THEN** `verify_row` fails with the version-skew reason and the
  learner drops the row with ONE loud warn

### Requirement: Settlement lines carry reward and confidence band

The settlement credit row banked into the sealed learning stream SHALL
carry additive `reward` and `confidence_band` columns when the caller
supplies them (absent when not supplied — legacy rows byte-identical,
additive-key discipline), so the event stream self-documents what
reward banked and at which band (production: reward/band had zero
presence in the event stream).

#### Scenario: settlement row carries reward and band

- **WHEN** the scalar first-bank face settles a dispatch's ladder value
- **THEN** the sealed settlement row carries `reward` equal to the
  settled ladder value and `confidence_band` equal to the settlement
  band, both covered by the seal's canonical record sha

#### Scenario: unsupplied columns stay absent

- **WHEN** a settlement banks without reward/band supplied
- **THEN** the row equals the pre-R2 shape exactly (no empty columns)
