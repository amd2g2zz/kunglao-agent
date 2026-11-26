# Design — issue 1094, S29

## D1. The read domain is the shared asset, and it moves to the dedup home

"Which files make up one session" is the piece that forked. It existed in
`hooks/cost_input_capture.py` (`sidechain_transcripts`, #1005 C1/s1), got
re-implemented privately in `scripts/eval_loop_runner.py`
(`_sidechain_transcripts`, same change, before a shared home was
considered), and was absent from `bench_tokens` (the defect this slice
fixes). The instruction "reuse, do not write a third reader" lands on the
read domain: `sidechain_transcripts` and its two constants move verbatim
to `scripts/_common.py` (the owner-named leaf dedup home; the function
uses only `pathlib`, so the leaf contract — stdlib/numpy/PyYAML only,
never a repo import — holds), and both the hook and the bench meter
import it from there.

`_fold_session` itself is NOT re-used as a callable, because its output
face cannot express this gauge's receipt: it returns
`(machine_input, analysis_output)` under the cockpit-ratio ruling
(#1005 design D2: machine side = orchestrator input only) and therefore
never sums `cache_creation`, worker input, or worker cache-read — the
four-face bench receipt is not reconstructible from its return value.
The row-level arithmetic that stays bench-specific is the pre-existing
bench fold (unchanged semantics, now run over each file of the session);
what is shared and single-sourced is the file set and its order, which is
where the fork happened. The hook's tests pin the move byte-equivalently
(all 15 `test_cockpit_worker_tokens_1005.py` cases must stay green with
only the definition's address changed).

A new `session_transcript_files()` face in `_common` — `[main] +
sidechain_transcripts(main)` — fixes the canonical fold ORDER (main
first, workers sorted by name), which is what makes the in-order sum
deterministic (D4).

## D2. What widens and what deliberately does not

| Receipt field | Session scope? | Ruling |
|---|---|---|
| `total_in/out/cache_creation/cache_read` | yes — all four faces over all files | the cost unit must carry the worker population; this is the defect |
| `grand_total` | yes (derived) | its "experiment's cost unit" declaration is kept BECAUSE the collector now measures what it claims |
| `wall_s` | yes — min→max ts across all files | measured on the reference set: 2 of 4 sessions have worker rows up to 35 min AFTER the main file's last row, so the main-file span under-measured the session wall clock |
| `user_turn_count` | **no — main transcript only** | worker files carry `type=user` rows that are the dispatch envelope (measured: 2/2/99/509 on the four reference sessions); counting them would turn dispatches into phantom human interventions on the `z_self` contamination channel |
| `usage_incomplete` | yes — any assistant row without usage, in any file | the "partial truth beats no truth" rule the main file already had, extended to the widened read domain |

The new faces `worker_transcripts` / `worker_unread` mirror the
cockpit-ratio faces of the same names (#1005): how many worker files the
fold saw and how many could not be read, so "measured the session" is
inspectable rather than implied.

## D3. Failure policy at the file boundary

The main transcript keeps its existing short-circuit: unreadable main
file → `error` + `usage_incomplete`, return (the receipt was always
allowed to fail loudly at its primary input). A worker transcript that
cannot be read costs only its own contribution — `worker_unread += 1`,
`usage_incomplete = True`, fold continues (same policy as the cockpit
fold's `worker_unread`). A malformed line inside a readable file is
skipped, never fatal (`iter_jsonl` already yields non-dict rows as
non-dict; the fold's `isinstance` guard handles them).

## D4. Determinism

Token sums are exact-integer in-order accumulation over a fixed file
order (`session_transcript_files`: main first, workers sorted by name) —
no `np.sum`/pairwise reduction, matching the settlement axiom's
input-order rule (`_common.seq_sum` documents the float face of the same
axiom; the token faces are integers, so the pin here guards against a
future "optimization", not a float hazard). Pinned by
`test_session_sum_is_the_input_order_sum_of_its_files` (receipt ==
per-file folds summed in the canonical order) and
`test_session_files_order_main_first_workers_sorted`.

## D5. Consumers checked before the change

- `scripts/capability_report.py` — calls `bt.collect(tx)` for `wall_s`
  (value may grow, by D2's measurement that is a correction, not a
  regression) and for `user_turn_count` (value unchanged by D2). Its
  `cost_faces` still sums each population separately; its `_grand_total`
  docstring justified the split with the OLD meter's limitation and is
  updated. Its no-worker reconciliation pin keeps holding: with no
  workers `session_transcript_files` is `[main]` and the fold is the
  main fold.
- `scripts/eval_loop_runner.py` — does not import `bench_tokens` (its
  own `transcript_usage` is the harvest face). Untouched.
- `tests/test_bench_tokens.py` — the five existing pins all describe
  single-file sessions (no `subagents/` layout), so they hold unchanged.
- `hooks/cost_input_capture.py` — import-only change; `_fold_session`
  calls the shared function under the same name. The import sits inside
  the existing fail-open try block: if `scripts/` is unreachable in a
  partial deploy, the hook degrades exactly as it already does when
  `kunglao_log` is unreachable (the cockpit face fails open via its own
  `except Exception` guard; the tool stream is never blocked).
- `scripts/eval_loop_runner.py`'s private `_sidechain_transcripts`
  duplicate is recorded for a follow-up (out of scope here: one gauge's
  blast radius per slice).
