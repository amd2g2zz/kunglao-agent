# issue-740-progress-coupling — the round-close runs on input change (Face 1)

## Why

RC1 (re-labs/ctf-1): ~500 t2_queue_built events vs 36 dispatches in 5
hours — every SubagentStop rebuilt and re-emitted the priority queue
because the queue's `age_min` projection moves with the clock, making
every build content-new. The treadmill burned the token budget the
analysis needed (27/37 claims never dispatched when the budget died).

This PR lands **Face 1** of the #740 mini-plan (the objective function
is recorded in the issue): the round-close runs on INPUT CHANGE.

## What Changes

1. The round-close computes the queue's INPUT signature —
   (claim_id, status, stalled, priority) per entry, deliberately
   excluding the time projections (age_min, reason, ts).
2. Same signature → the persisted queue is still true: persist and
   emit NOTHING (the honest idle).
3. A stall-floor crossing or a register change changes the shape and
   rebuilds (real changes, not clock flow).
4. The drain face keeps its semantics byte-identically (consumption
   loses the signature → the next close legitimately rebuilds once).

## Out of scope (named follow-ups on the same issue)

- Face 2 (act-or-suppress for stale/drift faces), Face 3 (park), Face 4
  (dispatch exit/duration telemetry) — the RC1 audit's remaining faces.
