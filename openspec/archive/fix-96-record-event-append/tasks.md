# fix-96-record-event-append: Tasks

## T1: GREEN implementation [DONE]

- [x] Add `import os, threading` to kunglao_record.py
- [x] Add `_scan_ledger_tail(p, n) -> (line_count, tail_lines)`: single-pass
  file read returning both line count and last N non-empty lines
- [x] Add `_event_id_in_lines(eid, lines) -> (found, seq)`: check event_id
  existence in parsed lines
- [x] Add `_append_single_line(p, text)`: os.open(O_APPEND | O_CREAT) + os.write
- [x] Add `_ledger_lock_for(p) -> Lock`: per-path threading.Lock registry
- [x] Rewrite `record_event`: validate -> compute eid -> acquire lock ->
  scan tail -> idempotency check -> seq from line count -> append -> release lock
- [x] Remove `_atomic_write` usage from `record_event` (keep for `_set_claim_status`)
- [x] Verify 5 concurrent tests pass (10/10 runs stable)

## T2: Verification [DONE]

- [x] `python -m pytest tests/test_record_event_concurrent.py -v` -- 5/5 pass
- [x] `python -m pytest -q` -- 721 passed, 2 failed (pre-existing), 0 regressions
- [x] Pre-existing failures: test_acceptance_overall_passes, test_skill_lte_500_lines

## T3: OpenSpec [DONE]

- [x] proposal.md, design.md, tasks.md, .openspec.yaml
