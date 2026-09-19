# Spec Delta — hypothesis bridge (issue #252)

## ADDED Requirements

### Requirement: Hypothesis families SHALL mint arms as claims

A hypothesis candidate SHALL enter the economy as an OPEN claim in
claim-register.yaml carrying the family linkage
`competitor_group: hyp-<H-id>` and `hypothesis_ref: <H-id>` (the #234
edge-field style), minted through the normal mint path (register
append + the single claim-ID grammar). Minted arms SHALL be
TS-samplable (`priority_ratio.is_open`). Minting SHALL be idempotent
by the (origin, hypothesis_ref, arm_key) marker — never by text.
A minted candidate MUST NOT also appear as a store candidate string
(no second representation).

#### Scenario: family arms enter the TS rank pool

- **WHEN** hypothesis H-001 exists and `mint_family_arms` mints two
  candidates
- **THEN** claim-register.yaml holds two OPEN claims with
  competitor_group hyp-H-001 and hypothesis_ref H-001, and
  `priority_ratio` ranks them (is_open true)

#### Scenario: minting is idempotent and never duplicates the representation

- **WHEN** the same candidates are minted again, and the hypothesis
  file is inspected after minting
- **THEN** no duplicate claims exist and the hypothesis carries no
  candidate strings (the claim is the one representation)

### Requirement: The store SHALL demote to the family ledger synced from claim settlements

Hypothesis state SHALL sync FROM the settlement statuses of its family
member claims, using the #528 transitions unchanged: any arm
PROVEN/VERIFIED -> the family hypothesis confirmed (confirming
reference = the winning arm claim id) and every OTHER open hypothesis
in the same competitor_group superseded (superseded_by = the family
id); all arms terminal with at least one NEGATIVE -> refuted
(refuting reference = a NEGATIVE arm id only — a DEFERRED/STALE-only
family is budget exhausted, not a refutation, and SHALL stay
pending); otherwise the family stays open. On family resolution,
losing OPEN arms SHALL retire claim-level SUPERSEDED
(superseded_by = the winning arm id) so a decided question leaves the
TS rank pool. The sync SHALL run from the claim settlement writer
(kunglao_record.claim_migrator), SHALL be guarded (a sync failure MUST
NOT fail the settlement and MUST emit a visible WARN), and terminal
hypotheses MUST NOT be rewound. An already-adjudicated family SHALL be
reported unchanged (no duplicate settlement events).

#### Scenario: a proven arm resolves its family and supersedes competitors

- **WHEN** one arm of family hyp-H-001 settles PROVEN and another open
  hypothesis shares H-001's competitor_group
- **THEN** H-001 is confirmed with confirming_fact_id naming the arm,
  the competitor hypothesis is superseded naming H-001, and every
  losing OPEN arm of both families is claim-level SUPERSEDED with
  superseded_by = the winning arm (out of the TS rank pool)

#### Scenario: all arms settle negative and the migration survives a sync crash

- **WHEN** every arm of a family settles REFUTED/NEGATIVE through
  claim_migrator, and separately the sync raises
- **THEN** the hypothesis is refuted with a NEGATIVE-arm refuting
  reference, and in the crash case the migration still reports success
  with a family_sync_failed WARN

#### Scenario: deferred-only arms never refute

- **WHEN** every arm of a family is DEFERRED or STALE (no NEGATIVE
  arm)
- **THEN** the family stays open (pending) with no refuting reference

### Requirement: Candidate-fillers SHALL route into hypothesis families at their existing mint sites

