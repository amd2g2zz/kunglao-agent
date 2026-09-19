# Tasks — issue-282-progress-timeline

## 1. Renderer module

- [x] 1.1 `scripts/progress_timeline.py`: constants (`PROGRESS_NAME`,
      `SIDECAR` path, `RENDER_MARKER`), `read_events` (via kunglao_log.tail),
      `read_narrative` (tolerant JSONL)
- [x] 1.2 `ingest_progress_appends`: rendered-block split + line-level
      narrative ingest into the sidecar (dedup by exact text, ts-prefix
      parse with previous-line inheritance)
- [x] 1.3 `render`: deterministic header + E/N rows, `(ts, kind, idx)`
      ordering, narrative tick interpolation, gap-check trailer
- [x] 1.4 `render_and_repair`: ingest → render → write-on-diff; fail-open
      status object (`{status, wrote, reason}`)
- [x] 1.5 `timeline_gaps`: per-event presence + tick-order verification face

## 2. Hook wiring

- [x] 2.1 `scripts/convergence_check.py` `main()`: fail-open
      `render_and_repair` right after `_append_ledger` (documented as the
      checkpoint cadence — the tick writer)
- [x] 2.2 `scripts/kunglao_resume.py` `main()`: render-then-read before
      `build_brief`; progress data-age row gains the render annotation
      (`progress_row_annotation`); #466 amendment documented in the module
      docstring

## 3. Tests

- [x] 3.1 `tests/test_progress_timeline_282.py`: pinned gap-free, ordering,
      idempotency (byte-identical + mtime no-op), self-healing, legacy
      migration, fail-open, resume contract, tick interpolation,
      multi-day merge, #530-anchor coexistence
- [x] 3.2 `tests/test_kunglao_resume.py`: `test_resume_is_read_only`
      re-pinned to the #282 amendment (only progress.txt may change;
      steady-state second resume = full no-op)
- [x] 3.3 `tests/_tiers.py`: register `test_progress_timeline_282` in
      FAST_MODULES

## 4. Docs (migration notes)

- [x] 4.1 `agents/kunglao-worker.md` step 4 + golden-rule note: file is
      regenerated from the ledger; appended lines are preserved (sidecar
      mirror), append protocol unchanged
- [x] 4.2 `agents/web-re-worker.md`: same one-line note
- [x] 4.3 `docs/workspace-manifest.md`: progress.txt = rendered timeline
      VIEW (#282), still not scaffold/machine state (#530)
- [x] 4.4 `skills/kunglao-agent/SKILL.md` external-memory line: keep the
      human/narrative qualifiers, add the rendered-view note

## 5. Verification

- [x] 5.1 `pytest tests/test_progress_timeline_282.py -n 8` green
- [x] 5.2 resume + state_anchor + kunglao_log + digest suites green
- [x] 5.3 full fast tier green
- [x] 5.4 `ruff check` on touched files (line-length 100)
- [x] 5.5 `deploy_manifest.py --write` + `--verify` clean
- [x] 5.6 `openspec validate issue-282-progress-timeline`
- [x] 5.7 comment_hygiene_lint from root
