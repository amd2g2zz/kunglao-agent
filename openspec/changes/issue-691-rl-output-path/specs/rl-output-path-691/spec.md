# rl-output-path-691 delta — issue-691-rl-output-path

## ADDED Requirements

### Requirement: Every approved dispatch declaration records the sampler view

The dispatch usage row SHALL record the sampler view beside every
declaration: for every dispatch that passes the method-family vocabulary
gate, `runs/method-family-log.jsonl` carries one row with three additive
fields — `propensity` (the sampler's draw
probability of the DECLARED family, rounded to 6dp), `sampled_family`
(what the gate's own draw would have chosen) and `prior_source`
(history | llm_prior | store). When no proposal material exists or the
sampler fails, the fields SHALL degrade to explicit nulls with one
rate-limited warn — telemetry never turns an ALLOW into anything else,
and a fabricated number is never written (0.0 means "the draw could
never have chosen it", null means "no view").

#### Scenario: a declaration the sampler would have chosen

- **WHEN** the workspace's proposal history holds one registered family
  and the dispatch declares that same family
- **THEN** the usage row carries `sampled_family` equal to the
  declaration, `propensity` of 1.0 (the sole candidate), and
  `prior_source: history` — and no deviation event fires

#### Scenario: a declaration outside the sampler's support

- **WHEN** the proposal history holds only `static-decompile` and the
  dispatch declares the registered `dynamic-trace`
- **THEN** the usage row records `sampled_family: static-decompile`,
  `propensity: 0.0` and `prior_source: history` — the sampler could
  never have picked the declared family, and the row says so

### Requirement: A deviation from the sampler is a recorded decision, never a reject

A deviation from the sampler SHALL be recorded and SHALL never reject:
when the declared method family differs from the gate's own draw, the
gate emits exactly one unified-log `sample_deviation` event (a
registered `EMIT_ACTIONS` word) carrying the declared family, the
sampled family, the logged propensity, the prior source, and the
dispatch's own recorded reason when the prompt declares one — and the
dispatch still passes. The reconciliation adds no REJECT face and
no new prefix bypass; vocabulary validation remains the gate's only
REJECT (2026-10-14 acceptance amendment).

#### Scenario: a plain deviation is recorded, not silent

- **WHEN** the declared family differs from the sampled family and the
  prompt carries no deviation excuse
- **THEN** `pre_check` returns 0 (pass) and one `sample_deviation`
  event lands in `runs/logs/` with `declared`, `sampled`,
  `propensity`, `prior_source` and a null `reason`

#### Scenario: an agent-reasoning deviation is recorded with its reason

- **WHEN** the declared family differs from the sampled family and the
  prompt carries an `agent-reasoning:` line
- **THEN** `pre_check` returns 0 and the `sample_deviation` event
  carries the reasoning text as its `reason` — the prefix that excuses
  the top-1 claim rank elsewhere never silences the family record

### Requirement: The gate's draw shares one implementation with the advisory lead and labels its prior source

`PosteriorStrategyStore.method_lead` SHALL derive its return value from
`method_sample(fp)` — one draw implementation (labeled prior chain,
`q_cells_seed_state` seed, feature/warm/death kwargs) behind both the
advisory lead and the gate's reconciliation, so the two faces cannot
disagree on the same state. The receipt SHALL carry an additive
`prior_source` distinguishing the measured declaration history
(`history`) from the explicit `runs/llm-prior.json` intake doc
(`llm_prior`) and the cross-task store fallback (`store`), without
changing `_proposal_prior`'s signature or the kernel receipt shape.

#### Scenario: a cold workspace with an explicit intake prior

- **WHEN** the workspace has no declaration history but carries a
  valid full-coverage `runs/llm-prior.json`
- **THEN** `method_sample` draws over the intake prior and the receipt
  labels `prior_source: llm_prior` — a prior the workspace was TOLD is
  distinguishable from one it earned

#### Scenario: the recorded view matches the lead

- **WHEN** `method_lead(fp)` and `reconcile_declaration(ws, declared)`
  run over the same unchanged workspace state
- **THEN** both name the same `sampled_family` (one draw
  implementation), so a matched declaration is reconciled against the
  very draw the orchestrator was shown

### Requirement: Settlement moves the linked CasePosterior and the claim rank follows

Settlement SHALL move the linked CasePosterior and the claim rank SHALL
follow: given open claims linked to `oracle/cases/*.yaml` by `target_pq`,
the rank samples `Thompson Beta over N linked` from
`runs/posteriors.yaml` when the ledger exists, and
`settle_round_credit.record_case_settlements` moves the linked
`CasePosterior` (+1 alpha on a PROVEN/VERIFIED settlement, +1 beta on a
REFUTED/NEGATIVE one) such that a subsequent rank orders the claims by
the moved posteriors — the output path from settlement into claim
ranking is verifiable end to end.

#### Scenario: a settlement flips the rank order

- **WHEN** two open claims rank on cold Beta(1,1) posteriors and
  settlements drag the leader's linked case down and boost the
  trailer's linked case up through `record_case_settlements`
- **THEN** `runs/posteriors.yaml` is generated with the moved
  alphas/betas (schema `posteriors-schema/1`) and the next rank orders
  the claims in reverse — the posterior moved the rank, and the feeds
  keep reporting linked-case Thompson rather than cold-start
