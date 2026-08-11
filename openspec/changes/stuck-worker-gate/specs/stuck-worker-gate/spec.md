## ADDED Requirements

### Requirement: worker_budget SHALL reject dispatch when backtrack_gate detects a stuck worker

`hooks/worker_budget.py::check_backtrack_gate(paths)` SHALL wrap `scripts/backtrack_gate.py` via the shared `_run_py` subprocess helper (20s timeout, FAIL_OPEN) and SHALL be the final entry in `pre_check`'s checks list, immediately after `('health', check_convergence_health(paths))`. A stuck worker — in-progress with file mtime older than the stuck threshold AND no valid `## backtrack` block (backtrack_gate rc=1), OR a stale un-actioned backtrack older than 30 minutes with a decision other than `redispatch` (backtrack_gate rc=2) — MUST reject the dispatch with a guiding message naming the failure mode. backtrack_gate rc=0 (clean, or stuck-but-valid-backtrack) MUST pass. Any subprocess failure, timeout, missing workspace, or unknown return code MUST fail open to (True, "") so a broken gate never blocks dispatch.

#### Scenario: stuck worker without a backtrack block rejects dispatch
- **WHEN** `backtrack_gate.py` returns rc=1
- **THEN** `check_backtrack_gate(paths)` returns `(False, msg)` where msg contains "backtrack", and `pre_check` rejects the dispatch with check name `backtrack`

#### Scenario: stale un-actioned backtrack rejects dispatch
- **WHEN** `backtrack_gate.py` returns rc=2
- **THEN** `check_backtrack_gate(paths)` returns `(False, msg)` where msg contains "escalate" or "redispatch"

#### Scenario: clean workspace passes
- **WHEN** `backtrack_gate.py` returns rc=0
- **THEN** `check_backtrack_gate(paths)` returns `(True, "")`

#### Scenario: missing workspace fails open
- **WHEN** the `paths` dict has no `workspace` key
- **THEN** `check_backtrack_gate(paths)` returns `(True, "")` without invoking the subprocess

#### Scenario: subprocess failure or unknown rc fails open
- **WHEN** `_run_py` returns `None` (timeout / missing script) OR `backtrack_gate.py` returns a return code other than 0, 1, or 2
- **THEN** `check_backtrack_gate(paths)` returns `(True, "")`

### Requirement: worker_pulse SHALL surface mtime-stale in-progress workers on any Agent PostToolUse

`hooks/worker_pulse.py::_check_stale_workers(ws)` SHALL scan `ws/runs/worker-status-*.md` for files whose last `status:` line resolves to `in_progress` (case-insensitive, `-`/`_` normalized) and whose file mtime exceeds `STUCK_MIN` (20 minutes, mirroring backtrack_gate's default). On the non-dispatch PostToolUse path — where `main()` previously returned silently at the `if not _was_dispatch(payload): return 0` line — worker_pulse SHALL call `_check_stale_workers` and, if it returns a non-empty message, emit it as a soft `additionalContext` (the same JSON shape used for the dispatch-complete pulse). It MUST NEVER abort (rc=0); the hard reject remains worker_budget's responsibility. Any OSError, missing `runs/` directory, or unreadable status file MUST yield the empty string (no crash, no false alarm).

#### Scenario: stale in-progress worker is surfaced
- **GIVEN** `runs/worker-status-w1.md` whose last `status:` line is `in-progress` and whose file mtime is 25 minutes ago
- **WHEN** `_check_stale_workers(ws)` runs
- **THEN** it returns a non-empty message that names `w1` and reports the age in minutes

#### Scenario: fresh in-progress worker is not flagged
- **GIVEN** `runs/worker-status-w1.md` whose last `status:` line is `in-progress` and whose file mtime is 2 minutes ago
- **WHEN** `_check_stale_workers(ws)` runs
- **THEN** it returns `""`

#### Scenario: completed worker is not flagged regardless of age
- **GIVEN** `runs/worker-status-w1.md` whose last `status:` line is `done` and whose file mtime is 40 minutes ago
- **WHEN** `_check_stale_workers(ws)` runs
- **THEN** it returns `""`

#### Scenario: missing runs directory yields no alarm
- **WHEN** `_check_stale_workers(ws)` runs against a workspace with no `runs/` directory
- **THEN** it returns `""` without raising
