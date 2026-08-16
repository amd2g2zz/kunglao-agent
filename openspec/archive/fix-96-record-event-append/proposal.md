# fix-96-record-event-append: Proposal

## Problem

Issue #96, Finding F8: `record_event` in `scripts/kunglao_record.py` uses a full
read-modify-write cycle (read all ledger lines, check idempotency, rebuild full
file, `_atomic_write` via temp-file rename). Under concurrent access (multiple
worker threads calling `record_event` on the same ledger), the second writer's
read sees pre-first-writer state and its `_atomic_write` overwrites the first
writer's event -- data loss.

The `_atomic_write` temp-file rename pattern is also inherently racy under
concurrency on Windows: two threads create the same `.tmp` file simultaneously,
causing `PermissionError`.

## Proposed Fix

Replace the read-modify-write cycle in `record_event` with:

1. **Append-only write**: Use `os.open(path, O_WRONLY | O_CREAT | O_APPEND)` +
   `os.write()` for the ledger line write. O_APPEND makes the kernel seek to
   EOF atomically for writes within PIPE_BUF size (~200 bytes per line, well
   within the 4KB+ OS buffer).

2. **Tail-only idempotency scan**: Instead of `read_events(ws)` (parses entire
   ledger), read only the last 100 non-empty lines from the file for the
   `event_id` existence check. Single-pass read returns both line count and
   tail in one file read (no TOCTOU gap).

3. **Seq from line count**: `seq = line_count + 1` where line_count is from
   the same single-pass scan, not from `len(existing)` after a full parse.

4. **Per-path threading.Lock**: Serializes the read-check-append sequence
   within a single process (the primary concurrency scenario for same-process
   worker threads). Cross-process safety is provided by O_APPEND atomicity.

5. **Preserve `_atomic_write`**: Keep it for `_set_claim_status` and other
   operations that genuinely need full-file rewrite. Only remove its usage
   from `record_event`.

## Constraints

- No change to ledger.jsonl line format (one JSON object per line).
- No change to `event_id_of`, `read_events`, or public API signatures.
- Idempotency preserved: same `event_id` recorded twice returns same `seq`,
  one entry in ledger.
- No external file locks (fcntl/msync); threading.Lock for in-process only.
- Must not break `_set_claim_status` or `claim_migrator`.
- Must not break `convergence_check._append_ledger` (separate file, untouched).

## References

- Issue #96, F8 (absorption-research-round2.md)
- `convergence_check._append_ledger` pattern (single `open('a')` append per call)
- `tests/test_record_event_concurrent.py` (RED phase, 5 tests)
