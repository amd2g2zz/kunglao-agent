# issue-682-liveness-triad — the scheduler liveness triad

## Why

Issue #682: three liveness defects make the heartbeat both over-eager and
self-blocking. (a) `cadence_advisor.active_workers` counts any
in-progress `worker-status-*.md` with no freshness cut, so a killed
worker's stale status tail pins the loop at `FLOOR_MIN` (live evidence:
C006/C019; 94% of 156 measured fires fell in [4,6] min).
(b) `hooks/heartbeat_touch.py` seeded `last_tick_ts` from `activity_ts`
via `setdefault`, so tool activity masqueraded as a tick for every
`last_tick_ts` reader — the 35-min monitor face and the external kicker
read a dead cron as alive while a human typed.
(c) The dispatch liveness gate (`worker_budget_sinks.check_heartbeat_alive`)
and WORKGUARD (`workguard.actionable_set`) each demanded the other's
precondition: `dispatch REJECT (liveness) -> turn-exit BLOCK (workguard)
-> retry`, a mutual block with no repair step named on either side.

## What Changes

1. **Freshness cut in the cadence advisor** (`scripts/cadence_advisor.py`):
   `active_workers` excludes status files whose mtime is older than
   `WORKER_FRESH_MIN = 10` — the same rule as workguard's `waiting_live`.
   A fresh in-progress worker still counts as busy; a zombie tail steps
   the advisor toward quiet.
2. **The tick stream is cron-owned** (`hooks/heartbeat_touch.py`): the
   hook writes only `activity_ts`; it never creates or advances
   `last_tick_ts`. `check_heartbeat_alive` already reads
   `evaluate_tick_continuity` (the #754 standard) — now pinned as a
   regression so no last_tick_ts fallback can creep back into the gate.
3. **The liveness wall in WORKGUARD** (`scripts/workguard.py`):
   `actionable_set` calls the dispatch gate's OWN predicate
   (`check_heartbeat_alive`) and, while every dispatch would be rejected,
   reports a `liveness` wall and an empty actionable set — legal sleep
   with the repair chain named in the wall detail. The gate's REJECT is
   NOT downgraded: the #754 mechanical guarantee (no dispatch without a
   live heartbeat) is untouched.

## Non-goals

- Changing the #754 continuity standard itself (`evaluate_tick_continuity`).
- Changing `external_kicker` (its re-arm chain is the recovery path the
  legal sleep hands off to).
- Rendering walls in `turn_exit_guidance` (legal sleep is a silent pass
  by the #434 contract; walls ride the actionable-set result).

## Recovery chain after (c)

Dead heartbeat -> dispatch gate REJECTs (unchanged) -> WORKGUARD wall
makes turn exit legal sleep (new) -> `external_kicker` sees stale
`last_tick_ts` and re-arms a replacement loop (existing) -> continuous
ticks resume -> wall lifts -> DAG re-enters the actionable set.
