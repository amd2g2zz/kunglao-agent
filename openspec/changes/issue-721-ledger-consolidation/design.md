# design — issue-721-ledger-consolidation

## The 4-file cut

| New file | Contents (pre-#721 stores) | Semantics |
|---|---|---|
| `runs/experience.jsonl` | transitions + q-cell-log + step-ledger + evidence-credit | WHAT HAPPENED — the learning feed |
| `runs/settlement.jsonl` | rollout-ledger + attributed-waste + cost_events | HOW IT CLOSED — the credit |
| `runs/telemetry.jsonl` | interventions + predictions + situation-stream + strategy-log | WHAT WAS OBSERVED — audit |
| `knowledge-store.jsonl` (guarded cross-task root, `strategy_store.store_root()`) | posterior-store + marl-negative + feature-table | WHAT IS KNOWN — cross-task |

12+ physical files → 4. Trust properties preserved unchanged:
append-only, per-row `<name>/N` schema stamps, identity ts, flock
single-writer, 逐句可归因.

## Row contracts (unchanged — now enforced in one place)

- **append-only**: no rewrite/truncate path exists in the core;
- **schema stamps**: `append()` REFUSES a row whose `schema` is not a
  non-empty, whitespace-free string (ONE warn, never a raise). An
  unattributable row inside a multi-schema file is exactly the
  orphan-store bug class #721 exists to kill. New: transition rows carry
  `transition/1` (they carried NO stamp pre-#721; every other family's
  stamps are untouched);
- **flock**: appends take `.<stem>.lock` in the file's dir (the
  rollout-ledger pattern; unlocked O_APPEND fallback where fcntl is
  unavailable — single writes stay atomic, CI single-tenant);
- **read discipline**: a multi-schema file is only ever read through a
  stamp filter (`schema_prefix` — str or tuple of prefixes). Legacy
  (archive-window) rows precede the live file's rows: the archive
  predates it, and append-order IS the fold's decay axis.

## Migration protocol (append-only legal)

Per rel: read the legacy rows → stamp ONLY where safe (a rel with
exactly ONE registered schema may add the missing stamp — the pre-stamp
transitions archive; a two-schema rel's unstamped row copies VERBATIM,
never a guessed stamp, ONE loud warn) → append what the target does not
already carry (canonical-JSON multiset — a re-run appends nothing) →
MOVE the original into `runs/archive/` (bytes intact; moved, not
copied, so the live read face can never double-count).

- originals are NEVER rewritten or deleted (the archive keeps the exact
  bytes; `test_migration_appends_never_rewrites_history` pins it);
- a failed append NEVER archives the rel (status `partial`, re-run
  retries); an existing archive file is never overwritten;
- `dry_run=True` (CLI `--dry-run`) writes nothing;
- a crash between append and move duplicates nothing — the multiset
  dedupe makes the re-run idempotent.

## Compat window

Writers target the consolidated file from the switch commit on; readers
ride `read()` — legacy rel rows first (if still present), then the
consolidated rows. Once `migrate()` has archived a rel its rows arrive
via the consolidated file only. Consumers that used to read a path
directly now ride the read faces (they must, or the migration would
strand them — the #690 dead-store lesson).

## Liveness

`liveness(ws)` returns `{family:schema: count}` over the consolidated
files AND any legacy rels still on disk; every REGISTERED schema reports
a count (0 = dead-but-visible alarm), foreign stamps and unstamped rows
count under their own keys, never hidden. The CLI `--liveness` prints
the same face.

## Blind-act walls

The q-cell arm values are a policy learning face (closed to settler/RT
acts since #687). #721 moves those rows into `runs/experience.jsonl`,
whose transition rows are reward-bearing policy feedback too — so the
WHOLE consolidated file joins the deny lists (rt_read_barrier ACT-side,
settlement_scorer doc-side). Denying more is safe (a blind act builds
from a whitelist); denying less would have unblinded the grader.

## Residuals recorded (not delivered here)

The settlement / telemetry / knowledge families keep their legacy paths
until their own cards switch writers+readers together. Their LEGACY
registry entries (paths + stamps) are already live, so migration and
liveness work unchanged when they switch. See tasks.md §Follow-ups.
