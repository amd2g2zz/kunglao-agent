# issue-691-rl-output-path — the RL's output path into decisions

## Why

Issue #691: the reward has no output path into decisions. The sampler
(`q_cells.sample_method_family`) implements the intended semantics
(weight = P_LLM · θ, proportional draw — the LLM is the prior, the
sampler is the choice operator), but the orchestrator DECLARES
`method_family` itself and the sampler's output is only advisory prose
(`method_lead` → `rl_digest`). Measured on the live workspace: 16
declaration rows in `runs/method-family-log.jsonl` with NO propensity
and NO sampled-vs-declared reconciliation, and 542/542 `rank_feeds`
events saying `cold-start exploration` (0 saying `Thompson Beta over N
linked`). Fixing the reward (#678) therefore raises settlement from 0.0
and still changes no behavior — learning would be measurable but inert.
The 2026-10-14 acceptance amendment constrains the fix shape: reconcile
declaration vs sample per dispatch as RECORDED ROWS, and NOT add another
rule gate — exception paths must be decisions with recorded reasons,
never a new prefix bypass.

## What Changes

1. **The declaration reconciliation (T2)** — `_method_family_gate`
   (the #432 validation chokepoint) reconciles every validated
   declaration against the gate's OWN sampler draw
   (`rlvr.strategy_store.reconcile_declaration` — the same face
   `method_lead` renders, recomputed at dispatch time so nothing the
   envelope says can move it). `append_usage_row` gains three additive
   fields: `propensity` (the sampler's draw probability of the DECLARED
   family; 0.0 when it is not a candidate at all, null when the sampler
   view is unavailable), `sampled_family`, `prior_source`. A deviation
   (declared != sampled) emits one unified-log `sample_deviation` event
   carrying the logged propensity and the dispatch's recorded
   `agent-reasoning:` reason when present — recorded, NEVER rejected
   (fail-open + warn; vocabulary validation stays the gate's only
   REJECT face).
2. **The labeled prior (T3)** — `PosteriorStrategyStore` gains
   `proposal_prior_labeled()` (source ∈ history | llm_prior | none) and
   `method_sample(fp)`, the receipt-bearing twin of `method_lead`
   (ONE draw implementation behind both faces — the advisory lead and
   the gate's reconciliation can never disagree on the same state). The
   receipt carries the additive `prior_source` label so a prior the
   workspace EARNED (measured declaration history) is distinguishable
   from one it was TOLD (the explicit `runs/llm-prior.json` intake doc)
   and from the cross-task store fallback.
3. **CasePosterior → rank verification (T4)** — a regression test over
   the already-landed wiring: `settle_round_credit.record_case_settlements`
   moves the linked `CasePosterior` in `runs/posteriors.yaml` and the
   `priority_ratio` rank order follows (`Thompson Beta over N linked`
   instead of cold-start). The test generates the ledger itself — the
   #678 arming gap is workspace state, out of this card's scope.

## Non-goals

- No new REJECT face, no new prefix bypass (acceptance amendment (c)).
- No `priority_ratio` / `rank_feeds` payload change (the feeds already
  carry the linked-case text; this card only makes the state behind it
  non-empty).
- No change to `sample_method_family`'s receipt shape (bit-exact faces
  stay byte-identical; `prior_source` rides the strategy_store wrapper,
  never the kernel receipt).
- No enforcement of sampler-chosen dispatches — the reconciliation is
  telemetry; the #432 vocabulary gate remains the only enforcement face
  of the chokepoint.

## Impact

- `hooks/worker_budget_sinks.py` (`_method_family_gate` + two fail-open
  helpers), `scripts/rlvr/strategy_store.py` (`method_lead` delegation,
  `method_sample`, `proposal_prior_labeled`, `reconcile_declaration`),
  `scripts/method_families.py` (`append_usage_row` keyword-only additive
  fields), `scripts/event_taxonomy.py` (`sample_deviation` registered).
- Blast radius (GitNexus, `--repo kunglao-agent`): `_method_family_gate`
  1 direct caller (the pre_check battery in the same file) with a CRITICAL
  transitive label (211 symbols / 30 dispatch processes at d=3) — the
  signature and fail-open semantics are unchanged, so the direct break
  surface is the battery itself; `sample_method_family` LOW — kernel
  untouched, 3 production callers (strategy_store.method_sample, the
  q_cells `--sample` CLI, the e2e envelope sampler); `append_usage_row`
  1 direct caller (the gate); `_proposal_prior`
  keeps its exact signature and behavior (the labeled face wraps it), so
  its existing callers and tests are untouched.
- Consumers of `method-family-log.jsonl` read `family`/`cell` by key —
  the new explicit-null keys are additive (stable-schema discipline).
