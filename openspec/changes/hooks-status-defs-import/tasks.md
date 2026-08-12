# hooks-status-defs-import — Tasks

## Phase 1: RED — Extend guard to scan hooks/

- [x] 1.1 Add `HOOK_CONSUMERS` list to `test_status_defs.py` with `worker_budget.py` and `state_anchor.py`
- [x] 1.2 Refactor `test_consumer_has_no_own_status_set` to resolve paths from both `scripts/` and `hooks/`
- [x] 1.3 Refactor `test_consumer_imports_shared_module` similarly
- [x] 1.4 Run pytest — confirm RED: `worker_budget.py` fails (has `TERMINAL_STATUS = {` and no `from status_defs import`)
- [x] 1.5 Confirm `state_anchor.py` fails (has `_PARTIAL_STATUSES = {` and no `from status_defs import`)

## Phase 2: GREEN — Fix hooks/ imports

- [x] 2.1 `hooks/worker_budget.py`: add `from status_defs import TERMINAL` in the existing sys.path block
- [x] 2.2 `hooks/worker_budget.py`: remove local `TERMINAL_STATUS = {...}` 5-value set (line 26)
- [x] 2.3 `hooks/worker_budget.py`: replace `TERMINAL_STATUS` with `TERMINAL` in `check_tier_gate` (line 622)
- [x] 2.4 `hooks/state_anchor.py`: add `from status_defs import PARTIAL_STATUSES` at module level
- [x] 2.5 `hooks/state_anchor.py`: remove local `_PARTIAL_STATUSES = {...}` (line 63)
- [x] 2.6 `hooks/state_anchor.py`: replace `_PARTIAL_STATUSES` with `PARTIAL_STATUSES` (lines 164, 171)
- [x] 2.7 Run pytest — confirm all RED tests now GREEN

## Phase 3: VERIFY

- [x] 3.1 Run full pytest suite — no regression (pre-existing 2 failures exempt)
- [x] 3.2 Verify status_defs.py unchanged (8-value TERMINAL set)
