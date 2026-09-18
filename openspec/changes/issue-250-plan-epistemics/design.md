# Design — issue-250-plan-epistemics

## Anchors verified (2026-09-18, HEAD 7ec2586)

| Anchor | Found at | Drift |
|---|---|---|
| Plan format goal/preflight/steps/fallback | agents/kunglao-worker.md golden rule #3; machine face = `hooks/worker_budget_gates.check_worker_plan` (+ `_plan_is_empty_shell`, `_BARE_FIELD_RE`) | none — plan_stages.py is the #822 stage model, NOT the plan schema (the dispatch brief's "find the plan schema/validator" assumption resolves to the gate + worker doc) |
| entropy machinery | scripts/posteriors.py:50 entropy_bits, :119 PQCategorical, :148 update_eliminate, :158 update_evidence, :168 entropy | none (matches EXP-3 spike) |
| ΔH term | scripts/priority_ratio.py:96 LAMBDA_DH, ~:713-715 `dh = pq_cat.entropy()`, :727 score | none |
| competence_coverage | scripts/priority_ratio.py:894 | none |
| refutation structural face | scripts/refutation_propagate.py (depends_on reverse walk, needs_re-eval marking) | none |
| fact lint | scripts/lint_facts.py (KNOWN_FRONTMATTER_KEYS :135, VALID_SOURCE :53) | none |
| seed region (#251 boundary) | priority_ratio.py case_face_seed :535 / posterior_rng :549 | untouched |
| claim vocabulary | templates/state/claim-register.yaml (boundary_type comment block) | `epistemic` added as a documented claim boundary_type |

## D1 — per-step if-fails: lint shape and binding condition

The plan file is free-form markdown with labeled sections. Mechanical lint
`lint_plan_contingency(text)` in scripts/plan_epistemics.py:

- the `steps:` SECTION spans from the `steps:` label to the next top-level
  label (`goal:|preflight:|steps:|fallback:` at column 0) or EOF;
- a STEP ENTRY is a non-empty sub-line of that section (bullet `-`/`*` or
  numbered `1.`/`1)`);
- each step entry must be followed (before the next step entry or section
  end) by an `if-fails:` line whose content carries condition + action
  (non-empty after the colon; a bare `if-fails:` is a violation).

BINDING: the gate rejects only when the plan ENUMERATES step entries.
Legacy inline plans (`steps: dump strings`) and bare `steps:` carry zero
enumerated entries and pass unchanged — this keeps the ~15 legacy plan
fixtures in test_worker_budget / test_framework_rigidity_57 /
test_plan_first_ownership_239 green while the issue's RED (enumerated
linear plan now rejected) holds. Arms-race hardening (inline dodge) is the
same incremental path #294 took for the empty shell.

