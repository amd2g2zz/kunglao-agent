# External Kicker — OS-level dead-session recovery (#39)

## Why

The heartbeat/loop depends on a living Claude Code session. When the session
dies (crash, kill, logout, VM sleep), nothing starts a replacement — `last_tick_ts`
goes stale, the 30-min activation TTL expires, the mechanical gates in
worker_budget.py silently close, and dispatch is blocked until a HUMAN starts
a new session (T1 obs 4, 2026-08-05). Recovery must not depend on presence.

Root-cause finding (2026-08-11, 坑 7): `wire_up_settings.py:20` writes the
hooks to the **user-level** `~/.claude/settings.json`, but the 6 hooks that
actually fire live in the **project-level** `.claude/settings.json` of the
workspace parent (gitignored, carries `env` secrets + `mcpServers` +
`block_malware_exec`). `--wire-up` has therefore been repairing the wrong
file — the T1 zombie root cause. A recovery kicker MUST re-register hooks at
the project level while preserving the `env` segment byte-for-byte.

Also: any recovery mechanism has a silent-gate window unless its tick
interval is strictly below the 30-min activation TTL — between TTL expiry and
the next tick, hooks sleep and nothing re-awakens them.

## What Changes

- **`scripts/external_kicker.py`** (new): OS-level every-tick launcher
  (Windows `schtasks /sc minute`, POSIX crontab line). Each tick:
  1. **Competition gate (idempotent)**: atomic lock file
     `runs/.kicker.lock` (O_EXCL; lock younger than the tick interval skips —
     a recent kick already ran); skip when the heartbeat proves a live
     session; skip when fresh in-progress worker status files exist (a
     session is mid-dispatch).
  2. **Dead-session detection** (pure function): session is dead when
     `runs/.heartbeat.json` is missing OR both `last_tick_ts` and
     `activity_ts` are older than the stale threshold (default 10 min).
     `activity_ts` is refreshed mechanically by the heartbeat_touch hook on
     every tool call; `last_tick_ts` by the loop's renew tick. Both stale =
     no session alive.
  3. **Project-level hooks re-registration** (pure function on a settings
     dict): ensure the 5 kunglao hook entries (PreToolUse worker_budget +
     dispatch_gate on Agent, heartbeat_touch on Bash; PostToolUse
     worker_budget + worker_pulse on Agent) exist in the **project**
     settings file (`<workspace-parent>/.claude/settings.json`), preserving
     EVERY other key — `env` (secrets), `mcpServers`, `permissions`, other
     matchers' hook entries. Written atomically (tmp→replace) only when
     changed. Never touches user-level settings (the wire-up bug).
  4. **Kick**: build the fresh-session prompt from
     `heartbeat_loop_prompt.build_prompt(ws)` (verbatim), write it to
     `runs/.kicker-prompt.txt`, and spawn `claude -p` detached with
     cwd=workspace (prompt delivered via stdin). Record `runs/.kicker-last.json`.
- **Interval enforcement**: the tick interval MUST be < 30 min (activation
  TTL); the CLI rejects `--tick-interval-min >= 30` with exit 1 (default 15).
- **schtasks/cron construction** is pure string building — the kicker never
  registers a task itself; a manual one-time `schtasks /create` (or crontab)
  step wires it.

## Capabilities

### New Capabilities

- `external-kicker`: OS-level dead-session detection + fresh-session kick +
  project-level hooks re-registration (env-preserving) + idempotent session
  competition. Complements #38 (stuck gate survives restart: the kicker
  restarts the session, #38 keeps the gate released across the restart).

## Impact

- `scripts/external_kicker.py`: new (~330 lines, pure stdlib).
- `scripts/test_external_kicker.py`: new (~25 tests).
- `wire_up_settings.py`: NOT touched in this change (its user-level bug is
  documented here and the kicker implements the correct project-level path;
  migrating --wire-up is a follow-up).
- Behavior change: dead sessions now self-recover without human presence;
  project-level hooks self-heal every tick with env secrets preserved.
- NOT in scope: #43 ledger-signature drift detection, #44 state_anchor hook,
  #45 fired-predicate resume prompt (separate sub-issues), migrating
  --wire-up, changing the loop prompt itself.
