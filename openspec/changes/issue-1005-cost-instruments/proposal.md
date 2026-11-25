# issue 1005 — C1 instruments (s1: worker tokens + killed-session cost)

## Why

Two cost gauges do not measure what they claim to measure, and their output
is the denominator of the K1/K2 controlled comparison.

1. `hooks/cost_input_capture.py` reports `analysis_output_tokens` as 0 for
   every session. Its own stated scope (the `_fold_usage` docstring) is:
   analysis side = the output tokens of `isSidechain` rows. But a Claude
   Code main transcript carries **no** `isSidechain:true` row at all
   (measured: 0 rows in each of 20 real sessions on this machine) — the
   worker rows live in separate files beside it, at
   `<session>/subagents/agent-*.jsonl`. So the ratio degenerates to
   `machine_input / 1` and the "ratio > 1" alarm face cannot say anything
   about harness overhead competing with analysis.
2. `scripts/eval_loop_runner.py` reads its cost face from the session's own
   stdout result line. A wall-cap kill (SIGKILL to the process group)
   leaves stdout empty, so the cost face is empty: 25 of the 30 session
   rows in the real eval artifacts carry no cost. Consumers treat the empty
   face as zero spend (`gap_redo_decision`: "a missing report reads as zero
   spent") or drop it from the sample (`eval_matrix_report` appends a cost
   only when it is not None) — so exactly the sessions that burned the most
   wall clock vanish from the cost account while their failures stay in the
   denominator.

## What Changes

- `_fold_usage`'s read domain becomes "one session" instead of "one file":
   the main transcript plus `<session>/subagents/agent-*.jsonl`. The
   stated scope is unchanged in every word — the machine side still counts
   only the orchestrator rows' input tokens including cache reads, the
   analysis side still counts only sidechain rows' output tokens. What
   changed is which file those rows are in.
- Each PostToolUse call re-folds the worker transcripts, which is too
  expensive to be true (the largest real workspace holds 1.5 GB across 307
  files: 12.3 s measured). A memo keyed by (file name, size, mtime_ns)
  lands at `ws/runs/.cockpit-worker-memo.json`, so only files that grew are
  re-read. It is a pure memo: a hit and a miss must produce the same
  numbers, and a corrupt or missing memo recomputes.
- The face gains `worker_transcripts` and `worker_unread`: how many worker
  files were folded and how many could not be read, instead of an unreadable
  file silently contributing zero.
- `eval_loop_runner` gains a transcript fallback: when the session never
  reported itself, read the CLI's OWN cumulative `cost-state.totalCostUSD`
  off its transcript, and always book the token sums from the usage rows
  (orchestrator and worker populations kept apart). When no dollar row
  exists, the face names the reason (`cost_unavailable_reason`) instead of
  leaving zero to be inferred, and `cost_source`
  (`cli-result` / `transcript-cost-state` / `transcript-usage-tokens`)
  makes a mixed-scale cost account visible on its own face.
- NOT done: pricing dollars from token counts. The CLI's own
  `modelUsage` dollar face is not the same population as the transcript's
  usage rows — the model-name spaces differ (a tier suffix on one side, and
  models that appear in no usage row at all) and they diverge per model
  (measured on one session: input 6.8x, cache-read 19x; the mixed grand totals
  are 2.8x), while the CLI's own row says `hasUnknownModelCost=True`. A rate
  table calibrated on it would put
  killed sessions on a different money scale from the completed sessions
  they are compared against: a distorted denominator, which is worse than a
  missing one.

## Impact

- Gauge faces affected: `runs/.cockpit-ratio.json`'s `analysis_output_tokens`
  and `ratio` (on real sessions: 0 and ~1e9 become non-zero and 115–2546;
  the alarm bit still arms on the same >1 rule), and
  `loop.session.session_cost` in the eval results document (new keys; no
  existing key changes meaning).
- No decision, dispatch, settlement or wake behaviour changes.
- `scripts/heartbeat_tick.py` is the only current reader of
  `.cockpit-ratio.json`; it reads the same keys — its own use of the new
  numbers is s2's scope.
- Real transcripts are read-only. Nothing here writes
  `~/.claude/projects/` or `~/re-labs/`.

Refs #1005 (not Closes).
