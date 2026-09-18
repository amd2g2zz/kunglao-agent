# issue-241-granularity-gate — claim granularity discipline: plan-size/domain-span gate splits monolithic claims before dispatch

## Why

Issue #241, wbtest C-005 field evidence (2026-09-12): a 12+-step plan
("Reverse white-box crypto core — safeEncrypt whitebox VM") hung on ONE
claim dispatched to ONE worker. Under the #239 v2 contract the plan-first
gate (`hooks/worker_budget_gates.check_worker_plan`) checks plan
EXISTENCE (+ #294 content, #57 provenance) only — SIZE and DOMAIN SPAN
are unread. Monolithic claims degrade every downstream channel:
spawn-recall quality = f(dispatch-text domain precision) ("parse the
JNINativeMethod arrays from .rela.dyn" keyword-matches the ELF index
cards; "reverse the whitebox crypto core" is a lottery), evidence
verification, per-unit settlement, TS pricing granularity. The split
machinery (claim_deps/depends_on, the #234 fan-out
`scripts/target_ladder.mint_sibling_claims`) already exists but nothing
triggers decomposition for SIZE.

## What Changes

1. **Granularity plane** (new module `scripts/claim_granularity.py`): the
   pure predicate + split fan-out for monolithic claims.
   - `GRANULARITY_MAX_STEPS = 8` (the K, named constant): a plan with
     more enumerated `steps:` marker lines is monolithic. Padded/trivial
     steps ("wait"/"check") count toward K — no free passes.
   - Domain-span: >= 2 distinct mechanism families with
     >= `GRANULARITY_MIN_FAMILY_STEPS` (2) steps each. The family table
     reuses the #234 mechanism-family vocabulary where it fits
     (static-unpacking / dynamic-tracing / memory-imaging / emulation);
     families outside it (network-replay, crypto-analysis) are inference
     families, LABELLED "(inferred)" in guidance — never passed off as
     ladder vocabulary. Unclassified steps never manufacture a second
     domain (they ride the dominant classified group; an all-unclassified
     plan is a size-only shape).
   - `mint_split_claims(ws, claim_id)`: the #234 fan-out at CREATION
     time — one OPEN sub-claim per domain group (a group larger than K is
     chunked into units of <= K steps), origin `granularity-split`,
     `split_for` the parent, real `claim_deps.yaml` depends_on edge,
     `domain_family` tag, `answers_question` inherited, idempotent on the
     (origin, split_for, domain_family, split_chunk) marker. The parent
     is annotated `split_into` and marked SUPERSEDED
     (`superseded_by` = sub ids, the #59 replacement semantics).
   - CLI: `--check C-NN` (verdict, exit 1 when monolithic) and
     `--split C-NN` (the mint).
2. **Dispatch-time gate** (`hooks/worker_budget_gates.
   check_claim_granularity`, new battery entry `('granularity', ...)`
   right after the `plan` check in `worker_budget_sinks.pre_check`): the
   gate fires at the plan-check point of the execution loop — post-#239
   planning is the worker's FIRST act, so on the first dispatch no
   worker-authored plan exists and the gate is NOT armed (approval-point
   anchor-log arming, identical to plan-first). From the NEXT dispatch on
   the worker-authored plan is read; a monolithic plan REJECTS with the
   mechanical split directive (entrypoint + parent + observed domain
   split). Single-rejection rule: with no plan to inspect, granularity
   fail-opens — the plan-first gate owns the no-plan rejection.
3. **Split guidance** (REJECT_FIXES['granularity'] + the dynamic stderr
   message): mechanical — names the mint entrypoint
   (`scripts/claim_granularity.py <ws> --split <C-NN>`), the parent
   claim, and the observed split (which steps belong to which family).
4. **Plan-naming single source**: `plan_files`/`plan_file` (the #239
   glob contract) moves to claim_granularity and
   `check_worker_plan` consumes it (behavior-preserving refactor; the
   prompt-leg regex is factored into `_prompt_plan_ref`).

## Consequences

- Sub-claims enter the TS pool: OPEN + non-terminal + depends_on parents
  all terminal (the SUPERSEDED parent is what admits them past the dep
  gate — without it the split deadlocks).
- The monolithic parent exits the dispatch frontier (SUPERSEDED is
  terminal) — the orchestrator dispatches the SUB-claims; each
  sub-claim's own worker-authored plan must be under threshold and
  single-domain to pass this gate on its re-dispatch.
- TS ranking, decomposition QUALITY (the LLM performs the split;
  machinery only demands it), and semantic recall stay out of scope
  (issue #241 out-of-scope list).

## Verification

- tests/test_claim_granularity_241.py (fast, 19 tests): monolithic
  12-step reject with split guidance; K boundary (8 pass / 9 reject);
  size-only vs span-only defects; padded-steps adversarial; first-dispatch
  not armed; no-plan fail-open; split mint (dep edges, domain tags,
  chunking, idempotency, refusals, parent supersession); sub-claims rank
  in the pool (EvidenceView.from_workspace); battery wiring
  (REJECT granularity rc=2, first dispatch rc=0).
- #270 reject-guidance census updated: REJECT_NAMES +
  REJECT_FIX_KEYWORDS gain `granularity`.
