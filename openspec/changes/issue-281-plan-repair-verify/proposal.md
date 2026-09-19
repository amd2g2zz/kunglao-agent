# issue-281-plan-repair-verify — the plan-drift REJECT repair is unverified

## Why

Field evidence (issue #281, owner ruling 2026-09-19, current-milestone
scope): the plan-drift REJECT instructs a repair ("update global_plan.txt
and/or ...") that nothing verifies — the #249 dead-lock class ("knows the
error but the next step doesn't move") on the plan face. The detector
re-runs every round and already re-reads global_plan.txt; the repair
instruction is PROSE with no verification face, so a plan-drift REJECT can
loop forever on the same un-amended plan.

## What Changes

1. **Episode-scoped repair state (detector face)**: a drift REJECT-class
   detection round opens a repair episode (state file
   `runs/plan-repair-state.json`: fingerprint = `TYPE:claim_id` items +
   classes, rounds=0). The fingerprint is the verification unit — the
   amendment landed when the SAME drift classes no longer fire for the
   SAME claims. STALE_PLAN_ON_NEW_EVIDENCE warns never open an episode
   (observe-first stays observe-only).
2. **Bounded-window verification (every detection round)**: the tick runs
   inside `plan_drift_detector.check()` — operator CLI, `--auto`
   dispatch-gate face and the hooks gate subprocess all advance the same
   episode state (one source). The window counter is cumulative and
   fingerprint-INDEPENDENT: every drift round advances it, so a rotating
   drift shape can never reset the window. At every multiple of
   `PLAN_REPAIR_WINDOW_ROUNDS = 3` the detector escalates
   (plan_repair_overdue event row + stderr line — a cadence, so a
   long-lived stuck episode re-escalates each window). ONLY a genuinely
   clean round closes the episode as verified (plan_repair_verified
   event + stdout line) — drift changing shape is not evidence of repair.
   Escalation is visibility-only — never a new block (the drift REJECT
   itself still gates dispatch).
3. **Registration + cross-face sync**: both event words ship in
   `event_taxonomy.EMIT_ACTIONS` (sorted+unique discipline); the sinks
   drift guidance and the templates/CLAUDE.md.base.tmpl carrier row carry
   the window number as a literal, pinned to the detector constant by
   tests (issue-249 literal-duplication posture).

## What Does NOT Change

- The five (six, post-#241) drift classes, their detection logic, and the
  exit codes (0 / 1 / 2) are untouched — the tick never alters check()'s
  verdict; the opening round and window advance are output-silent.
- STALE_PLAN_ON_NEW_EVIDENCE stays WARN-level observe-first; it can never
  open an episode or fire the window.
- The optional STALLED-class operator-face surfacing (convergence_health)
  is NOT taken — the unified event log + stderr are the operator surface;
  noted as the known out-of-scope tail.

## Impact

- **Code**: scripts/plan_drift_detector.py (the tick + two call sites in
  check()), scripts/event_taxonomy.py (2 EMIT_ACTIONS words),
  hooks/worker_budget_sinks.py (drift guidance sentence),
  templates/CLAUDE.md.base.tmpl (carrier-row clause),
  tests/_tiers.py (fast registration).
- **Tests**: tests/test_plan_repair_verify_281.py (fast, 17 tests, W1-W8
  faces: silent open / window expiry / re-escalation cadence /
  verified-only-on-clean / the adversarial flip-flop probe (alternating
  disjoint drift shapes escalate, zero false verified) / rotation
  supersedes silently / fresh window after close / fail-open / no-churn /
  registration / cross-face sync).
- **Specs**: specs/plan-drift-repair-verification — the bounded-window
  amendment check.
