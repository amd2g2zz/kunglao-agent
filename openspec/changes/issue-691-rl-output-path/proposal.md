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

## W2 Amendment (2026-10-19 — §8.2 M3.4, recorded per the owner directive that previously lived only in the code comment)

**Frozen text**: item 1 "recorded, NEVER rejected (fail-open + warn;
vocabulary validation stays the gate's only REJECT face)"; Non-goals "No
new REJECT face … No enforcement of sampler-chosen dispatches — the
reconciliation is telemetry"; spec requirement "A deviation from the
sampler is a recorded decision, never a reject".

**Owner directive (2026-10-18)**, verbatim from the implementing comment:
"#773 W2: the sampler is the EXIT for the UNDECLARED case — silence is not
an override. The gate draws once and REJECTs with the sampled family in
the guidance (deterministic compliance in one retry); declaring another
family remains the recorded-decision override (sample_deviation). This
supersedes the 2026-10-14 'never rejects' amendment FOR THE UNDECLARED
CASE ONLY (owner directive 2026-10-18 + the live forensics: declared=false
on every strategy-log row meant the sampler never exited). Cold sampler ->
the legacy face (the honest gap), never a fabricated family."

**New semantics** (three cases, replacing the single never-reject rule):

1. DECLARED family, any deviation from the draw — unchanged:
   recorded, never rejected (one `sample_deviation` event, fail-open +
   warn; the 2026-10-14 amendment stands for this case).
2. UNDECLARED dispatch + the gate's own draw has material — ONE REJECT
   (`methodfamily`, exit 2) whose guidance carries the sampled family,
   its propensity and its `prior_source`; declaring the sampled family
   makes the sampled exit durable in the usage row. Declaring a DIFFERENT
   family on the retry is the recorded-decision override, not an error.
3. UNDECLARED + cold sampler (no proposal material) — the legacy honest
   gap: no reject, no fabricated family. A missing registry module
   (`scripts/method_families.py` unimportable) is fail-closed REJECT per
   the 2026-09-28 owner ruling ("a gate that cannot see must not wave the
   dispatch through").

**Implementing code**: `hooks/worker_budget_sinks.py:822-895`
(`_method_family_gate`; owner-directive docstring 843-855; registry-gap
reject 854-862; the #773 W2 comment 869-878; the UNDECLARED reject
880-889), `hooks/worker_budget_sinks.py:801` (`_gate_sample`; the
gate's own decision-grade draw) and `hooks/worker_budget_sinks.py:744`
(`_sample_reconciliation`).

**Invariant**: INV-001 (`loop-sampler-exit`) — this amendment IS the W2
wiring the invariant's fingerprint watches: the reject carries the draw,
and the retry's usage row records `sampled_family` + `propensity` so
`runs/strategy-log.jsonl` shows `strategy: "sampled"` rows
(`fingerprint: rl-sampler-exit`).

### Integration contract (W2 amendment)

Caller: the pre_check method-family face of the dispatch gate battery in
`hooks/worker_budget_sinks.py` (the #432 chokepoint, wired pre-activation).
Trigger: every kunglao-shaped dispatch whose declaration is absent while
the sampler view is non-empty. Firing fingerprint: one `methodfamily`
REJECT (exit 2) with the sampled family + propensity + prior_source in the
guidance; the subsequent retry lands a `declared=true` usage row
(`runs/method-family-log.jsonl`) and a `strategy: "sampled"` strategy-log
row. DECLARED deviations keep firing only the `sample_deviation` event
(registered `EMIT_ACTIONS` word), never a reject.
