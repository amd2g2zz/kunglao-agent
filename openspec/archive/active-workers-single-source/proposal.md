## Why

`hooks/worker_budget.py::check_workers_lt_3` and `scripts/convergence_check.py::_scan_active_workers` each read a DIFFERENT active-worker count source — a double-truth-source defect (architectural leftover: v1.9.13 moved the semantic to status files but the gate never followed).

- The **gate** reads the `[active_workers]` segment of `analysis_state.txt`. That segment is maintained by `register_worker` / `remove_worker`, but is only cleaned up (claim_id / tier / dispatched_at zeroed) by the **LLM-driven cron tick** (reconcile). When reconcile misses a tick, fails, or leaves stale residue, the gate reads the wrong count.
- **convergence_check** reads `runs/worker-status-*.md` + `.wt-*/` worktree status files (last-status == `in-progress`) — a mechanical, file-driven source of truth.

Consequences (issue #37):
- State segment reconciled to empty → gate sees 0 → dispatches a 4th worker while 3 are genuinely running (over-concurrency).
- State segment with stale residue → gate sees "full" → blocks dispatch even when 0 workers are genuinely running (deadlock).

Both failure modes are direct symptoms of "gate and convergence_check not sharing one source."

## What Changes

- **`hooks/lib_kunglao.py`** (new function): `scan_active_workers(workspace) -> (active, stuck)` — a byte-for-byte mirror of `convergence_check._scan_active_workers` (incl. `.wt-*/` worktree scan + last-status=in-progress rule + STUCK_MINUTES=20). Shared host for hooks/scripts, removing the double implementation.
- **`hooks/worker_budget.py::check_workers_lt_3`** (read source): signature `(state_path: Path)` → `(paths: dict)`; source switched from `read_active_workers(state_path)` to `lib_kunglao.scan_active_workers(paths['workspace'])`. FAIL_OPEN preserved (workspace missing / scan exception → allow).
- **`pre_check` call site**: `check_workers_lt_3(paths['state'])` → `check_workers_lt_3(paths)`.
- **state segment demoted to cache/display only**: `register_worker` / `remove_worker` keep writing it (post_check still uses remove_worker), but the gate no longer reads it.
- **`scripts/test_worker_budget.py`**: migrate the 2 old `check_workers_lt_3` tests to the dict signature + add 3 new status-scan tests.

## Capabilities

### Modified Capabilities

- `worker-budget`: the concurrency gate's count source moves from the `analysis_state.txt [active_workers]` cache to status-file scanning (aligned with convergence_check's single source of truth). The state segment stays as cache/display; the gate does not read it.

## Impact

- `hooks/lib_kunglao.py`: +1 function `scan_active_workers` (~25 lines, mirrors convergence_check.py:74-120) + module-top imports of `re`, `datetime`.
- `hooks/worker_budget.py`: `check_workers_lt_3` signature + read-source change (~10 lines); `pre_check` call site (1 line).
- `scripts/test_worker_budget.py`: 2 old tests migrated + 3 new tests (~35 lines).
- Behavior change: the gate is no longer affected by reconcile clearing / stale residue — the core fix of this issue.
- Related: complements #38 (stuck-worker mechanical gate), #39 (external-kicker). This issue fixes "wrong count source"; #38 fixes "stuck worker not released"; #39 fixes "kick when stalled".
- NOT in scope: no change to convergence_check.py (already the single source); no reconcile-at-dispatch patch (explicitly rejected by the issue — reconcile is LLM-driven and cannot be a gate dependency); no change to MAX_WORKERS / STUCK_MINUTES semantics.