Wiring: `check_worker_plan` re-dispatch leg, after the empty-shell check,
before the #57 plan-author provenance gate. First dispatch stays plan-free
(#239 v2 contract untouched).

## D2 — epistemic claims + situational PQs (represent + price only)

New module scripts/plan_epistemics.py (pure library + thin CLI):

- `detect_target_class(ws) -> "vmp" | "android" | None` — vmp: evidence/
  die.json `derived.detected_packer` in {vmprotect, themida} (the
  difficulty_calibration SEVERE_PACKERS class); android: evidence/apkid.json
  status ok or project_type containing "android" (hypothesis_seeder read
  precedent). Fail-open: no evidence → None → no derivation.
- `derive_must_master(target_class, task_spec) -> list[unknown]` — target
  class templates (vmp: dispatch-mode + pointer-table reachability;
  android: dispatch-mode + register-natives map). Each unknown:
  `{pq_id, question, candidates, promotion_gate}`. pq_id is the
  situational question id — the SAME string that becomes the claim's
  `answers_question` and the ledger key (priority_ratio keys
  `ledger.pqs` by `answers_question` matched against oracle `target_pq`,
  so one string must serve all three roles; EXP-3 finding 2).
- `mint_epistemic_claims(existing, unknowns, next_id) -> new claims` —
  `boundary_type: epistemic`, `status: OPEN`, `answers_question: pq_id`,
  `h_standing_bits` (mint-time entropy), `delta_h_bits: 0.0`. Idempotent
  by pq_id (an answers_question already covered by ANY claim skips).
- `seed_situational_pqs(ws, claims, task_spec)` — for each epistemic
  claim: `PQCategorical(pq_id, candidates)` where candidates come from the
  matching task_spec `model_selection` question when present, else the
  unknown's derived competitor set; uniform weights (#106 seeder
  convention; scaffolds invent no analysis content per #412). Writes
  `ledger.pqs[pq_id]` + atomic save — the FIRST production writer of
  ledger.pqs (EXP-3 gap 1). Mid-run seeding remains #257's settlement
  channel; mint-time is the only write this change makes.
- `apply_and_measure(pq, event) -> {h_before_bits, h_standing_bits,
  delta_h_bits}` — the EXP-3 call-shape helper: snapshot entropy BEFORE
  the in-place update (update_* return None), delta = before − after,
  signed, NEVER clamped (softening legitimately raises entropy — spike
  EXP-3b: −0.185269 bit). Guards the last-candidate eliminate (ValueError)
  by checking nonzero mass first. NOT called by any settlement code —
  #257 wires that; this is the bookkeeping helper with the footgun removed.

Pricing: NO formula change. priority_ratio already prices any claim whose
`answers_question` keys a ledger PQ (`score = (case_face + LAMBDA_DH * dh)
* weight`); once mint+seed exist, epistemic claims price nonzero
automatically. The only ranker diff: the dh feed line names the
situational/epistemic source so the audit trail distinguishes PQ-categorical
from situational ΔH. LAMBDA_DH stays the single free parameter.

## D3 — fact assumptions + semantic invalidation

`assumptions: [<topic>=<polarity>]` on fact frontmatter (e.g.
`dispatch=static`). `known` key in lint_facts (UNKNOWN_KEY would otherwise
fire); shape rule BAD_ASSUMPTIONS (error: not a list of non-empty strings);
ASSUMPTION_UNKEYED (warning: entry without `=` can never be semantically
invalidated).

refutation_propagate gains `find_semantic_undermined(ws)`:

- SOURCES: facts with status PROVEN/VERIFIED (title + body) and register
  claims PROVEN/VERIFIED (title/statement/evidence);
- TARGETS: facts carrying `assumptions`;
- CONTRADICTION RULE (mechanical, minimal-viable — full ATMS out of scope
  per the issue): source content contradicts assumption `T=P` iff it
  contains a topic token of T AND a token of the contradicting polarity
  (CONTRADICTION_TABLE: static↔dynamic; the minimal viable table, same
  spirit as fact_contradiction_gate's topic-key proxy);
- MARKING (no cascade, unchanged semantics): the undermined fact's
  `claim_id` gets `needs_re-eval: true` in the register (the convergence
  loop already re-ranks needs_re-eval claims); the fact ids are reported
  on stdout. Idempotent with the existing skip. Dry-run respected.
  The structural depends_on face is unchanged and runs alongside.

Canonical regression (the issue's xref case): fact F1 "sub_1234 is
uncalled" (assumptions: [dispatch=static], claim C-101) vs PROVEN fact F2
"JNI_OnLoad registers natives via RegisterNatives — dispatch resolves
calls dynamically" (claim C-102) → C-101 flagged needs_re-eval. No
epistemic claim or depends_on edge required.

lint_facts observation-vs-world wording (OBSERVATION_WORLD_BLUR, error):
an observational-source fact (static-decompile/dynamic-trace/frida-capture/
qiling-emu) whose TITLE asserts a world-existential (no callers/uncalled/
no xrefs/not called/never called/no references/does not exist) without a
tool-scope qualifier (xref, decompiler, ghidra, ida, binja, frida, qiling,
debugger, tracer, objdump, radare, static analysis, dynamic trace,
cross-reference, "observation:", per/via+token) — "tool X found no Y" is
legal, "no Y exists" is not.

## D4 — settle-time coverage (annotation, sort-shaped, never blocking)

`settle_coverage(ws, claim_id) -> {claim_id, presuppositions, unresolved,
coverage}` — the settling claim's facts' assumptions each name a
presupposed situational question (`T=P` → T); T is COVERED iff the
epistemic claim whose `answers_question` == T is terminal (any terminal
status — PROVEN/REFUTED/NEGATIVE all answer the unknown; dead-ends count
as addressed). Unresolved = non-terminal (OPEN/INFERRED) → coverage:
"uncovered".

Anti-Goodhart (owner R4-class): the result is an ANNOTATION ONLY —
emitted to the event log (`epistemic_coverage`) and appended to the
completion-gate PASS note in hooks/completion_gate.py (fail-open,
non-blocking). It never changes an exit code, never blocks settlement, and
never blocks promotion — a coverage gate that blocked would be gamed by
cheap mint-and-settle epistemic claims; a sort-shaped signal lets the
orchestrator re-rank instead.

## D5 — boundaries respected

- No settlement code calls `update_eliminate`/`update_evidence` (#257).
- priority_ratio `case_face_seed`/`posterior_rng` untouched (#251).
- No VMP/Android replay infrastructure (#260).
- LAMBDA_DH unchanged; no new pricing parameter.

## Test plan

Fast (pure unit): plan_epistemics library; gate branching; semantic
refutation (xref regression); lint assumptions+wording; pricing feed.
Default tier (subprocess shim): completion-gate coverage annotation wiring.
