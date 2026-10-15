# tasks — issue-682-liveness-triad

## 1. RED tests (tests/test_liveness_triad_682.py)

- [x] `test_zombie_worker_does_not_pin_cadence_at_floor` (defect a)
- [x] `test_fresh_worker_still_counts_busy` (the cut must not blind)
- [x] `test_tool_touch_does_not_seed_last_tick_ts` (defect b)
- [x] `test_tool_touch_does_not_advance_existing_last_tick_ts`
- [x] `test_check_heartbeat_alive_reads_continuity_verdict` (regression pin)
- [x] `test_liveness_and_workguard_do_not_mutually_block` (defect c repro)
- [x] `test_live_heartbeat_does_not_wall` + no-heartbeat fail-open pin

## 2. Implementation

- [x] (a) `cadence_advisor.active_workers`: `WORKER_FRESH_MIN = 10` mtime
  cut (mirrors workguard `waiting_live`); injectable `now`
- [x] (b) `heartbeat_touch`: delete the `setdefault("last_tick_ts", ...)`
  seeding; docstrings record the stream split (#682b)
- [x] (c) `workguard._liveness_wall`: the gate's own
  `check_heartbeat_alive` verdict becomes a wall in `actionable_set`
  (fail-open on load failure; no wall without the gate's state file)

## 3. Verification

- [x] triad suite green (8 passed)
- [x] neighbor suites green: cadence 635, workguard 434, pulse 618,
  autonomy 754, durable 830, kicker, tick/window/gate/bootstrap,
  liveness-policy 597 (170 passed)
- [x] consumer suites green: framework-rigidity 57, loop-prompt 434,
  loop-watchdog 434, slot-monitor 636, reset-continuity 616,
  verify-truth 609, heartbeat-off (115 passed)
- [x] ruff clean on the touched files
- [x] openspec validate issue-682-liveness-triad exit 0
- [x] comment/formal-code lints + deploy manifest re-emit
