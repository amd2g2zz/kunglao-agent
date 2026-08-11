## ADDED Requirements

### Requirement: The worker-budget concurrency gate SHALL count active workers from status files, not the analysis_state.txt cache

`hooks/worker_budget.py::check_workers_lt_3` SHALL determine the active-worker count by scanning `runs/worker-status-*.md` (last `status:` line == `in-progress`) plus every `.wt-*/malware-analysis-workspace/runs/` worktree status directory, via the shared `hooks/lib_kunglao.py::scan_active_workers`. The `[active_workers]` segment of `analysis_state.txt` SHALL NOT participate in the gate decision — it remains a cache/display only (register_worker/remove_worker keep writing it). This makes the gate and `convergence_check._scan_active_workers` read the same single source of truth, so a reconciled-to-empty or stale-residue state segment can neither over-allow nor over-block dispatch.

#### Scenario: three in-progress status files reject the fourth dispatch
- **WHEN** three `worker-status-*.md` files in `runs/` each have a last status line of `in-progress`
- **THEN** `check_workers_lt_3(paths)` returns `(False, ...)` with `3` in the message, regardless of the `[active_workers]` cache contents

#### Scenario: empty state cache with one active worker does not fool the gate
- **WHEN** one `worker-status-*.md` file is `in-progress` and `analysis_state.txt` has no `[active_workers]` segment (or it was reconciled to empty)
- **THEN** `check_workers_lt_3(paths)` returns `(True, ...)` — the gate counts 1 active worker from status files, not 0 from the empty cache

#### Scenario: done status files do not occupy slots
- **WHEN** one status file last line is `in-progress` and another last line is `done`
- **THEN** only the in-progress file counts toward the limit; `check_workers_lt_3(paths)` returns `(True, ...)`

#### Scenario: missing workspace key fails open
- **WHEN** `paths` lacks a `workspace` key or `scan_active_workers` raises
- **THEN** `check_workers_lt_3(paths)` returns `(True, '')` — the hook never blocks dispatch on a scan failure

### Requirement: scan_active_workers SHALL be byte-equivalent to convergence_check._scan_active_workers

`hooks/lib_kunglao.py::scan_active_workers(workspace) -> (active, stuck)` SHALL mirror `scripts/convergence_check.py:_scan_active_workers` exactly: scan `workspace/runs` plus `workspace.parent.glob(".wt-*/malware-analysis-workspace/runs")`; count a worker active only if the LAST `status:\s*(\S+)` line in its `worker-status-*.md` is `in-progress`; flag a worker as stuck when its file mtime exceeds STUCK_MINUTES (20); skip files on `OSError`. This shared host eliminates the double implementation so the gate and the convergence decision cannot drift.

#### Scenario: same runs directory yields the same count as convergence_check
- **WHEN** `scan_active_workers(workspace)` and `convergence_check._scan_active_workers(workspace)` scan the same `runs/` tree
- **THEN** both return the same `active` integer and the same stuck set

#### Scenario: worktree status files are included
- **WHEN** an in-progress `worker-status-*.md` lives under `.wt-NN/malware-analysis-workspace/runs/` rather than the main `runs/`
- **THEN** `scan_active_workers` still counts it as active
