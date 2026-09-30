# issue-472-audit-blockers — pre-release exception/logging audit fixes: wave act cage + resolve_claims warn (2 HIGH) + retry-warn / safe-int / exit-registry / pipeline cage (4 MEDIUM)

## Why

The pre-release exception/logging audit (#472; AST sweep of 329 files,
~132k lines) found 0 CRITICAL, 2 HIGH, 8 MEDIUM, 9 LOW. The two HIGH
items violate the non-silent evidence rule at tag-blocker severity:
structured evidence is LOST exactly at the failure moment, and a corrupt
spec is indistinguishable from an absent anchor. Four MEDIUM items ship
in the same train (the remaining MEDIUM 7-10 + LOW items are explicitly
out of scope — #472 stays open per the release-train convention).

Verified defects on dev head (ea383376):

1. HIGH — `scripts/e2e/llm_faces.py:355` (`run_dispatch_parallel`):
   `return [future.result() for future in as_completed(futures)]` has no
   per-future cage. One raising act (e.g. `AutoLlmFace.run_dispatch`'s
   unguarded `Path(req.prompt_file).read_text()` at :168 raising
   FileNotFoundError before ANY result row) re-raises in the main
   thread: the wave's collected records are discarded, the ATTEMPT row
   never gets its RESULT row, the tick dies, no report is written.
2. HIGH — `scripts/e2e/checkpoints.py:141-143` (`_resolve_claims`):
   `except Exception: restore defaults` silently swaps derived
   defaults back in when the spec is unreadable — a corrupt
   task_spec.yaml is indistinguishable from a legitimately
   anchors-absent spec (the #456 bug-3 shape it was built to cure).
3. MEDIUM — `hooks/worker_budget_gates.py:361` (`read_retry_counter`):
   `except Exception: return {}` — a corrupt `.retry-counter.yaml`
   silently resets the pass@k retry cap with zero trace (issue-275
   batch-3 policy: fail-open handlers leave ONE rate-limited warn).
4. MEDIUM — `scripts/kunglao_log.py:538-542` + `scripts/e2e/audit.py`
   (twin event dict): `int(duration_ms)` / `int(exit)` / `int(epoch)`
   raise ValueError on non-numeric caller input — emit's documented
   "Never raises" contract only holds for well-typed callers.
5. MEDIUM — `scripts/hook_exit_codes.py`: `HOOK_EXIT_SEMANTICS` has NO
   row for completion_gate (vocabulary 0/1/2/3/4/5/6/7 — codes 4-7 do
   not even exist as `ExitCode` members; `hooks/completion_gate.py`
   hardcodes `EXIT_NOTES_DUE=5/6/7`), and `ExitCode.GENERAL_ERROR`'s
   own comment ("hook crashed, malformed input") contradicts the
   deliberate exit-1 block faces that workguard_gate and
   completion_gate document.
6. MEDIUM — `scripts/e2e/checkpoints.py:935` (`run_pipeline` step
   loop): `result = fn()` is uncaged — a raising checkpoint aborts the
   pipeline with NO report written (finalize() never runs), the worst
   possible failure shape for a harness whose product IS the report.

## What Changes

1. Wave act cage: per-future try/except in the collection (plus the
   same cage on the inline wave-of-one path); a caged act synthesizes
   `ActRecord(claim, mode, "ERROR", {...})` and completes the
   ATTEMPT/RESULT pair with an honest rc-null reason; the
   prompt-file read in `AutoLlmFace.run_dispatch` gets its own guard
   (known failure cause → ERROR record, no raise).
2. `_resolve_claims` warns via `kunglao_log.warn` on spec-unreadable;
   anchors-absent stays silent-legitimate.
3. `read_retry_counter` warns on parse failure (rate-limited by
   kunglao_log.warn's per-(op, reason) dedupe); fail-open `{}` posture
   unchanged.
4. `_safe_int` (coerce-or-None) defined in `kunglao_log`, applied at
   both emit sites (kunglao_log.emit + e2e.audit.emit) for
   duration_ms/exit/epoch; each coerced null is explained in
   null_reasons (honesty rule: a null measurement is documented, never
   silent).
5. Exit-code registry: add `ExitCode.INTENT_UNMATCHED=4 / NOTES_DUE=5 /
   NOTES_FAKE=6 / SUMMARY_FAKE=7`; register the full completion_gate
   vocabulary; document workguard's exit-1 block face as the deliberate
   block it is; resolve the exit-1 dual meaning per the registry's own
   docstring (semantics are per-hook and log-only — Claude Code reads 0
   vs non-zero); the completion_gate shim's EXIT_* constants derive
   from the registry (with the fail-open literal fallback) so the file
   is the single source of truth it claims to be. NO emitted exit code
   changes.
6. run_pipeline step cage: `fn()` wrapped; a raising step records a
   FAIL CheckpointResult (error + failed_step in detail) via the
   existing `_record` seam, so evidence lands and `finalize()` still
   writes the report.

## Non-goals

- Audit MEDIUM 7-10 and LOW items (separate cards; #472 stays open).
- Any change to emitted exit codes, hook JSON contracts, or the retry
  counter's fail-open semantics.
- Any retry/re-launch semantics for caged acts (cage = record + move
  on; the pass@k discipline is untouched).
- Workguard/completion_gate behavioral changes beyond constant wiring.
