# issue 1094 — bench_tokens reads the session, not one file

## Why

`scripts/bench_tokens.py`'s `collect()` folds ONE transcript file — the
main session transcript. A Claude Code session that dispatched workers
writes those workers' rows to `<session-id>/subagents/agent-*.jsonl`
beside the main file; the main transcript carries no `isSidechain:true`
row at all (measured across the real corpus by #1005 C1/s1: 0 rows in 20
sessions). So the receipt's `grand_total` — declared at
`bench_tokens.py:10` as "the experiment's cost unit" — silently drops the
worker population of every session that dispatched one.

The drop is not symmetric across the arms K1/K2 compare: the kunglao arm
dispatches workers, the bare-Claude control arm essentially does not.
Under-counting worker tokens makes the kunglao arm look cheaper on
exactly the owner's acceptance axis ("fewer tokens"), so a K1 run on the
current meter would produce a favourable conclusion manufactured by the
gauge. Measured on four real sessions (C1/s2 §2, re-verified on this
branch before the change): the single-file face misses 4.0% / 7.6% /
55.9% / 41.2% of the session's true grand_total.

This is the same root defect #1005 fixed in `hooks/cost_input_capture.py`
(read domain = one file, not one session), in an independent reader on
the same base. Fixing that one did not fix this one.

## What Changes

- `collect()` becomes a SESSION-scope fold: the main transcript plus the
  worker transcripts beside it, enumerated by the ONE shared read-domain
  function. `sidechain_transcripts()` (and its `SUBAGENT_DIRNAME` /
  `SUBAGENT_GLOB` constants) moves from `hooks/cost_input_capture.py` to
  `scripts/_common.py` — the owner-named dedup home — and BOTH readers
  import it from there. No third (fourth) independent implementation of
  "which files make up one session" is created; the hook's existing
  behaviour is byte-equivalent, only the definition moves.
- The four token faces (`total_in`, `total_out`, `cache_creation`,
  `cache_read`), `grand_total`, and `wall_s` are computed over the whole
  session. `wall_s` becomes the min→max timestamp span across ALL of the
  session's transcripts (measured: on 2 of the 4 reference sessions a
  worker's last row is written after the main transcript's last row —
  up to 35 minutes later — so the main-file span was never the session's
  wall clock either).
- `user_turn_count` stays a MAIN-transcript count. The worker transcripts
  carry `type=user` rows that are the dispatch envelope, not a person
  (measured: 2/2/99/509 genuine-looking user rows inside the worker files
  of the four reference sessions); counting them would poison the
  human-intervention signal (`z_self` channel 4) with dispatches.
- `usage_incomplete` becomes a whole-session flag: a worker row without
  a usage face marks the receipt incomplete (partial truth beats no
  truth — same rule the main file already had). An unreadable worker
  transcript counts into a new `worker_unread` face and costs only its
  own contribution; the receipt gains `worker_transcripts` /
  `worker_unread` so "measured the session" is visible on the data.
- The `grand_total` "experiment's cost unit" declaration is KEPT — after
  this change the collector genuinely measures the session, which is what
  the declaration claims. The docstring states the read domain.
- Determinism: the token sums remain in-order integer accumulation over
  a fixed file order (main first, then worker files sorted by name) —
  no `np.sum`/pairwise reduction on this path (the settlement axiom's
  rule; the sums are exact integers, the pin guards against a future
  "optimization").
- `scripts/capability_report.py`'s `_grand_total` docstring is updated:
  it still sums each population separately for its split faces, but its
  justification ("bench_tokens reads ONE file") no longer describes the
  meter. Its no-worker reconciliation pin
  (`test_grand_total_matches_the_bench_meter_without_workers`) keeps
  holding: with no workers the session fold is the main fold.

## Impact

- Receipts from `bench_tokens.collect()` on sessions that dispatched
  workers grow by their worker population (the four reference cases go
  from 4.0%/7.6%/55.9%/41.2% missing to 0% missing — verified on this
  branch before/after). `wall_s` on such sessions can grow when a worker
  outlived the main transcript's last row.
- `user_turn_count` is unchanged in value (main transcript only).
- `hooks/cost_input_capture.py` behaviour is unchanged; the function
  moved to `_common` is re-exported by the same module namespace, so
  `cic.sidechain_transcripts(...)` callers (its own tests) keep working.
- `scripts/eval_loop_runner.py`'s private `_sidechain_transcripts` is a
  pre-existing duplicate of the same read domain (built by #1005 C1/s1
  before the shared home existed); retargeting it is left to a follow-up
  to keep this slice's blast radius at one gauge. Recorded in the relay
  handoff.
- Real transcripts are read-only. Nothing writes to
  `~/.claude/projects/` or `~/re-labs/`.

Closes #1094.
