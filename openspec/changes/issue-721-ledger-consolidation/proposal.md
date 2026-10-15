# issue-721-ledger-consolidation — consolidate the ~12 JSONL ledgers into 4 files by lifecycle

## Why

Experience is fragmented across 12+ JSONL stores. "The experience" (one
logical entity: what happened) lives in three physical files at three
grains (transitions / q-cell-log / step-ledger). The fragmentation
already bit once: transitions.jsonl was written by e2e but not by the
plugin path until #690 — a dead store nobody noticed.

Owner ruling (2026-10-16): the ledgers are too fragmented; consolidate
into a few files. The prior "determinism wall" objection was weighed and
is WRONG: the wall lives in ROW-level contracts (append-only +
`<name>/N` schema stamps + identity ts + flock), not in file
separation — `runs/step-ledger.jsonl` already hosts step-record/1 AND
step-record/2 in one file (the precedent).

## What Changes

1. **The consolidation core** (`scripts/rlvr/consolidated_ledger.py`) —
   the 4-family registry (experience / settlement / telemetry under
   `runs/`; knowledge under the guarded cross-task root), `append()`
   (flock, append-only, refuses a stampless row), `read()` (legacy
   archive rows first, then the consolidated file; stamp filter),
   `liveness()` (per-schema counts — a dead schema reads 0, visible),
   `migrate()` (per rel: append rows, then move the original into
   `runs/archive/` — bytes intact, idempotent).
2. **The experience family switches whole in this change**: the
   transition ledger (`incremental_reward`), the q-cell observation log
   (`q_cells`), the step-record + evidence-credit ledgers
   (`step_ledger`) all write `runs/experience.jsonl`; their readers
   accept both paths during the compat window (legacy archive first,
   then the file; stamp-filtered). New transition rows gain the
   `transition/1` stamp (they carried none pre-#721 — a multi-schema
   file makes the stamp mandatory); all other stamps are unchanged.
3. **The direct-path consumers** switch to the read faces: rollup,
   eval_loop_runner, eval_matrix_report, e2e runtime's wipe guard, and
   censored_review (which scans other workspaces and now matches both
   filenames, skipping `runs/archive/`).
4. **The blind-act walls extend**: `hooks/rt_read_barrier.py` and
   `scripts/rlvr/settlement_scorer.py` deny `runs/experience.jsonl` —
   the q-cell arm values ride it now, so the whole consolidated learning
   feed is closed to settler/RT acts (the move must not unblind an act).
5. **The migration CLI** (`scripts/consolidate_ledgers.py`) — the
   one-time append-and-archive migration plus the per-schema liveness
   readout.
6. **Follow-up cards** (recorded, NOT delivered here; see tasks.md):
   settlement family (rollout-ledger / attributed-waste / cost_events),
   telemetry family (interventions / predictions / situation-stream /
   strategy-log), knowledge family (cross-task posterior-store /
   marl-negative / feature-table).

## Non-goals

- Switching the settlement / telemetry / knowledge families' writers and
  readers (each is its own card — a family switches whole or not at all).
- Deleting or rewriting any legacy file: the migration moves originals
  into `runs/archive/` byte-identical; nothing is ever deleted.
- Changing any row's schema stamp version, field set, or the append-only
  semantics; the per-workspace `runs/posterior-store.jsonl` (#428 bank)
  is out of the 4-file cut.
- Tightening `fold()` numerics: the q-cell fold reads the same rows
  through the same stamp filter and folds identically.
