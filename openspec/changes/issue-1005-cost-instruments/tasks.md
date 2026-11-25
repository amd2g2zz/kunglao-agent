## 1. Baseline

- [x] Verify the premise on the local corpus instead of inheriting it: 20
      real sessions with workers — main transcript carries 0 sidechain
      rows; every worker row lives in `<session>/subagents/agent-*.jsonl`
      and carries `isSidechain: true`.
- [x] Census the real eval artifacts: 30 session rows, 25 with an empty
      cost face; 14 of them resolvable to a transcript.
- [x] Record RED: `tests/test_cockpit_worker_tokens_1005.py` 12 failed /
      1 passed, and
      `tests/test_session_cost_transcript_fallback_1005.py` 12 failed /
      1 passed, both at commit 82cb03df before the change (evidence kept
      under the relay's directory, out of the repository).

## 2. Worker transcripts in the ratio fold

- [x] Read the three faces that consume the ratio before touching it:
      `compute_ratio`, `cockpit_ratio`, `process_event`, plus
      `scripts/heartbeat_tick.py` (its only reader) and
      `scripts/experiments/rc1_econ_replay.py` (which carries its own copy
      of the arithmetic and stays as the historical replay).
- [x] Widen `_fold_usage` to the session: fold the main transcript, then
      each worker file's sidechain output rows into the analysis side;
      machine side untouched.
- [x] Expose `worker_transcripts` / `worker_unread` in the face; per-file
      read trouble warns and costs only that file.
- [x] Add the (name, size, mtime_ns) memo at
      `runs/.cockpit-worker-memo.json`; a miss, a corrupt memo and a
      rotated-away entry all recompute.
- [x] Cover with tests (13): the acceptance fold, the machine-side scope,
      inlined sidechain rows, no-worker sessions, malformed lines,
      unreadable worker file, growth, memo/fresh equality, corrupt memo,
      the memo sidecar, the recorded face, the denominator.
- [x] Make it green; ruff on the touched Python.

## 3. The killed session's cost face

- [x] Re-derive the transcript location rule from the CLI itself: resolved
      cwd with '/' and '.' folded to '-' (verified against a symlinked
      /tmp cwd), the session's own rows carry the resolved `cwd`.
- [x] Decide the dollar face by measurement: no cost-state row exists for a
      hard kill; SIGTERM exits 143 without writing one; the CLI's per-model
      dollar face does not join onto the usage rows (per model: input 6.8x,
      cache-read 19x on the same session, different model-name spaces;
      `hasUnknownModelCost=True`) → harvest what exists, never
      price what does not.
- [x] Add `session_transcript` / `transcript_usage` /
      `session_cost_fallback` / `_merge_session_cost` to the runner and
      route `launch_session`'s cost face through the merge.
- [x] Cover with tests (13): the path mapping, the newest-after-launch
      pick, the foreign-cwd reject, the missing dir, orchestrator vs
      worker sums, the last cost-state row, the no-cost-state case,
      malformed lines, the end-to-end kill through the adapter, the
      reason field, stdout precedence, silent stdout falling back, the
      absent transcript keeping the old shape.
- [x] Make it green; ruff; comment-hygiene and formal-code lints clean.

## 4. Evidence on real transcripts (current code)

- [x] Fold all 20 real worker sessions with the changed hook: worker output
      0 → 140 … 11,725,237 tokens, 20/20 non-zero; ratio → 115–2546.
- [x] Write the hook's face for the worst real session (307 worker files)
      into a SYNTHETIC tmp workspace — the real workspace is read-only.
- [x] Harvest the cost face for every empty-cost eval row: 11 sessions
      yield a token account, 1 yields the CLI's own dollars
      ($5.0409120000000005), 0 dollars invented.
- [x] Keep the dumps under the relay's directory, out of the repository.

## 5. Registration

- [x] `deploy_manifest.py --write` then `--verify`.
- [x] `tests/_tiers.py` FAST_MODULES for the pure-unit module (the
      transcript-fallback module spawns sessions and stays integration).
- [x] This OpenSpec change; `openspec validate issue-1005-cost-instruments
      --strict`.
