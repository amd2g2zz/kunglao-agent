# Design — external-kicker (#39)

## Design Decisions

### D1. Dead-session detection = heartbeat staleness (both signals), pure function

`session_is_dead(heartbeat: dict | None, now: datetime, stale_minutes: int) -> bool`:

- `heartbeat is None` (file missing) → dead. A workspace that never
  registered a heartbeat has no loop keeper; the kicker bootstraps it.
- `last_tick_ts` fresh → ALIVE. The loop's renew tick writes it (LLM-driven,
  5-min cron).
- `activity_ts` fresh → ALIVE. The heartbeat_touch hook writes it on EVERY
  tool call — purely mechanical (v1.9.36). A busy session always has it
  fresh.
- Both stale (or absent / unparseable) → dead.

Why BOTH signals, not one: `last_tick_ts` alone goes stale when a live
session is busy (renew is LLM-driven and the cron prompt gets skipped);
`activity_ts` alone goes stale when hooks were dropped (then no hook fires).
Requiring both to be stale makes the dead verdict robust: only a session
with no tool activity AND no loop ticks for `stale_minutes` is kicked.

Threshold: default `STALE_MINUTES = 10`, tick interval default 15. Worst
case death (just before a tick) is detected at ≤ 15 + 10 = 25 min < 30-min
TTL → the kick always lands before the activation TTL expires, so there is
never a moment where hooks sleep with no session to re-activate them (the
issue's no-silent-window requirement). The kicker also HARD-REJECTS
`interval >= 30` (exit 1) so a misconfigured schedule cannot reintroduce the
window.

Unparseable timestamps are treated as stale (recovery bias: the kicker's job
is to repair broken states, not preserve them). `activity_ts`/`last_tick_ts`
absent fields → cannot prove liveness → dead.

NOT used: `.hook_state.json` `expires_at` as a liveness signal. It is
LLM-renewed and would delay detection to the TTL boundary (the exact window
the issue forbids). `expires_at` granularity (30 min) is too coarse for the
kicker's 15-min cadence.

Known limitation (documented): a session that is alive but whose hooks were
dropped AND which makes no tool calls for 10 min is indistinguishable from a
dead session → the kicker starts a second session. That session's
`--heartbeat-on` registration + project-level hook re-registration (D2)
self-heals wiring, and the fresh heartbeat then blocks any third kick. Bounded,
self-healing, accepted for the skeleton scope (process-level pid fencing is
#43/#45 territory).

### D2. Project-level settings re-registration = pure dict transform, env-preserving

`ensure_project_hooks(settings: dict, hook_dir: str) -> (dict, int)` mirrors
`wire_up_settings._ensure` EXACTLY for the 5 entries (same matchers, same
`{"type": "command", "command": f"python {posix_path}"}` shape, same
basename dedupe so legacy backslash-path entries are replaced not stacked),
but operates on a **dict passed in** and returns the new dict — the caller
decides where to write it:

- Default target: `<workspace-parent>/.claude/settings.json` (project level —
  the file where the 6 live hooks actually fire; mirrors hooks_selfcheck.py:78).
- EVERY other key of the settings dict is carried through untouched — `env`
  (VMR_API_KEY etc.), `mcpServers`, `permissions`, other hooks events, other
  matchers' entries. Byte-identical values; the pure function never
  serializes anything itself.
- Written atomically (tmp→replace, heartbeat_touch F2 pattern) and ONLY when
  the transformed dict differs from the current file content — a healthy
  file is never rewritten.
- Explicitly NEVER writes `~/.claude/settings.json` (the wire_up bug, 坑 7).

Why not fix `wire_up_settings.py` itself: migrating `--wire-up` changes its
contract (it has no workspace argument today) and every caller; the kicker
implements the correct project-level path as the live recovery mechanism.
Documented as a follow-up.

Hook dir: `Path(__file__).resolve().parent.parent / "hooks"` (repo-relative,
same rule as wire_up_settings.py:33) — in the installed skill
(`~/.claude/skills/kunglao-agent`) this resolves to the live hooks location.

### D3. Competition = lock file + heartbeat + fresh-worker markers

Exactly one session takes over. Three skip conditions, evaluated in order:

1. **Atomic lock** `runs/.kicker.lock`: created with `os.open(..., O_CREAT|O_EXCL)`.
   If it already exists and its mtime is YOUNGER than the tick interval, a
   concurrent/duplicate kicker tick ran recently → SKIP (this is the
   multi-start race: two ticks, one winner). If older, the lock is stale
   (crashed kicker) → replace it. Released by the tick at the end; the
   mtime rule makes an unreleased lock harmless.
2. **Heartbeat alive** (D1) → SKIP. A live session owns the loop.
3. **Fresh in-progress worker status files** (`runs/worker-status-*.md`, last
   `status:` line `in-progress`, mtime < `FRESH_WORKER_MINUTES` = 20) → SKIP.
   A session is mid-dispatch; kicking would risk duplicate workers on the
   same claim. Stale in-progress files (a dead session's legacy) do NOT block
   the kick — that is precisely the stuck state the kicker recovers from.

The fresh session's first loop action (`--heartbeat-on`) re-registers the
heartbeat, so the next tick's D1 check sees a live session and skips — the
kick is idempotent.

### D4. Kick = prompt from heartbeat_loop_prompt + detached `claude -p`

- Prompt: `heartbeat_loop_prompt.build_prompt(ws)` output VERBATIM (the
  issue: "prompt = heartbeat_loop_prompt 输出"). Written to
  `runs/.kicker-prompt.txt` (visible artifact, avoids CLI arg-length issues).
- Command: `build_kick_command(claude_bin) -> [claude_bin, "-p"]`; the prompt
  is delivered via **stdin** (no quoting hell on Windows schtasks /tr).
- Spawn: `subprocess.Popen(args, cwd=workspace, stdin=PIPE)` with
  `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` on win32 /
  `start_new_session=True` on POSIX — the fresh session survives the
  kicker's exit.
- Record `runs/.kicker-last.json` `{kick_ts, prompt_file, pid}`.
- The TRUE E2E (session killed → scheduled tick → fresh session running the
  loop) is a documented manual step in the PR body; unit tests cover the
  decision + construction, never spawning.

### D5. schtasks/cron = pure string construction, never registered by the code

`build_schtasks_command(task_name, interval_min, python_exe, script, workspace)`
returns the full `schtasks /create /tn ... /sc minute /mo <n> /tr "<py> <script> <ws>" /f`
arg list; `build_crontab_line(...)` returns `*/<n> * * * * ...`. Tests assert
the strings. One-time registration is a documented manual step (registration
on a dev machine during tests is explicitly forbidden).

### D6. Interval validation is a hard gate

`tick()` rejects `tick_interval_min >= ACTIVATION_TTL_MINUTES (30)` with
exit 1 before ANY side effect — the no-silent-window requirement is enforced
mechanically, not by convention.

## Rejected Alternatives

- **R1: user-level settings rewrite via existing `--wire-up`**: the T1
  root-cause path — writes a file the hooks never read. Rejected by the
  issue.
- **R2: process-based session detection (tasklist / ps + cwd match)**:
  fragile across platforms, needs elevated privileges to read other
  processes' cwd, false-positives on any claude.exe running elsewhere.
  Signal-based detection (D1) is the file-state pattern this repo already
  uses (heartbeat.py, hooks_selfcheck).
- **R3: `.hook_state.json` expires_at as an alive signal**: delays detection
  to the TTL boundary — recreates the silent window. Rejected (D1).
- **R4: kicker registers the schtasks task itself**: a dev machine must not
  mutate the OS scheduler from tests, and a scheduled task is a
  human-owned, long-lived asset. The kicker builds the command; a manual
  one-time step registers it.
- **R5: cron-style interval from `hook_activation` TTL with no explicit
  bound**: nothing stops a 45-min interval from silently reintroducing the
  window. The hard `>= 30 → exit 1` gate (D6) is the only safe default.

## File layout

| File | Action | Purpose |
|---|---|---|
| `scripts/external_kicker.py` | NEW | pure functions (D1-D6) + `tick()` orchestration + CLI |
| `scripts/test_external_kicker.py` | NEW | ~25 unit tests, tmp_path only, no spawns, no schtasks registration |

## Out of scope

- #43 ledger-signature drift detection / #44 state_anchor / #45 fired-predicate resume (sub-issues, separate PRs).
- Migrating `wire_up_settings.py --wire-up` to project level (follow-up; the kicker implements the correct path).
- Changing `heartbeat_loop_prompt.py` output (the kicker consumes it verbatim).
- Process-level pid fencing of live sessions (documented limitation, D1).
