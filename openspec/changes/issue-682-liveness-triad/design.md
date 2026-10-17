# design — issue-682-liveness-triad

## (a) The freshness cut mirrors the one rule that already existed

`workguard.actionable_set`'s `waiting_live` applies a 10-minute mtime cut
to `waiting` workers (owner ruling 2026-10-10: freshness filters zombie
waiters). The cadence advisor's `active_workers` gets the identical rule
as a named constant `WORKER_FRESH_MIN = 10` — same window, same signal
(status-file mtime), no new primitive. The scan surface is unchanged
(only `ws/runs/`, only the #444 parser); the cut is an extra predicate on
the same row. `now` is injectable for deterministic tests.

Rejected alternative: counting only workers whose claim flipped
IN_PROGRESS in the register. The status file IS the worker-protocol
ground truth (#444); the register flip lags and couples the advisor to
settlement it does not own.

## (b) Activity and ticks are two streams; the hook owns only one

`heartbeat_touch` predates the E2.3 split: the `setdefault` seeded the
missing `last_tick_ts` from `activity_ts` "for legacy readers". The
#754 continuity verdict never reads `last_tick_ts`, but the monitor
(M5.2), the external kicker (`tick_fresh`), and resume do — a seeded
field lets tool activity vote on cron health for up to 35 min after any
reset-shaped state (the `reset_continuity_baseline` rebuild writes no
`last_tick_ts`). The fix deletes the seeding line: the tick stream is
written by the renew/registration tick ONLY; the hook owns `activity_ts`
alone. Its sidecar pulses keep `actor="hook"` and stay skipped by
`evaluate_tick_continuity` (#415 skip list — no change needed there).

`check_heartbeat_alive` already reads `evaluate_tick_continuity`; the
triad pins it with a regression test (fresh `last_tick_ts`, no tick
history -> REJECT) so the authority can never silently drift back to the
tick field.

## (c) The deadlock: share the gate's verdict as a wall, keep the REJECT

Options considered:

1. **Downgrade the liveness REJECT to WARN** — rejected: it deletes the
   #754 mechanical guarantee (dispatch without monitoring was the
   #1 recurring failure across v1.9.12-v1.9.28) to fix a workguard bug.
2. **Workguard re-implements a liveness check** — rejected: a fourth
   hand-rolled standard is exactly the drift #754 fought.
3. **Workguard calls the gate's own predicate** — ADOPTED.
   `_liveness_wall(ws)` loads `hooks/worker_budget_sinks.py` via the
   #863 Family B by-path loader (isolated module name) and calls
   `check_heartbeat_alive(ws / "analysis_state.txt")` — the exact call
   `pre_check` makes. Parity is structural: the gate's skip semantics
   (no state file -> pass), its skill-side fallback, and its continuity
   standard all carry over; workguard can never wall a workspace the
   gate would let through.

While the wall stands, the actionable set is empty (walls gate both
faces) -> `workguard_gate` passes -> turn exit is legal sleep -> the
external kicker's re-arm chain (stale `last_tick_ts` -> replacement
loop) is the recovery. The wall detail names the repair commands.

Fail-open: any loader/read failure -> no wall + one canonical warn; the
guard must never become the deadlock source it exists to prevent. A
workspace with NO heartbeat file (never opted into the gate) keeps the
pre-#682 predicate — no wall appears out of nothing.
