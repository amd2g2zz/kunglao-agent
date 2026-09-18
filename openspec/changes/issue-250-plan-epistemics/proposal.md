# Proposal: issue-250-plan-epistemics — epistemic bookkeeping (plans branch, unknowns mint, facts carry assumptions)

## Why

Issue #250 (owner root correction 2026-09-12): the root is PLAN EPISTEMICS,
not admission-side evidence planning. Four faces, all bookkeeping gaps:

1. Plans are linear happy-path pipelines (`goal/preflight/steps/fallback` —
   one tail escape hatch); no step carries an outcome branch.
2. No epistemic ledger: situational unknowns (VMP: dispatch static or
   dynamic? pointer-table reachability? RegisterNatives map?) are never
   derived from the task, never minted as claims, never priced — the TS
   sampler's LAMBDA_DH term prices ONLY the primary-question categorical
   because nothing ever writes `ledger.pqs` for situational questions
   (EXP-3 spike: ΔH ≡ 0 structurally).
3. Facts are assumption-free atoms: "xref null → uncalled" stores a tool
   observation as a world fact; `refutation_propagate.py` walks ONLY
   `depends_on` structural edges, so the agent's own JNI_OnLoad→
   RegisterNatives finding never retracts the conclusion it falsified.
4. No settle-time coverage check: a claim can close while an epistemic
   claim it presupposes is still open.

Fix = epistemic BOOKKEEPING (owner), not a new algorithm. The VMP/Android
replay closure criterion is CUT to #260 — no replay infrastructure here.

## What Changes

- **Per-step `if-fails` branching (plan schema)**: the worker plan format
  (`runs/plan-<KEY>*.md`, format defined in agents/kunglao-worker.md golden
  rule #3, machine-checked by `check_worker_plan`) gains a per-step
  `if-fails:` branch (condition + action). The plan-first gate rejects a
  re-dispatch plan whose enumerated steps carry no if-fails coverage.
  Inline single-value steps (the legacy shape) are unaffected.
- **Epistemic unknowns as claims**: new `scripts/plan_epistemics.py`
  derives the MUST-MASTER situational list (target-class templates:
  vmp → dispatch-mode + pointer-table reachability; android →
  dispatch-mode + register-natives map), mints claims with
  `boundary_type: epistemic` (`answers_question` = the situational pq_id,
  `h_standing_bits`/`delta_h_bits` recorded at mint), and seeds the
  situational `PQCategorical` into `ledger.pqs` keyed by that pq_id
  (candidates from task_spec `model_selection` where available, else the
  derived competitor set — uniform weights). Signed-gain convention pinned:
  `apply_and_measure` snapshots H BEFORE the in-place `update_*` call
  (they return None), records `h_standing_bits` and `delta_h_bits` as
  separate fields, delta may be negative (softening), NEVER clamped.
- **ΔH-situational pricing**: epistemic claims' ΔH enters the existing
  priority_ratio ΔH term through the seeded ledger (same LAMBDA_DH
  formula — it stays the only parameter); the rank feed names the
  situational source.
- **Fact assumptions + semantic refutation**: fact frontmatter gains
  `assumptions: []` (entries `topic=polarity`, e.g. `dispatch=static`);
  `refutation_propagate.py` gains a SEMANTIC face — a PROVEN fact/claim
  whose content matches an assumption's topic with a contradicting
  polarity flags the assumption-carrying fact's claim `needs_re-eval`
  (canonical regression: the xref/uncalled fact vs the
  JNI_OnLoad→RegisterNatives dynamic-registration fact). `lint_facts`
  enforces observation-vs-world wording (a world-existential title on an
  observational-source fact requires a tool-scope qualifier).
- **Settle-time coverage annotation**: `settle_coverage` verifies that the
  settling claim's fact assumptions resolve to terminal epistemic claims;
  the result is an ANNOTATION (event log + completion-gate pass note) —
  sort-shaped, never blocking (anti-Goodhart: R4-class signals sort only).

## Boundary

- #257 wires SETTLEMENT to `update_eliminate`/`update_evidence`. This
  change only REPRESENTS and PRICEs: PQ construction, ΔH fields, the
  `apply_and_measure` bookkeeping helper. No settlement code calls
  `update_*` after this change.
- #251 owns the priority_ratio seed region (`case_face_seed`/
  `posterior_rng`) — untouched here.
- #260 owns the VMP/Android replay closure — no replay infrastructure.

## Capability Intent

Plan epistemics: the plan models per-step contingency; the unknown list is
derived, minted, priced, and able to undermine the facts that presuppose
it; settlement records whether the epistemic ground was covered.
