## ADDED Requirements

### Requirement: tick SHALL evaluate the drift predicate on a fresh heartbeat before skipping

`scripts/external_kicker.py::tick(workspace, *, tick_interval_min, stale_minutes, settings_path, claude_bin, dry_run)` SHALL, when `session_is_dead(heartbeat, now, stale_minutes)` is False (heartbeat fresh), evaluate `should_kick(workspace)` BEFORE returning. `should_kick` is the #43 drift predicate (rotation >= `DRIFT_ESCALATE_ROWS` = 6 AND `drift_detected` = rotation >= `ROTATION_WINDOW` = 3 AND NOT `workers_progressing`) — the SAME function the pure tests prove; no second drift definition may be introduced. When `should_kick` is True, the tick SHALL continue onto the SAME guarded recovery path as a stale session: the already-held kick lock, project-hooks ensure, `build_resume_prompt` staging to `runs/.kicker-prompt.txt`, dry-run/spawn semantics, and `runs/.kicker-last.json` receipt write. When `should_kick` is False, the tick SHALL print `kicker: skip — session alive (heartbeat fresh)` and return 0 exactly as before.

#### Scenario: fresh heartbeat with six frozen ledger rows produces a drift receipt in dry-run

- **WHEN** `runs/.heartbeat.json` is fresh, `.convergence_ledger.jsonl` holds 6 identical signatures, there is no fresh in-progress worker status file, and `tick(ws, dry_run=True)` is called
- **THEN** the tick returns 0, `runs/.kicker-last.json` exists with `reason: "drift"` plus `kick_ts` / `prompt_file` / `pid`, `runs/.kicker-prompt.txt` is staged, and the output contains a DRIFT-KICK line — the same guarded recovery path a stale session reaches, with a distinct receipt

#### Scenario: fresh heartbeat with fewer than six frozen rows does not kick

- **WHEN** the heartbeat is fresh and `.convergence_ledger.jsonl` holds 5 (or fewer) identical signatures (below `DRIFT_ESCALATE_ROWS`)
- **THEN** the tick prints the alive skip line, returns 0, and writes NO `runs/.kicker-last.json`

#### Scenario: fresh heartbeat with a progressing worker does not kick

- **WHEN** the heartbeat is fresh, the ledger holds 6 frozen rows, AND an in-progress `runs/worker-status-*.md` file has an mtime younger than `WORKER_PROGRESS_MINUTES` (fresh-worker race / legal SATURATED wait)
- **THEN** the tick does NOT kick — no receipt, no spawn — and returns 0

#### Scenario: healed / cure-window state does not kick

- **WHEN** the heartbeat is fresh and the ledger's tail shows rotation below `ROTATION_WINDOW` (healed) or rotation >= 3 but below 6 with a healed signature inside the 3→6-row cure window
- **THEN** the tick does NOT kick and returns 0

### Requirement: drift receipts SHALL be distinct from stale-session receipts without regressing the stale path

The `runs/.kicker-last.json` receipt written on the drift path SHALL carry `reason: "drift"` as an additional key. The stale-session path (heartbeat dead) SHALL keep producing the EXACT current receipt shape `{kick_ts, prompt_file, pid}` — no `reason` key — and SHALL keep its existing skip/print/spawn behavior, lock behavior (acquire/release in `finally`), and no-real-spawn guarantee under `dry_run=True`. The spawn-failure record (pid=-1) SHALL also carry `reason: "drift"` when the kick was drift-initiated.

#### Scenario: repeated dry-run drift ticks are deterministic

- **WHEN** `tick(ws, dry_run=True)` is called twice consecutively against the same fresh-heartbeat + six-frozen-rows workspace (lock released between rounds)
- **THEN** both calls return 0, both write `runs/.kicker-last.json` with `reason: "drift"`, and neither raises

#### Scenario: stale-session tick is unchanged

- **WHEN** `tick(ws, dry_run=True)` is called with no heartbeat file (dead session, existing `test_kick_stages_resume_prompt` setup)
- **THEN** the tick returns 0, stages `runs/.kicker-prompt.txt`, and writes `runs/.kicker-last.json` WITHOUT a `reason` key — the receipt shape is byte-identical to pre-#79 output

#### Scenario: held lock skips both drift and stale paths

- **WHEN** a fresh `runs/.kicker.lock` (younger than `tick_interval_min`) exists at tick start, regardless of drift state
- **THEN** the tick prints the lock-skip line and returns 0 without evaluating the heartbeat or drift (existing lock behavior unchanged)
