# step-credit-712 delta — issue-712-step-level-credit

## ADDED Requirements

### Requirement: The step boundary scores and banks a step credit

`rlvr.step_credit.evidence_in_window` SHALL score only the evidence the
step itself touched — fact files whose mtime falls in the half-open
window `(previous settled step ts, this settle]` (first step: the
dispatch-launch stash ts) and whose exact claim channels (`claim_id` /
`claim_ids` / `claims` / `creator`) name the pending claim — and
`step_credit` SHALL grade each item as cross-validated (terminal status
`PROVEN`/`VERIFIED`/`NEGATIVE` with `verify_status: passes`) = 1.0,
unverified (any other status/gate pair, and the empty-evidence window) =
0.3, refuted (`status: REFUTED` or `verify_status: fails`) = 0.0, each
multiplied by the source-reliability weight of the fact's worst
provenance Admiralty letter when present. `rlvr.step_grain.settle_step`
SHALL bank that score into the claim's pending-dispatch Q cell at the
SubagentStop boundary (a `credit_kind: "step"` observation, admissible
to the fold like solve credit) BEFORE any claim-terminal settlement, and
every scoring/banking failure SHALL be fail-open (ONE warn, the settled
step row and transition stand).

#### Scenario: the stop banks the credit

- **WHEN** a dispatch-launch stash and a pending dispatch row exist, a
  fact naming the claim sits inside the step window, and `settle_step`
  runs
- **THEN** runs/q-cell-log.jsonl gains one `credit_kind: "step"` row
  whose credit is 1.0 and no round-credit ledger settlement exists yet

#### Scenario: a scoring failure never undoes the settle

- **WHEN** the evidence window is undecidable (unparseable launch ts)
- **THEN** the step settles normally and the banked step credit is the
  0.3 provisional floor

### Requirement: A ten-step rollout produces ten learning signals

Ten subagent completions SHALL produce ten `credit_kind: "step"`
observations and ten transition rows (O(steps), never O(claims)), and
each banked cross-validated step SHALL strictly increase the cell's
folded success mass at the explicit γ=1 read (refuted steps increase
failure mass; band-valued information options move no mass), all
BEFORE the claim's terminal settlement exists.

#### Scenario: dense accrual during the rollout

- **WHEN** a claim runs ten steps, each touching one cross-validated
  fact in its own window
- **THEN** the q-cell log carries ten step rows, the transition ledger
  carries ten rows, the cell's success mass after the tenth step is 10.0
  at γ=1, and no round-credit ledger row exists

### Requirement: Claim-terminal calibration corrects the cumulative Beta

`scalar._bank_q_cell_credit` SHALL bank ONE signed
`credit_kind: "step_calibration"` residual row when step credit already
exists for the dispatch being settled (`q_cells.step_credit_totals`
n > 0): Δsuccess = clamp01(ladder) − Σ(step credit) and Δfailure =
(1 − clamp01(ladder)) − Σ(1 − step credit), where the sums SHALL count
ONLY the step rows that became fold mass (credit == 0.0 or above the
observation band — band-valued information-option rows banked no mass
and SHALL count in neither term). The fold SHALL apply both
deltas verbatim after the row's γ weight (no clamp, no observation
band, no Φ tiebreak) and SHALL exclude calibration rows from the γ
schedule's EMA. Cumulative success after the row SHALL equal the ladder
value (over-credit clawed back, under-credit topped up) and the folded
endpoint SHALL equal the step-less endpoint for the same ladder value.

#### Scenario: over-credit is clawed back

- **WHEN** three cross-validated steps bank Σ=3.0 and the claim
  settles with ladder credit 1.0
- **THEN** the calibration row's credit is −2.0 and the cell folds to
  (success 1.0, failure 0.0) at γ=1

#### Scenario: under-credit is topped up

- **WHEN** one provisional step banks 0.3 and the claim settles with
  ladder credit 1.0
- **THEN** the cell folds to (success 1.0, failure 0.0) at γ=1 — the
  0.7 provisional failure mass washed out with the top-up

#### Scenario: the endpoint is independent of step count

- **WHEN** two workspaces settle the same cited ladder value, one after
  three provisional steps and one with no steps
- **THEN** both cells fold to identical success and failure masses

### Requirement: Settlement without step credit stays byte-identical

`scalar._bank_q_cell_credit` SHALL keep a dispatch with NO step-credit
rows (n = 0) on the unchanged `observe_settlement` face: no
`credit_kind` column on the settlement row, no calibration row, and
fold arithmetic identical to pre-#712 — a claim that settled before
this change SHALL work unchanged.

#### Scenario: a step-less claim banks the legacy row

- **WHEN** a pending dispatch row with no step credit settles with a
  cited full-credit artifact
- **THEN** exactly one settlement row exists carrying no `credit_kind`
  key and credit 1.0, no `step_calibration` row exists, and the cell
  folds to (1.0, 0.0) at γ=1
