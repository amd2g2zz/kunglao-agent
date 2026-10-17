# issue-740-face4-dispatch-telemetry — the completion row closes the dispatch loop

## Why

RC1: 36 dispatch events with `exit=None` ×35 — the dispatch row records
the start; nothing records the completion. The investigation verdict:
ABSENT, not unjoinable — the completion face already exists (the
round-closure hook emits `lifecycle_completed` at exactly the right
point) and the settle face already computes the wall time and holds the
attempt id. Only the enrichment was missing.

## What Changes

1. `settle_step` returns additive telemetry keys (claim, attempt_id,
   wall_s, outcome, duration_ms, exit) — the ledger whitelists are
   untouched.
2. The round-closure emit carries claim / duration_ms / exit (0 =
   settled, 1 = blocked) + attempt_id/step_id/outcome in the detail.
3. A non-worker stop (no settle receipt) stays SILENT — the designed
   posture: only real dispatch completions emit the completion row.
4. `_kernel_faces` returns the settle receipt (its annotation updates).

## Out of scope (named follow-up card)

- The `action="dispatch"` vocabulary overload (five non-dispatch faces
  share the word — tick-noise/init/module-wired) and the dead
  `external_kicker.py` module emit (NameError → never fires): a
  vocabulary-hygiene card, not Face 4.
- The blocked-outcome producer (worker-status last token) — the exit
  mapping is the contract; the producer lands with the worker-status
  face.
