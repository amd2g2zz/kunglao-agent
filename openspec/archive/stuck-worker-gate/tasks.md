# Tasks — stuck-worker-gate

## 1. RED — write failing tests first
- [x] Create `scripts/test_stuck_gate.py`:
  - `check_backtrack_gate` (monkeypatch `wb._run_py`): clean rc=0 -> (True, ""); stuck rc=1 -> (False, "backtrack" in msg); stale rc=2 -> (False, "escalate"/"redispatch" in msg); failopen None -> (True, ""); failopen no-workspace -> (True, ""); failopen unknown rc -> (True, "").
  - `_check_stale_workers` (temp workspace): stale in-progress mtime 25m -> non-empty, names worker; fresh in-progress mtime 2m -> ""; done + mtime 40m -> ""; no runs/ dir -> "".
- [x] Run `pytest scripts/test_stuck_gate.py` -> confirm tests FAIL (functions do not exist yet).

## 2. GREEN — implement
- [x] `hooks/worker_budget.py`: add `check_backtrack_gate(paths)` after `check_convergence_health` (mirror the `_run_py` + FAIL_OPEN + rc-map pattern at lines 83-112); map rc 1 -> "backtrack" REJECT, rc 2 -> "escalate"/"redispatch" REJECT, rc 0 / None / unknown -> (True, "").
- [x] `hooks/worker_budget.py`: wire `('backtrack', check_backtrack_gate(paths))` as the 11th entry in the `checks` list, immediately after `('health', check_convergence_health(paths))` (line 728).
- [x] `hooks/worker_pulse.py`: add `import time`; add `STATUS_RE` (multi-line `^status:\s*(\S+)`, IGNORECASE) and `STUCK_MIN = 20` constants after `DISPATCH_RE`.
- [x] `hooks/worker_pulse.py`: add `_check_stale_workers(ws) -> str` (glob `runs/worker-status-*.md`, last-status in-progress + mtime > STUCK_MIN -> named message; every OSError/missing-dir -> "").
- [x] `hooks/worker_pulse.py`: on the non-dispatch path (`if not _was_dispatch(payload):`), call `_check_stale_workers(ws)` and emit non-empty result as `additionalContext` JSON (same shape as the dispatch-complete pulse) before `return 0`.
- [x] Run `pytest scripts/test_stuck_gate.py` -> PASS.

## 3. Suite + validate
- [x] `pytest scripts/ -q` — baseline count unchanged, no new failures.
- [x] `pytest tests/ -q` — 222 passed + 6 pre-existing failures unchanged.
- [x] `openspec validate stuck-worker-gate` -> "is valid".
- [x] Commit SDD + RED + GREEN; open PR to dev (closes #38).
