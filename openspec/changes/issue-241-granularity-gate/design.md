# design — issue-241-granularity-gate

## Verified anchors (2026-09-18, worktree @ 658468d)

| Issue/task says | Actual | Drift |
|---|---|---|
| wbtest C-005 monolithic 12+-step claim is the field instance | issue #241 body verbatim: C-005 "Reverse white-box crypto core — safeEncrypt whitebox VM", live rejection text "no runs/plan-C005*.md ... write the plan FIRST" | none |
| #234 fan-out primitive: `scripts/target_ladder.py mint_sibling_claims` + claim_deps/depends_on split machinery | `mint_sibling_claims(ws, obstacle_claim_id)` at scripts/target_ladder.py:302 — guarded (parent EXISTS, origin=failure-obstacle, ladder walked-valid, inventory non-empty), mints OPEN siblings (origin=obstacle-alternative, obstacle_for, ladder_family, depends_on=[parent], answers_question inherited, `_ensure_dep_edge` write) | none (its obstacle guards are why the size-split gets its OWN mint, not a `--mint` overload) |
| plan-first gate current shape: post-#239 v2, gates the worker execution loop, first-dispatch keyed on approval-point anchor log | `check_worker_plan` at hooks/worker_budget_gates.py — `_anchor_log_ts_list` arming, first dispatch plan-free, re-dispatch requires on-disk plan (empty-shell #294 + author #57 gate 3) or prompt plan-ref (continuity leg) | none |
| dispatch-time claim context: `hooks/worker_budget_sinks.py pre_check` battery | `('plan', check_worker_plan(paths, cid, prompt))` entry; `_reject(name, msg, paths)` emits stderr + REJECT_FIXES additionalContext | none |
| GitNexus impact | `check_worker_plan` upstream: LOW, 3 impacted (d1 pre_check CALLS 0.85, d2 main, d3 tests); `pre_check` (sinks) upstream: LOW, 3 impacted (d1 main, d2 file, d3 tests); `mint_sibling_claims` absent from index (stale — merged #234 post-index) → verified by grep: writers only in target_ladder itself, readers = settlement_blocker consumers (kunglao_record:329, worker_budget_gates:154) | index stale for the #234 symbol; grep fallback |

## Module: scripts/claim_granularity.py (new, ~430 lines)

Cohesion: the granularity plane (measure + split) in one file; the gate
face stays in hooks (dispatch admission is the gates module's job).

### Constants

- `GRANULARITY_MAX_STEPS = 8` — the K (issue calibration "start ~8"),
  named constant, test-pinned.
- `GRANULARITY_MIN_FAMILY_STEPS = 2` — span threshold, verbatim from
  scope: ">= 2 distinct families with >= 2 steps each".
- `GRANULARITY_SPLIT_ORIGIN = "granularity-split"` — a NEW origin value.
  Blast radius checked: origin readers are equality comparisons
  (settlement gate reads origin=="failure-obstacle", sibling reads
  origin=="obstacle-alternative") — an unseen value matches neither, so
  the split sub-claims are invisible to the obstacle machinery by
  construction. No schema file constrains register fields (schemas/ is
  tick/decide outputs only; #234 added fields freely).

### Step-domain inference

Ordered table, first keyword match wins (specificity order: network →
crypto → emulation → memory → dynamic → static). #234 vocabulary where
it fits (emulation, memory-imaging, dynamic-tracing, static-unpacking;
"hooking" folds into dynamic-tracing at plan granularity); network-replay
and crypto-analysis are inference families, labelled "(inferred)" in
guidance. Unclassified steps ride the dominant classified group — vague
text must not manufacture a span violation; an all-unclassified plan is
a size-only shape.

### Steps parsing

`parse_plan_steps`: bare `steps:` collects the marker lines that follow
(`-`, `*`, `+`, `N.`, `N)`, `[ ]`) until a top-level field or `#` header;
inline `steps: do X` counts as ONE step. Every marker line counts —
padded/trivial steps included (adversarial scope point: no free passes).
No `steps:` block at all → [] → gate passes (plan CONTENT is #294's
contract, not this gate's).

### Split mint (rides the #234 machinery)

`mint_split_claims` imports the primitives from target_ladder /
failure_analysis_gate via deferred imports (the established
cross-scripts pattern): `_load_claims`, `_find_claim`,
`_ensure_dep_edge`, `_next_claim_id`. Same construction as the #234
mint, with two deliberate differences:

1. **Guards are size-shaped** (the #234 obstacle guards — origin
   failure-obstacle + walked ladder — would refuse every size-split):
   parent EXISTS, plan EXISTS, plan enumerates steps, plan OUTSIDE the
   threshold (explicit refusal, never a silent partial write).
2. **Chunking**: a domain group larger than K splits into ceil(n/K)
   units (id: C-<next>, `split_chunk` no.) — a domain split alone cannot
   fix a size violation, and each unit must be authored a plan under K.

**Parent supersession + the admission consult (review round 1 CRITICAL).**
The mint marks the parent SUPERSEDED with `superseded_by` = sub ids. The
pool's candidate filter (priority_ratio.priority_ratio:735-744) admits a
claim only when every depends_on parent holds a TERMINAL FACT (facts/
_INDEX.md rows, with the #594 register fallback firing only at ZERO index
rows) — so register supersession alone deadlocks the split in any
workspace holding one settled fact (the production shape): settled subs
cite subs, never the parent, so the block would never lift. Fix chosen
(of the three the reviewer offered): the candidate filter ALSO consults
the register — a parent carrying `superseded_by` satisfies the dep gate
(lineage, not evidence). Chosen over (a) an EvidenceView union: widening
the #594 fallback to all terminal statuses changes admission for EVERY
terminal register status on a CRITICAL-blast-radius symbol (44 impacted,
13 direct callers, 5 processes) — the superseded_by consult is strictly
additive (only admits more, never blocks a previously-admitted claim) and
scoped to replacement; (b) minting a parent facts row: facts are evidence
artifacts produced by verification — machinery-written rows pollute the
evidence channel. Repro pinned as
`test_split_ranks_in_a_settled_workspace_with_facts` (facts index with
one UNRELATED terminal row; SUBS RANK: True).

## Review round 1 fixes (2026-09-19)

- **HIGH — heading-enumerated steps**: `_HEADING_STEP_RE` (markdown
  heading lines carrying an explicit `Step N` number) count INSIDE the
  `steps:` block and, when the block is absent or empty, as a
  whole-document fallback — the "no free passes" headline now holds for
  every natural LLM plan format. Pinned: a 12-step heading plan with no
  label rejects (size+span); heading steps inside a bare label count
  (9-step single-family -> size reject).
- **MEDIUM-a — keyword precision over threshold raise**: single
  overloaded words ("dump", "memory") no longer key memory-imaging;
  compound phrases do ("memory dump", "process memory", "memory image",
  ...). "dump the binary" classifies static via the "binary" keyword.
  Chose keyword precision over raising the span threshold: raising
  GRANULARITY_MIN_FAMILY_STEPS would weaken the C-005 detection this
  card exists for. Residual keyword-collision FP risk accepted and
  documented (the table's broad keywords remain; the precision rule is
  stated in the table comment).
- **MEDIUM-b — superseded-parent reject names successors**:
  check_claim_granularity reads the register row; a parent carrying
  superseded_by gets the "already split — dispatch the SUB-claims"
  rejection (entrypoint/no-op text suppressed), never the generic
  split-loop directive. Register read fail-opens to the generic text.
- **MEDIUM-c — chunk ordering wired**: chunk N+1 depends_on chunk N
  within the same domain group (resolved from existing subs too, so an
  incremental re-mint chains onto the surviving predecessor chunk).
  Semantics: sequential WITHIN a domain (step order preserved),
  parallel ACROSS domains.

### Gate face (hooks/worker_budget_gates.check_claim_granularity)

Arming identical to plan-first: `_anchor_log_ts_list` on the
approval-point log — first dispatch is plan-free (post-#239 contract
preserved; scope point 2 verbatim), the gate fires from the NEXT
dispatch on. Plan discovery via the single-source `plan_file`
(claim_granularity); the prompt-leg regex is factored to
`_prompt_plan_ref` and SHARED with `check_worker_plan` — the continuity
file is read for granularity when it exists. FAIL_OPEN: no cid / no ws /
no plan (single-rejection rule: plan-first owns the no-plan rejection) /
unreadable plan (mirrors the #294 unreadable posture). REJECT message =
`split_guidance(...)`: GRANULARITY GATE prefix, the named defects, the
mint entrypoint, the parent, the observed family→steps split.

Battery position: immediately AFTER `('plan', ...)` — provenance is
checked before granularity (a ghostwritten monolithic plan rejects on
authorship, the more fundamental failure). REJECT_FIXES['granularity']
carries the static protocol (uv run --split invocation, SUPERSEDED
note); the dynamic split detail rides the stderr message (the
established channel, cf. devreason's PRIORITY suffix).

## Risks / trade-offs

- Step-domain inference is keyword-based and crude — deliberate
  (machinery only DEMANDS the split, the LLM performs it; issue
  out-of-scope list). False-negative spans (steps phrased without table
  keywords) degrade to size-only enforcement; false positives are
  bounded by the unclassified-absorption rule, the >= 2-families x
  >= 2-steps threshold, and the compound-phrase precision rule (round 1:
  bare "dump"/"memory" no longer key a family — but steps matching the
  WRONG family are absorbed by nothing; the residual misclassification
  FP is accepted and is the documented bound).
- The gate measures STEP COUNT and DOMAIN SPAN, not step SIZE: an 8-step
  plan of giant steps passes size when single-family. Step-size quality
  is out of the issue's scope (the plan-first/#294 content contract and
  the worker contract own it) — the gate must not over-promise.
- K=8 rejects some legitimately long single-mechanism plans — that is
  the POINT (the C-005 evidence); the split is chunked, not semantic.
- New origin value `granularity-split` — equality-reader audit above
  shows no coupling; a future settlement policy for split claims is a
  record-lane concern, not this card.
- Residual (round 1, LOW, note-only): a plan REWRITE between splits can
  mint a second wave under the same marker namespace while old subs stay
  OPEN (frontier leak; parent already SUPERSEDED, mint reachable only via
  the tool). Last-writer-wins register concurrency is inherited from the
  #234 mint, not new.
