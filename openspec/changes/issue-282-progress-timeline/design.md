# Design — issue-282-progress-timeline (design (a): derive-and-render)

## Decision

Design space from the issue:

- (a) derive-and-render: progress.txt becomes a RENDERED timeline generated
  from the kunglao_log event ledger at checkpoints (tick-ordered,
  machine-complete by construction) with worker narrative entries
  interleaved as annotated rows;
- (b) validated-append: worker appends stay primary, a face validates
  ordering/completeness against the ledger and repairs gaps.

CHOSEN: (a). Only (a) makes "zero gaps vs the ledger" true by construction
rather than by enforcement; (b) leaves the file's completeness at the mercy
of append discipline between validations, which is exactly the failure the
issue evidences.

## Architecture

```
runs/logs/kunglao-*.jsonl   (kunglao_log ledger — SOURCE OF TRUTH, machine events)
runs/progress-narrative.jsonl (sidecar — durable narrative store, JSONL)
          │                      │
          └──────┬───────────────┘
                 ▼
     scripts/progress_timeline.render(ws)  → deterministic text
                 │  write-on-diff
                 ▼
          progress.txt  (the complete human-scannable VIEW)
```

### Row grammar (byte-stable, machine-checkable)

```
# progress.txt — rendered case timeline (#282) ...
# events=<n> narrative=<m>
#---
E seq=1 tick=0 ts=2026-09-19T10:00:00Z actor=orchestrator action=converge claim=- :: detail text
N tick=0 ts=2026-09-19 10:04 [W-3 DONE] strings table extracted
```

- `E` rows: one per ledger event, in ledger stream order, carrying the
  event's own epoch as `tick` (`tick=?` when the emit face documented
  `tick_ledger_unreadable` — never fabricated).
- `N` rows: narrative text verbatim (byte-preserving, minus the trailing
  newline), prefixed with the interpolated tick and the entry ts.

### Ordering

Sort key `(sort_ts, kind_rank, stream_index)` — `kind_rank` E=0, N=1;
`stream_index` is the row's position in its input stream. The epoch axis is
monotonic with wall clock (ticks are assigned at emit time), so ts-order
induces tick-order; the gap check additionally asserts E-row ticks are
non-decreasing. Ties at equal ts resolve by stream order — authoritative
append order, fully deterministic.

### Narrative tick interpolation

Workers do not know the tick axis. A narrative entry's tick = the epoch of
the latest ledger event whose ts <= the entry ts (0 when none). Computed at
render time from the ledger itself, so it stays correct as events continue
to arrive.

### Ingest / migration (no worker-protocol change)

At render time, progress.txt is split:

