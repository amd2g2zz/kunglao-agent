## ADDED Requirements

### Requirement: signature_rotation SHALL count consecutive identical ledger signatures, excluding ts

`scripts/lib_kunglao.py::signature_rotation(workspace) -> int` SHALL read the last rows of the workspace's `.convergence_ledger.jsonl` (default window = `max(ROTATION_WINDOW, DRIFT_ESCALATE_ROWS)`), build a signature tuple `(decision, open_ids, partial_count, active_workers, blockers, facts_total)` per row — **`ts` excluded**, `open_count` excluded (derivable from `open_ids`) — and return the number of consecutive valid rows ending at the last valid row whose signature equals that reference signature. A missing or empty ledger, or a ledger with no valid row, SHALL return `0`. A row that fails to parse (bad JSON / missing field / non-dict / empty line) SHALL be skipped without raising — a corrupt ledger line must never crash the gate. Decoding SHALL use `errors="replace"`.

#### Scenario: frozen tail of three rows yields rotation 3
- **WHEN** the last 3 rows of `.convergence_ledger.jsonl` carry the same `(decision, open_ids, partial_count, active_workers, blockers, facts_total)` and a 4th (older) row differs
- **THEN** `signature_rotation(ws)` returns `3`

#### Scenario: differing timestamps do not break the run
- **WHEN** consecutive rows differ only in `ts` (every other field identical)
- **THEN** they count as identical — `ts` is excluded from the signature

#### Scenario: open_count differences do not break the run
- **WHEN** consecutive rows differ only in `open_count`
- **THEN** they count as identical — `open_count` is derivable and excluded

#### Scenario: corrupt ledger line never crashes the gate
- **WHEN** the ledger contains a malformed line (e.g. `not-json`) between identical rows
- **THEN** `signature_rotation(ws)` skips the corrupt line without raising and still counts the valid identical rows

#### Scenario: missing ledger yields zero
- **WHEN** the workspace has no `.convergence_ledger.jsonl` (or it is empty)
- **THEN** `signature_rotation(ws)` returns `0`

### Requirement: workers_progressing SHALL exempt sessions with fresh in-progress workers

`scripts/lib_kunglao.py::workers_progressing(workspace, now=None, fresh_minutes=WORKER_PROGRESS_MINUTES) -> bool` SHALL return True when ANY `worker-status-*.md` file whose LAST `status:\s*(\S+)` line is `in-progress` has an mtime younger than `fresh_minutes` (default `WORKER_PROGRESS_MINUTES = 20`). Scan targets SHALL mirror `convergence_check._scan_active_workers`: `workspace/runs` plus every `workspace.parent.glob(".wt-*/malware-analysis-workspace/runs")` worktree dir. Files with a last status other than `in-progress`, stale files, OSErrors on read/stat/glob, and a missing `runs/` dir SHALL NOT count. `now` SHALL default to `datetime.now(timezone.utc)` and be injectable for deterministic tests.

#### Scenario: fresh in-progress worker exempts
- **WHEN** an in-progress `worker-status-*.md` has mtime 5 minutes ago
- **THEN** `workers_progressing(ws, now=NOW)` returns True

#### Scenario: stale in-progress worker does not exempt
- **WHEN** an in-progress `worker-status-*.md` has mtime 45 minutes ago (beyond `WORKER_PROGRESS_MINUTES`)
- **THEN** `workers_progressing(ws, now=NOW)` returns False

#### Scenario: done-status file does not exempt
- **WHEN** the only status file's last status line is `done`
- **THEN** `workers_progressing(ws, now=NOW)` returns False

#### Scenario: worktree status files count
- **WHEN** a fresh in-progress `worker-status-*.md` lives under `.wt-NN/malware-analysis-workspace/runs/` rather than the main `runs/`
- **THEN** `workers_progressing(ws, now=NOW)` returns True

#### Scenario: no status files yields False
- **WHEN** no `worker-status-*.md` exists anywhere in the scan targets
- **THEN** `workers_progressing(ws, now=NOW)` returns False

### Requirement: drift_detected SHALL require a frozen window and no worker movement

`scripts/lib_kunglao.py::drift_detected(workspace) -> bool` SHALL return `signature_rotation(ws) >= ROTATION_WINDOW AND NOT workers_progressing(ws)` — the alive-but-stuck regime (heartbeat fresh, ledger writing, state frozen) that time-based dead-session detection cannot see. `ROTATION_WINDOW` SHALL default to `3`.

#### Scenario: frozen three rows with no worker is drift
- **WHEN** `signature_rotation(ws) == 3` and no in-progress worker status file is fresh
- **THEN** `drift_detected(ws)` returns True

#### Scenario: frozen three rows with a fresh worker is a legal wait
- **WHEN** `signature_rotation(ws) == 3` and an in-progress worker status file is 5 minutes old
- **THEN** `workers_progressing(ws)` returns True and `drift_detected(ws)` returns False — the SATURATED wait is exempt

#### Scenario: rotation below the window is not drift
- **WHEN** `signature_rotation(ws) == 2`
- **THEN** `drift_detected(ws)` returns False

### Requirement: should_kick SHALL escalate only on persistent drift beyond the cure window

`scripts/external_kicker.py::should_kick(workspace) -> bool` SHALL implement the #43 drift branch: return `drift_detected(ws) AND signature_rotation(ws) >= DRIFT_ESCALATE_ROWS` (`DRIFT_ESCALATE_ROWS = 6`). A drift detected at `ROTATION_WINDOW` (3) rows but not persistent (rotation < `DRIFT_ESCALATE_ROWS`, i.e. an older row within the window differs) SHALL NOT kick — the 3→6-row gap is the cure-first window for the #44 `state_anchor` hook. The function SHALL import the `lib_kunglao` helpers at function level (the file's existing lazy-import pattern) so the top-level import section of `external_kicker.py` stays untouched.

#### Scenario: six frozen rows escalate
- **WHEN** the last 6 ledger rows are identical and no in-progress worker is fresh
- **THEN** `should_kick(ws)` returns True

#### Scenario: rotation three with changed older rows does not escalate
- **WHEN** the last 3 rows are identical but the 4th-6th rows (older) differ from the tail signature — rotation is 3
- **THEN** `should_kick(ws)` returns False — the drift is not persistent

#### Scenario: fresh worker blocks escalation
- **WHEN** 6 identical ledger rows exist but an in-progress worker status file is 5 minutes old
- **THEN** `should_kick(ws)` returns False

#### Scenario: rotation below the escalation threshold does not kick
- **WHEN** the last 5 ledger rows are identical (rotation 5, above detection, below escalation)
- **THEN** `should_kick(ws)` returns False

### Requirement: drift thresholds SHALL be tunable module constants

`scripts/lib_kunglao.py` SHALL define `ROTATION_WINDOW = 3`, `DRIFT_ESCALATE_ROWS = 6`, and `WORKER_PROGRESS_MINUTES = 20` as module-level constants, and all drift functions SHALL read them (with per-call override parameters where a test needs one). The signature window SHALL track the constants (`max(ROTATION_WINDOW, DRIFT_ESCALATE_ROWS)`), so raising `DRIFT_ESCALATE_ROWS` automatically extends the read horizon.

#### Scenario: constants are importable and wired
- **WHEN** `ROTATION_WINDOW`, `DRIFT_ESCALATE_ROWS`, `WORKER_PROGRESS_MINUTES` are imported from `lib_kunglao`
- **THEN** they equal `3`, `6`, `20` respectively, and `signature_rotation` reads a window of `max(ROTATION_WINDOW, DRIFT_ESCALATE_ROWS)` rows
