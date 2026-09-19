# tasks — issue-241-granularity-gate

## 1. RED (TDD)

- [x] 1.1 tests/test_claim_granularity_241.py (fast, registered in
  tests/_tiers.py FAST_MODULES): K = named constant
  GRANULARITY_MAX_STEPS == 8.
- [x] 1.2 fast: wbtest C-005 replay — a 12-step 3-domain plan on ONE
  claim REJECTS with mechanical guidance naming the mint entrypoint
  (`claim_granularity.py --split`), the parent, and the three observed
  families; inference families labelled "(inferred)".
- [x] 1.3 fast: K boundary — 8 steps pass, 9 reject.
- [x] 1.4 fast: defect separation — single-domain 10-step plan carries
  plan-size ONLY (no domain guidance); 4+4 two-family 8-step plan
  carries domain-span ONLY (no size guidance).
- [x] 1.5 fast: adversarial — 6 real + 3 padded ("wait"/"check") marker
  steps = 9 counted -> reject; the message counts the padded steps.
- [x] 1.6 fast: arming — first dispatch NOT gated (monolithic plan on
  disk passes with the not-armed note); re-dispatch with no plan
  fail-opens (plan-first owns the no-plan rejection); no-cid fail-open.
- [x] 1.7 fast: split mint — one sub-claim per domain group with
  depends_on=[parent], real claim_deps.yaml edge, domain_family tag,
  answers_question inherited, each unit <= K steps, families as
  observed; parent split_into + SUPERSEDED (superseded_by = sub ids);
  oversized single-family group chunks; idempotent re-mint; explicit
  refusals (no register / no plan / within threshold).
- [x] 1.8 fast: split-then-redispatch — a sub-claim's under-K
  single-domain plan PASSES the gate; sub-claims are
  priority_ratio.is_open AND rank in the Thompson pool
  (EvidenceView.from_workspace, #594 register fallback).
- [x] 1.9 fast: battery wiring — pre_check exits 2 with
  `REJECT granularity` + `--split` guidance on a provenance-valid
  monolithic re-dispatch; first dispatch with a monolithic plan on disk
  stays rc=0.

## 2. GREEN

- [x] 2.1 scripts/claim_granularity.py (new): GRANULARITY_MAX_STEPS /
  GRANULARITY_MIN_FAMILY_STEPS / GRANULARITY_SPLIT_ORIGIN,
  STEP_DOMAIN_TABLE (#234 vocabulary + labelled inference families),
  parse_plan_steps, infer_step_domains, domain_groups,
  granularity_defects, plan_files/plan_file/read_plan, split_guidance,
  mint_split_claims (chunked, idempotent, guarded, parent superseded),
  CLI --check / --split.
- [x] 2.2 hooks/worker_budget_gates.py: `_prompt_plan_ref` factored;
  `check_worker_plan` consumes the single-source plan_file (no behavior
  change); new `check_claim_granularity` (anchor-log arming, prompt-leg
  continuity read, fail-opens, split-guidance reject).
- [x] 2.3 hooks/worker_budget_sinks.py: battery entry
  `('granularity', ...)` after the plan check; REJECT_FIXES['granularity'].
- [x] 2.4 tests/test_worker_budget.py: #270 reject-guidance census gains
  'granularity' (REJECT_NAMES + REJECT_FIX_KEYWORDS).

## 3. Verify

- [x] 3.1 neighbors green: worker_budget + plan_first_ownership_239 +
  framework_rigidity_57 + obstacle_ladder(+integration) +
  claim_granularity_241 = 198 passed (-n 8); declaration_scan 16 passed
  after cataloguing the new script.
- [x] 3.2 full fast tier green (-n 8).
- [x] 3.3 ruff clean on touched files (line-length 100).
- [x] 3.4 comment_hygiene_lint from root (new units carry no issue refs;
  baseline unchanged).
- [x] 3.5 deploy_manifest --write registers scripts/claim_granularity.py;
  --verify green.
- [x] 3.6 openspec validate.

## 4. Review round 1 fixes (BLOCK → re-submit)

- [x] 4.1 CRITICAL: superseded_by dep-gate consult — the candidate
  filter in scripts/priority_ratio.py treats a depends_on parent holding
  `superseded_by` as satisfied (register lineage consult alongside the
  facts face; additive-only on a CRITICAL-blast-radius symbol). Repro
  pinned: test_split_ranks_in_a_settled_workspace_with_facts (facts
  index with one UNRELATED terminal row → SUBS RANK: True).
- [x] 4.2 HIGH: heading-enumerated steps — `_HEADING_STEP_RE` counts
  `## Step N` lines inside the `steps:` block and as a whole-document
  fallback; pinned: heading plan without label rejects (size+span);
  heading steps inside a bare label count.
- [x] 4.3 MEDIUM-a: memory-imaging keys on compound phrases (bare
  "dump"/"memory" removed); "dump the binary"/"memory-map the binary"
  classify static — cohesive plan passes. Chose keyword precision over
  raising the span threshold (documented in design.md).
- [x] 4.4 MEDIUM-b: superseded-parent reject names the successors
  (superseded_by list), no generic split directive; fail-open to the
  generic text on register read errors.
- [x] 4.5 MEDIUM-c: chunk N+1 depends_on chunk N within a domain group
  (incremental re-mint chains onto the surviving predecessor);
  parallel-across/sequential-within documented; pinned by
  test_cross_chunk_sequential_deps_within_a_domain.
- [x] 4.6 re-verify: 25-test module + neighbors + fast tier + lint +
  ruff + openspec + manifest --verify.