- the rendered block = from the marker header line through the last row;
- every other non-empty line (worker appends since the last render, or ALL
  lines of a pre-#282 legacy file) is a narrative entry.

Entries are appended to `runs/progress-narrative.jsonl`
(`{ts, text, tick, src}` JSONL) unless an identical text line is already
stored (dedup by exact text). Line-level ingest keeps legacy blobs intact
at line granularity; a line without its own `[YYYY-MM-DD HH:MM]` prefix
inherits the ts of the previous line in the same batch. Migration is
therefore automatic on the first render and lossless; the sidecar makes the
narrative durable across re-renders (progress.txt alone is no longer the
only copy — this is what makes delete-a-line repairable for narrative too).

### WHEN it renders

1. Checkpoint cadence — `convergence_check.main()`, immediately after
   `_append_ledger` (the tick writer; `convergence_check.py:1996`). The
   convergence round is the natural hook: it is the only tick-axis writer,
   and the render then happens exactly when the axis advances. Fail-open:
   the render is wrapped like every other telemetry side channel — a
   failure never blocks the decision.
2. At resume — `kunglao_resume.main()` renders BEFORE `build_brief`
   (render-then-read). A crash may have ledger events that arrived after
   the last convergence round, so the resume face guarantees the human
   reads a current timeline.

### #466 contract amendment (documented, load-bearing)

`kunglao_resume` has been READ-ONLY (writes nothing, #466). #282 requires
render-then-read at resume. Amendment, scoped narrowly:

- resume writes ONLY the two derived-view faces: progress.txt (write-on-diff,
  a repair, same spirit as self-healing) and its narrative mirror
  `runs/progress-narrative.jsonl` (only when ingest found new lines);
- the ledger, state files, and every other artifact stay untouched;
- `build_brief` remains pure-read — the repair lives in `main()` only;
- fail-open: any render error leaves the file untouched and the resume
  proceeds on whatever exists;
- `tests/test_kunglao_resume.py::test_resume_is_read_only` is re-pinned:
  "resume writes nothing EXCEPT the two #282 view faces"; the steady state
  (content already current) still preserves mtimes.

### Idempotency + self-healing

`render(ws)` is a pure function of (ledger bytes, sidecar bytes):
- fixed header, deterministic sort, byte-stable row grammar;
- `render_and_repair(ws)` byte-compares before writing, so a no-op render
  does not touch mtime; re-render output is byte-identical for the same
  inputs (pinned test).
- Deleting any line (machine or narrative) is repaired on the next render:
  machine rows from the ledger, narrative rows from the sidecar.

### Fail-open matrix

| condition | behavior |
| --- | --- |
| ledger unreadable (dir at path, OSError) | NO write; existing file untouched; skip reason returned + annotated on the resume progress row; stderr warning |
| no ledger at all | render with zero E rows (cold start is a real empty timeline, header documents it) |
| sidecar unreadable/corrupt rows | tolerant read (skip bad lines), ingest re-migrates from progress.txt narrative |
| render itself raises | caller-side fail-open with an observable stderr WARN (issue-275 policy — never a bare pass) — never blocks decision/brief |
| worker appends never settle during the face | write SKIPPED (file untouched, zero loss); stderr WARN; the next render picks the appends up |
| renderer vs renderer | serialized by the advisory flock (runs/.progress-render.lock); a crashed holder cannot wedge the next render |

### Concurrency (review F1/F5 guards)

The checkpoint face and the resume face race real workers (a straggler
worker's DONE append racing a render) and each other (resume + checkpoint
converging on the same workspace). Two guards, no worker cooperation
needed:

1. **Renderer-vs-renderer**: ingest+render+write run under an advisory
   `flock` on `runs/.progress-render.lock` — flock dies with the process,
   so a crashed holder cannot wedge the next render.
2. **No-append-lost**: the destructive `write_text` fires only when the
   on-disk file is byte-identical to the state just ingested. An append
   landing mid-face folds into a bounded re-check loop (re-ingest delta,
   re-render, re-check); if appends never settle the write is skipped —
   the file stays untouched, so nothing is ever lost, and the next render
   (checkpoint or resume) picks the appends up.

### What does NOT change

- Worker append protocol (kunglao-worker step 4, web-re-worker) — same
  file, same line format; only a doc note that the file is regenerated.
- #530 disposition: progress.txt is still never machine-ingested state;
  `hooks/state_anchor.py` (`build_anchor` NEVER reads progress.txt) and
  `scripts/external_kicker.py` are verified unchanged and keep working.
- `scripts/digest_build.py` mechanical 3-line tail — now shows the newest
  timeline rows (superset of the old narrative tail); no code change.
- kunglao_log ledger schema — untouched; the renderer is a pure consumer
  (the shared `iter_jsonl` tolerance reader, plus explicit unreadable-file
  detection that `tail()`'s silent skip cannot express).

## Test plan

`tests/test_progress_timeline_282.py` (fast tier, registered in
`tests/_tiers.py` FAST_MODULES):

1. PINNED gap-free: N emitted machine events + M narrative entries →
   render → every event present exactly once, E-ticks non-decreasing,
   narrative interleaved between surrounding event timestamps.
2. Idempotency: two renders byte-identical; second repair is a no-op
   (mtime_ns preserved).
3. Self-healing: delete a line → repair restores byte-identical file.
4. Legacy migration: pre-#282 progress.txt content preserved verbatim in N
   rows; sidecar populated; no duplication across renders.
5. Fail-open: unreadable ledger → file untouched + annotation surface.
6. Resume contract: writes only progress.txt when stale; ledger line count
   unchanged; second resume is a full no-op.
7. Source anchors: convergence main renders after `_append_ledger`;
   #530 anchors stay green (no machine-ingestion claims).