The #234 strategy siblings and #250 situational epistemic claims SHALL
carry the family linkage stamped at their existing mint sites
(target_ladder.mint_sibling_claims, plan_epistemics.mint_workspace) —
no new pipelines, no re-minting, no double representation (#250 claims
keep boundary_type: epistemic). A pq-family scaffold SHALL be reused
when present (the #109 binding shapes) and created otherwise. Legacy
candidate strings in hypotheses/ SHALL be payable into the economy by
the sweep face (mint -> clear the string).

#### Scenario: #234 siblings join a family without re-minting

- **WHEN** target_ladder mints strategy siblings for a walked obstacle
- **THEN** each new sibling carries competitor_group hyp-<H-id> +
  hypothesis_ref for one family hypothesis (marker
  obstacle-family:<claim_id>), and no additional arm claims are minted

#### Scenario: #250 unknowns join the pq-family ledger

- **WHEN** plan_epistemics mints situational unknowns for a workspace
  whose pq scaffold exists (or not)
- **THEN** each minted epistemic claim carries the family linkage of
  the existing (or newly ensured) pq-bound hypothesis, and the claim
  keeps boundary_type epistemic

#### Scenario: legacy candidate strings are paid, not parked

- **WHEN** a hypothesis carries candidate strings (e.g. apkid-derived)
  and the sweep runs (the cold-start chain)
- **THEN** each string is minted as a family arm and cleared from the
  hypothesis file

### Requirement: Writes to hypotheses/ SHALL NOT bypass the claim mint

Candidate strings parked in hypotheses/ without a claim mint SHALL be
lint errors (the no-orphan-representation guard), as is a claim
carrying `competitor_group: hyp-<id>` whose hypothesis file is missing
or which lacks the mint-issued `hypothesis_ref` marker (namespace
capture). An OPEN family whose member claims already derive
confirm/refute SHALL be a derivation-divergence error (the ledger sync
did not run — the persistent-crash detector), repaired by the sync.
Modules that write to hypotheses/ without minting claims SHALL be
pinned to the explicit scaffold/adjudication/settlement allowlist
(scanned over scripts/ AND hooks/); a new writer bypassing the bridge
is a lint failure. The guard SHALL run at the cold-start face (the
digest), not only via the CLI.

#### Scenario: parked candidates are named by the guard

- **WHEN** a hypothesis holds candidate strings and no arm claims were
  minted from them (the sweep has not run / a path bypassed it)
- **THEN** check_bridge_lint errors naming the hypothesis and its
  unminted candidates

#### Scenario: orphan family claim errors

- **WHEN** a claim declares competitor_group hyp-H-999 with no
  hypotheses/H-999.md on disk
- **THEN** check_bridge_lint errors naming the orphan claim and the
  missing family file

#### Scenario: a namespace claim without the mint marker errors

- **WHEN** a claim declares competitor_group hyp-H-001 (a valid family
  reference) but carries no matching hypothesis_ref edge field
- **THEN** check_bridge_lint errors (E2b), the sync never adjudicates
  H-001 from that claim, and an external q_id cannot capture the
  namespace

#### Scenario: derivation divergence is flagged and repaired

- **WHEN** an OPEN family's member claims already derive confirm or
  refute (the sync crashed after a settlement)
- **THEN** check_bridge_lint errors (E3) and a subsequent sync clears
  the finding

#### Scenario: a minted-economy workspace lints clean

- **WHEN** every candidate string has been swept/minted and every
  hyp-* claim resolves to its family file with its mint marker
- **THEN** check_bridge_lint returns no errors

### Requirement: The PQ admission gate SHALL count family arms

The #109 first-dispatch admission read SHALL count the union of the
transitional store candidate strings AND the minted family arm claims
(OPEN, mint-issued, whose family hypothesis is bound to the PQ via the
#109 shapes or a claim_id->answers_question link), so the sanctioned
arm-mint path passes first dispatch on a lint-clean (swept) workspace.
The REJECT repair text SHALL name the mint path first. The bar stays
on COMPETING EXPLANATIONS: fewer than two counted explanations still
rejects.

#### Scenario: arm-minted workspace passes first dispatch

- **WHEN** a sweep-drained (lint-clean) workspace's pq scaffold has
  mint_family_arms arms minted, and the first dispatch into the PQ
  arrives
- **THEN** the admission gate counts the arms and the dispatch is
  admitted without any parked candidate string

#### Scenario: one arm alone still rejects

- **WHEN** only one family arm exists for the PQ and the first
  dispatch arrives
- **THEN** the admission gate rejects naming the #109 face and the
  mint repair path
