# Proposal: issue-282-progress-timeline — progress.txt as a complete case timeline

## Why

Issue #282 (owner directive, 2026-09-19): progress.txt must carry a COMPLETE
timeline. Today the machine event timeline lives only in the kunglao_log
ledger (`scripts/kunglao_log.py` emit stream, tick axis = the convergence
ledger's snapshot-row count per #251/#255); workers append narrative entries
to progress.txt with nothing guaranteeing completeness, ordering, or that
machine state-changes (claims minted/settled, gates fired, lifecycle
transitions) appear in any timeline a reader can scan end-to-end.

Owner directive (verbatim anchor):

> "progress.txt must carry a COMPLETE timeline."

## What Changes

Design (a) **derive-and-render** — the machine-complete option:

- NEW `scripts/progress_timeline.py` — the renderer. progress.txt becomes a
  RENDERED timeline generated from the kunglao_log event ledger at
  checkpoints: every ledger event rendered as one `E` row, tick-ordered
  (tick = the #255 epoch axis), with worker narrative entries interleaved as
  `N` rows at their timestamps.
- Narrative preservation WITHOUT a worker-protocol change: workers keep
  appending to progress.txt exactly as instructed today
  (`agents/kunglao-worker.md` step 4, `agents/web-re-worker.md`). The
  renderer ingests any non-rendered lines it finds into the durable
  narrative sidecar `runs/progress-narrative.jsonl` (dedup by exact text),
  then rewrites progress.txt as the rendered form. Pre-#282 legacy content
  migrates the same way on the first render — no narrative line is lost.
- WHEN it renders:
  1. checkpoint cadence — `scripts/convergence_check.py` `main()` renders
     right after `_append_ledger` writes the snapshot (the tick writer), so
     the timeline is in lockstep with the tick axis every round;
  2. at resume — `scripts/kunglao_resume.py` `main()` renders before
     reading (render-then-read): the recovery brief's progress.txt row and
     the human reader always see the freshest complete timeline. Contract
     amendment (#466): resume remains state-read-only EXCEPT the two
     derived-view faces — the progress.txt repair and its
     `runs/progress-narrative.jsonl` narrative mirror (both write-on-diff;
     the ledger and every other file untouched). `build_brief` itself
     stays pure-read.
- Idempotency: render is a pure function of (ledger bytes, sidecar bytes);
  re-render produces byte-identical output; the write is skipped entirely
  when content is unchanged (mtime untouched in the steady state).
- Self-healing by construction: a deleted/truncated/corrupted progress.txt
  is repaired byte-exactly on the next render from ledger + sidecar.
- Fail-open: an unreadable ledger never destroys the human file — the
  render is skipped, the file is left untouched, and the skip reason is
  surfaced as an annotation on the resume brief's progress row.
- The ledger stays the source of truth; progress.txt is the
  human-scannable VIEW. #530 disposition holds: progress.txt is still NOT
  machine-ingested state (`hooks/state_anchor.py` and
  `scripts/external_kicker.py` continue to never read it — verified, no
  code change).

## Capability Intent

A complete, gap-free, human-scannable case timeline derived from the event
ledger with worker narrative interleaved — machine-complete by
construction, self-healing on every checkpoint, and honest about its own
gaps.

## Impact

- `scripts/progress_timeline.py` (NEW) — renderer + ingest + gap check.
- `scripts/convergence_check.py` — `main()` gains one fail-open render call
  after `_append_ledger`.
- `scripts/kunglao_resume.py` — `main()` gains the guarded render-then-read;
  progress data-age row gains the render-state annotation.
- `tests/test_progress_timeline_282.py` (NEW) + `tests/test_kunglao_resume.py`
  read-only pin amended to the #282 contract.
- Docs: `agents/kunglao-worker.md`, `agents/web-re-worker.md`,
  `docs/workspace-manifest.md`, `skills/kunglao-agent/SKILL.md` (one-line
  view-note; #530 qualifiers kept).
- Blast radius (GitNexus, CLI face): `_append_ledger` upstream = 9 impacted
  (d=1: convergence_check.main), LOW; `build_brief` upstream = 4 impacted
  (d=1: kunglao_resume.main), LOW. No production process flows affected.
