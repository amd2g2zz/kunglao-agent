## ADDED Requirements

### Requirement: The external kicker SHALL decide a workspace session is dead from heartbeat staleness

`scripts/external_kicker.py::session_is_dead(heartbeat, now, stale_minutes)` SHALL return `True` when the heartbeat state is `None` (no `runs/.heartbeat.json` — never registered), or when BOTH `last_tick_ts` and `activity_ts` are missing, unparseable, or older than `stale_minutes`; and SHALL return `False` when either `last_tick_ts` or `activity_ts` is present, parseable, and younger than `stale_minutes`. `last_tick_ts` is written by the loop's renew tick; `activity_ts` is written mechanically by the `heartbeat_touch` hook on every tool call. Unparseable timestamps SHALL be treated as stale (recovery bias — the kicker repairs broken states, it does not preserve them).

#### Scenario: missing heartbeat file is dead
- **GIVEN** `heartbeat` is `None` (no `.heartbeat.json` was ever written)
- **WHEN** `session_is_dead` is called with any `now` and `stale_minutes`
- **THEN** it returns `True`

#### Scenario: fresh last_tick_ts means alive
- **GIVEN** `heartbeat` has `last_tick_ts` 2 minutes before `now` and `activity_ts` 2 hours before `now`, with `stale_minutes=10`
- **WHEN** `session_is_dead` is called
- **THEN** it returns `False`

#### Scenario: fresh activity_ts alone means alive
- **GIVEN** `heartbeat` has `activity_ts` 2 minutes before `now` and `last_tick_ts` 2 hours before `now`, with `stale_minutes=10`
- **WHEN** `session_is_dead` is called
- **THEN** it returns `False`

#### Scenario: both signals stale means dead
- **GIVEN** both `last_tick_ts` and `activity_ts` are 2 hours before `now`, with `stale_minutes=10`
- **WHEN** `session_is_dead` is called
- **THEN** it returns `True`

#### Scenario: unparseable or absent timestamps count as stale
- **GIVEN** `heartbeat` has `last_tick_ts="not-a-timestamp"` and no `activity_ts` (or `{"started_ts": ...}` only)
- **WHEN** `session_is_dead` is called
- **THEN** it returns `True` (no parseable signal proves liveness)

### Requirement: The external kicker SHALL reject a tick interval at or above the 30-minute activation TTL

`scripts/external_kicker.py::tick(...)` SHALL refuse to run — printing the requirement and exiting 1 — when `tick_interval_min >= ACTIVATION_TTL_MINUTES (30)` (the hook_activation TTL, `DEFAULT_TTL_MINUTES`). The default interval SHALL be 15 minutes. This enforces the no-silent-gate-window rule mechanically: between TTL expiry and the next tick there must never be a moment where hooks sleep with no session able to re-activate them.

#### Scenario: 30-minute interval is rejected
- **GIVEN** `tick_interval_min=30` (or larger)
- **WHEN** `tick()` is invoked
- **THEN** it exits 1 without any side effect (no lock, no settings write, no kick record)

#### Scenario: 15-minute interval is accepted
- **GIVEN** `tick_interval_min=15` (the default)
- **WHEN** `tick()` is invoked
- **THEN** it proceeds past the validation gate

### Requirement: The external kicker SHALL re-register kunglao hooks in PROJECT-level settings preserving the env segment

`scripts/external_kicker.py::ensure_project_hooks(settings, hook_dir) -> (dict, int)` SHALL return a new settings dict that carries every pre-existing key with byte-identical values — including `env` (API secrets), `mcpServers`, `permissions`, and any hook entries whose matcher is not one of the kunglao ones — plus exactly five kunglao entries in the same shape as `wire_up_settings._ensure`: PreToolUse `worker_budget.py` and `dispatch_gate.py` on matcher `Agent`, PreToolUse `heartbeat_touch.py` on matcher `Bash`, PostToolUse `worker_budget.py` and `worker_pulse.py` on matcher `Agent` (command = `python <hook_dir>/<file>` with POSIX separators). Entries with a matcher already targeted SHALL be replaced by basename (legacy backslash paths cleaned), never stacked. The tick SHALL write the transformed dict only when it differs from the current file, atomically (tmp→replace), to the PROJECT settings file `<workspace-parent>/.claude/settings.json` — NEVER to `~/.claude/settings.json` (the wire_up_settings.py:20 mis-wiring bug).

#### Scenario: env secrets and unrelated keys survive re-registration
- **GIVEN** a settings dict with `env: {"VMR_API_KEY": "<secret>"}`, `mcpServers: {...}`, `permissions: [...]` and no `hooks` key
- **WHEN** `ensure_project_hooks` is called
- **THEN** the returned dict contains all three keys with the identical secret value, and its `hooks` segment has exactly the five kunglao entries

#### Scenario: legacy same-basename entries are replaced, not stacked
- **GIVEN** a `hooks.PreToolUse` entry with matcher `Agent` whose command ends in `worker_budget.py` (e.g. a backslash path)
- **WHEN** `ensure_project_hooks` is called
- **THEN** the returned dict has exactly one PreToolUse Agent entry ending in `worker_budget.py`

#### Scenario: unrelated matchers are preserved
- **GIVEN** a `hooks.PreToolUse` entry with matcher `Bash` for `block_malware_exec.js`
- **WHEN** `ensure_project_hooks` is called
- **THEN** that entry appears untouched in the returned dict

