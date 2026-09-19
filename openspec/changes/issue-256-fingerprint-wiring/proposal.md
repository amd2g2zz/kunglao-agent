# issue-256-fingerprint-wiring — wire the A4 thrash circuit into the real trigger path

## Why

Issue #256: `scripts/zero_output_fingerprint.py` implements the same-type
action thrash circuit (count, persist, emit `zero_output_break`), but the
circuit is built-but-unwired:

- `record_action` has ZERO production callers (GitNexus upstream impact:
  0; only `tests/test_zero_output_fingerprint.py`,
  `tests/test_canary_gates.py`, `tests/test_value_shadow_gates.py` call it).
- `check_zero_output_circuit` (`hooks/worker_budget_gates.py:1441`) also has
  ZERO production callers (only `tests/test_canary_gates.py` invokes it —
  the test-only list).
- The A5 canary graduation this module's own docstring promises ("shadow →
  canary") never landed: the state file is never written in production, so
  the acceptance ("at least one real trigger recorded in production
  telemetry") cannot happen.

## What Changes

1. **Recording wired at the real trigger point**
   (`hooks/worker_budget_sinks.py`): `post_check` — the Agent PostToolUse
   face, i.e. exactly "a worker action completed" — counts every tool the
   completed worker actually invoked against its (tool, claim) fingerprint
   via `record_action`. Discriminator mirrors `_emit_tool_calls`
   (claim-granularity v1): only dispatched workers with a `claim_id` in
   `[active_workers]` record; orchestrator-side Agent calls never touch the
   state.
2. **Gate registered in the production gate list**
   (`hooks/worker_budget_sinks.py`): `check_zero_output_circuit` joins the
   `pre_check` checks battery (the list that decides which gates actually
   run in production) as `zerooutput`, placed next to its sibling stall
   breaker `backtrack`. A tripped circuit REJECTs the dispatch with
   actionable guidance (REJECT_FIXES entry) — the graduation the canary
   test already pins at function level. Fail-open on any read failure,
   matching the gate family's stance.
3. **Visible-recorder contract**: liveness first — a recorder fault never
   breaks `post_check` (fail-open, stderr WARN, same shape as
   `_dispatch_lifecycle`) — but the fault is NOT silently swallowed: a
   crash AND a no-op recorder (a `record_action` that returns without a
   streak payload) both land a visible WARN.
4. **Docstring rot fix** (`scripts/zero_output_fingerprint.py`): the
   module posture note ("does NOT block anything") is updated to the
   graduated posture; recorder code paths unchanged.

## Out of scope

- Any change to fingerprint semantics (hash shape, N=3, belief carriers,
  reset-on-belief-move) — the A4 circuit is owned and tested.
- Heartbeat-survival or mission-stall faces (`scripts/mission_stall.py`).
- In-flight PRs #237/#234 also touch sinks; this branch works against dev
  (`4c800b5`) and reconciles per the orchestrator's sync lane.
