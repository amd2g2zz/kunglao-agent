# Design — active-workers-single-source (#37)

## Design Decisions

### D1. scan function lives in lib_kunglao (shared host)

`scan_active_workers(workspace) -> (active: int, stuck: list)` goes into `hooks/lib_kunglao.py` (already the hooks shared host — `is_active` / `resolve_workspace` live there). It is a **byte-for-byte mirror** of `scripts/convergence_check.py:74-120` `_scan_active_workers`:

- Directories scanned: `workspace / "runs"` + `workspace.parent.glob(".wt-*/malware-analysis-workspace/runs")` (worktree isolation, v1.9.13).
- Active rule: the **last** `status:\s*(\S+)` line in a `worker-status-*.md` equals `in-progress`. done/blocked/no-status files do NOT count (worktree snapshots carry historical files — only the last line decides).
- Stuck rule: active files whose mtime is older than STUCK_MINUTES (20).
- Error tolerance: `OSError` on glob/read/stat skips that file; no crash.

Why a mirror and not an import of convergence_check._scan_active_workers: worker_budget is a hook (runs in the Claude Code process via `sys.path.insert`), convergence_check is invoked via subprocess (`_run_py`). Having the hook shell out to convergence_check would add a process spawn per dispatch plus a more complex failure mode (JSON parse errors, convergence_check also runs its full decide matrix). A shared pure function = each callsite invokes it in-process, minimal overhead, and mirror-not-rewrite guarantees the semantics cannot drift (the exact failure this issue eliminates).

### D2. check_workers_lt_3 switches read source + FAIL_OPEN

Signature `(state_path: Path)` becomes `(paths: dict)`. Read source: `paths.get('workspace')` then `lib_kunglao.scan_active_workers(Path(ws))`.

FAIL_OPEN policy (mirrors `check_plan_drift` / `check_convergence_health` already in this file):
- `workspace` key missing -> `(True, '')` (no workspace, allow).
- `scan_active_workers` raises -> `(True, '')` (scan failure must not block dispatch — the hook must fail open or worker_budget itself crashing deadlocks the whole loop).

Threshold unchanged: `n >= MAX_WORKERS(3)` -> REJECT `f'active_workers={n} >= {MAX_WORKERS}'`.

### D3. state segment demoted (write retained, not read)

`register_worker` / `remove_worker` keep writing the `[active_workers]` segment. Rationale:
- `post_check` calls `remove_worker(state, worker_id)` when a worker finishes — that is the existing worker-done release path; changing it is out of scope.
- The cache still has display value (the orchestrator can read the segment to quickly see who was dispatched).
- The gate does not read the segment = removing ONE read source, not removing the write path — consistent with the issue single-source-of-truth semantic (writes may have many consumers, but the gate DECISION trusts only status files).

### D4. old test signature migration

`test_check_workers_lt_3_ok` / `test_check_workers_lt_3_reject` currently pass a `Path` (state_path). The new signature is a dict. Migration: build `{'workspace': str(p.parent)}` and write status files into `p.parent / 'runs'` (instead of relying on the state segment). This is a required sync of the signature change, not a pure append.

## Rejected Alternatives

- **R1: reconcile-at-dispatch + remove_worker idempotence** (surface patch): let pre_check call reconcile to sync the state segment, then read it. **Rejected** — the issue explicitly rejects this: reconcile is an LLM-driven cron tick; depending the gate on it = the gate depends on LLM behavior, violating the mechanical-gate principle. Reconcile is also complex and introduces new failure modes.
- **R2: hook shells out to convergence_check._scan_active_workers**: spawn convergence_check.py once per dispatch and parse its JSON. **Rejected** — process-spawn overhead + JSON-parse failure modes + convergence_check runs its full decide matrix (the hook only needs the active count). Cost/complexity not worth it.
- **R3: move _scan_active_workers from convergence_check to lib, make convergence_check import lib**: most DRY, but **modifying convergence_check.py is out of scope** (the plan NOT-Building explicitly says do not touch convergence_check.py). This issue only does gate-switches-read-source + lib-gains-mirror; convergence_check can optionally import lib later (follow-up).
- **R4: delete the state-segment write path entirely**: purest single-source. **Rejected** — post_check remove_worker is the existing worker-completion path; deleting it has wide blast radius. The segment as a cache is harmless (the gate simply does not read it); retaining the write path is zero-risk.

## File layout

| File | Action | Purpose |
|---|---|---|
| `hooks/lib_kunglao.py` | UPDATE | +`scan_active_workers(workspace)` shared host (mirrors convergence_check.py:74-120) |
| `hooks/worker_budget.py` | UPDATE | `check_workers_lt_3(paths: dict)` switches read source; `pre_check` call site adapts |
| `scripts/test_worker_budget.py` | UPDATE | old tests migrated to dict signature + 3 new status-scan tests |

## Out of scope

- Modifying convergence_check.py (already the single source; can optionally import lib later).
- reconcile-at-dispatch / remove_worker idempotence (issue rejects).
- MAX_WORKERS / STUCK_MINUTES semantic changes.
- worker_pulse.py (it runs convergence_check; it does not call check_workers_lt_3 directly).
