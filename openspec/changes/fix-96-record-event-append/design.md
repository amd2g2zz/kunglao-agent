# fix-96-record-event-append: Design

## Architecture

```
record_event(ws, event)
  |
  +-- validate event_type
  +-- compute eid = event_id_of(et, payload)
  +-- acquire per-path threading.Lock
  |     |
  |     +-- _scan_ledger_tail(p, n=100)
  |     |     |  single file read -> (line_count, last_100_lines)
  |     |
  |     +-- _event_id_in_lines(eid, tail)
  |     |     |  if found -> return existing_seq (idempotent)
  |     |
  |     +-- seq = line_count + 1
  |     +-- build record dict + checksum
  |     +-- _append_single_line(p, json_line + "\n")
  |           |  os.open(O_APPEND | O_CREAT) + os.write()
  |
  +-- release lock
  +-- return seq
```

## Key Design Decisions

### Why threading.Lock instead of file lock?

The primary concurrency scenario is multiple threads in the same Python process
calling `record_event` (e.g., concurrent workers spawned by the orchestrator).
A `threading.Lock` is the simplest correct solution for this case. Cross-process
concurrency (separate Python processes writing to the same ledger) is not a
supported use case for `record_event` -- each worker writes to its own workspace.

### Why O_APPEND instead of Python open('a')?

`os.open` with `O_APPEND` + `os.write` bypasses Python's buffered I/O layer and
issues a single `WriteFile` system call on Windows (or `write()` on POSIX). This
is guaranteed atomic by the kernel for writes <= PIPE_BUF. Python's
`open('a').write()` goes through the Python buffer which may issue multiple
system calls for large writes, though for ~200 byte lines this is equivalent.
Using `os.open` makes the atomicity contract explicit.

### Why tail-only scan (100 lines) instead of full read?

In production, a ledger may accumulate thousands of lines over a session.
Reading only the last 100 lines for idempotency is sufficient because duplicate
events are nearly always recent (retry within the same session turn). The full
ledger scan via `read_events()` was the original bottleneck.

### Single-pass scan

`_scan_ledger_tail` reads the file once and returns both the total line count
and the last N non-empty lines. This eliminates the TOCTOU gap between
counting lines and checking the tail that would exist if two separate reads
were used.

## Unchanged Components

- `_atomic_write`: still used by `_set_claim_status`, `claim_migrator`
- `read_events`: unchanged, still parses full ledger for queries
- `event_id_of`: unchanged
- `ledger.jsonl` format: unchanged (one JSON object per line)
- `convergence_check._append_ledger`: separate module, untouched
