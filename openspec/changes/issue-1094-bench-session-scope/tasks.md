## 1. Baseline (recorded under the relay's out-of-repo directory)

- [x] Re-verify the four C1/s2 reference sessions on THIS branch before
      touching code, through the PRODUCT path (`bench_tokens.collect` on
      the main transcript): 14,900,406 / 203,904 / 1,837,410,746 /
      7,183,866,178 — and independently with a one-shot fold: session
      totals 15,519,178 / 220,672 / 4,168,350,569 / 12,220,662,382,
      missed 4.0% / 7.6% / 55.9% / 41.2%, bit-identical to C1/s2's table.
- [x] Measure the worker-file row shapes that decide scope: genuine-user
      rows inside worker files (2/2/99/509 — dispatch envelopes, not
      humans), assistant rows without usage (0/0/0/0), worker last-row
      timestamps beyond the main file's last row (2 of 4 sessions, up to
      35 min).

## 2. RED first

- [x] Write the session-scope pins into `tests/test_bench_tokens.py`
      (worker transcripts count; no-worker equality; user turns
      main-only; worker row without usage flags incomplete; unreadable
      worker counts unread and keeps partial truth; input-order sum;
      file order main-first-workers-sorted). Run them on the unchanged
      tree and record the RED counts.

## 3. The shared read domain

- [x] Move `SUBAGENT_DIRNAME` / `SUBAGENT_GLOB` / `sidechain_transcripts`
      verbatim from `hooks/cost_input_capture.py` to `scripts/_common.py`;
      add `session_transcript_files()` (main first, workers sorted).
- [x] Retarget the hook's import (inside its existing fail-open try
      block); all 15 `test_cockpit_worker_tokens_1005.py` cases green.
- [x] `eval_loop_runner`'s private duplicate recorded as follow-up, not
      retargeted here.

## 4. The session-scope receipt

- [x] `bench_tokens.collect()` folds every file of
      `session_transcript_files()`; four token faces + `wall_s` (session
      min→max ts) widen; `user_turn_count` stays main-only;
      `usage_incomplete` is whole-session; new faces
      `worker_transcripts` / `worker_unread`; main-file read failure
      keeps its short-circuit.
- [x] Docstring: the read domain is stated; the cost-unit declaration is
      kept because the collector now measures the session.
- [x] `capability_report._grand_total` docstring updated (its
      one-file-meter justification is gone); its pins still green.

## 5. GREEN + gates

- [x] New pins green; the five original `test_bench_tokens.py` pins
      green; `test_capability_report_1005.py` green.
- [x] `test_delegation_863i.py` (manifest face) green — run by the
      closeout segment on the shared pytest lock after the S18 full
      suite released it: the related family (delegation_863i,
      syspath_hygiene_671, cockpit_persist_873, economics_801 — which
      carries the ratio/alarm faces — pricing_760) 124 passed.
- [x] `ruff check` on the touched Python; comment-hygiene and
      formal-code lints clean against their baselines;
      `deploy_manifest.py --write` then `--verify` LAST.
- [x] Four reference sessions re-run through the product path after the
      change: session totals bit-identical to the independent fold,
      missed share 0.0% on all four; before/after table recorded.

## 6. Registration

- [x] `scripts/_common.py` is an existing registered module (no new
      entry-point); confirm ext-scan / README / manifest need no new row
      (bench_tokens row already exists; manifest refreshed by the
      --write above).