#### Scenario: re-running on an already-ensured dict is a no-op
- **GIVEN** a dict already returned by `ensure_project_hooks`
- **WHEN** `ensure_project_hooks` is called again
- **THEN** the result equals the input exactly (identical dict, count of changed entries 0)

#### Scenario: the tick writes only to the passed project settings path
- **GIVEN** a dead session and a project settings file at a caller-supplied path (tests use tmp_path)
- **WHEN** `tick()` runs
- **THEN** that file gains the hooks segment with all other keys preserved, and no file under the home directory is touched

### Requirement: The external kicker SHALL make exactly one session take over via lock + liveness + worker markers

`scripts/external_kicker.py::acquire_kick_lock(lock_path, interval_minutes) -> bool` SHALL create `runs/.kicker.lock` atomically (`O_CREAT|O_EXCL`); return `False` (skip) when the lock already exists with mtime younger than `interval_minutes` (a concurrent or duplicate tick already ran), replace a lock older than `interval_minutes` (crashed kicker) and retry once, and return `False` on any failure. `tick()` SHALL additionally skip when `session_is_dead` returns `False` (a live session owns the loop) or when `has_fresh_workers(runs_dir, FRESH_WORKER_MINUTES=20)` returns `True` (a `worker-status-*.md` file whose last `status:` line is `in-progress` and whose mtime is younger than 20 minutes — a session is mid-dispatch). The lock SHALL be released by the tick on exit; a stale lock is self-healing via the mtime rule.

#### Scenario: two racing ticks yield exactly one kick
- **GIVEN** a lock file created by the first tick's `acquire_kick_lock` moments ago
- **WHEN** a second `acquire_kick_lock` call runs with the same path and interval
- **THEN** it returns `False` — the second tick skips, one session takes over

#### Scenario: stale lock from a crashed kicker is replaced
- **GIVEN** a lock file whose mtime is 20 minutes old and `interval_minutes=15`
- **WHEN** `acquire_kick_lock` is called
- **THEN** it returns `True` and the lock file now carries the new timestamp

#### Scenario: alive session suppresses the kick
- **GIVEN** a fresh `last_tick_ts` in the heartbeat and no lock contention
- **WHEN** `tick()` runs
- **THEN** it skips: no kick record, no settings rewrite

#### Scenario: fresh in-progress workers suppress the kick
- **GIVEN** an in-progress `worker-status-*.md` file with mtime 2 minutes old
- **WHEN** `has_fresh_workers` is called
- **THEN** it returns `True`; `tick()` skips

#### Scenario: stale in-progress workers do not block recovery
- **GIVEN** an in-progress `worker-status-*.md` file with mtime 2 hours old
- **WHEN** `has_fresh_workers` is called
- **THEN** it returns `False` — the dead session's legacy workers do not block the kick

### Requirement: The external kicker SHALL build the kick and scheduler commands as pure strings

`scripts/external_kicker.py::build_kick_command(claude_bin)` SHALL return `[claude_bin, "-p"]` (the fresh-session prompt, produced VERBATIM by `heartbeat_loop_prompt.build_prompt(ws)` and persisted to `runs/.kicker-prompt.txt`, SHALL be delivered via stdin with cwd=workspace). `build_schtasks_command(task_name, interval_min, python_exe, script, workspace)` SHALL return the `schtasks /create /tn <task_name> /sc minute /mo <interval> /tr "<python_exe> <script> <workspace>" /f` argument list; `build_crontab_line(interval_min, python_exe, script, workspace)` SHALL return the `*/<interval> * * * * <python_exe> <script> <workspace>` line. Neither the code nor the tests SHALL register a scheduled task or spawn a claude process — registration and the true end-to-end kill→kick are documented manual steps.

#### Scenario: kick command construction
- **GIVEN** `claude_bin="claude"`
- **WHEN** `build_kick_command` is called
- **THEN** it returns `["claude", "-p"]`

#### Scenario: schtasks command construction for a 15-minute tick
- **GIVEN** `task_name="kunglao_kicker"`, `interval_min=15`, and concrete paths
- **WHEN** `build_schtasks_command` is called
- **THEN** it returns the argument list containing `/sc minute`, `/mo 15`, and a `/tr` value quoting the python script invocation

#### Scenario: crontab line construction
- **GIVEN** `interval_min=15` and concrete paths
- **WHEN** `build_crontab_line` is called
- **THEN** it returns a string starting with `*/15 * * * * ` followed by the quoted python script invocation

### Requirement: The external kicker SHALL record each kick and use the loop prompt verbatim

After passing all competition gates and confirming a dead session, `tick()` SHALL (1) write the `heartbeat_loop_prompt.build_prompt(workspace)` output verbatim to `runs/.kicker-prompt.txt`, and (2) write `runs/.kicker-last.json` with `kick_ts`, `prompt_file`, and the spawned pid, before releasing the lock. A subsequent tick after a successful kick SHALL observe a fresh heartbeat (the fresh session's first loop action re-registers it) and skip.

#### Scenario: kill-session → tick → kick record + fresh heartbeat re-registration decision
- **GIVEN** a workspace whose heartbeat is 2 hours stale, no fresh workers, no lock, and a project settings file lacking the hooks segment
- **WHEN** `tick(workspace, dry_run=True)` runs
- **THEN** it exits 0, `runs/.kicker-prompt.txt` equals `heartbeat_loop_prompt.build_prompt(workspace)` byte-for-byte, `runs/.kicker-last.json` exists with a `kick_ts`, and the project settings file now contains the five hooks with `env` preserved
