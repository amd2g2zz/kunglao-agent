# Design — issue 1086 S18 (wake gate wiring)

## D1 The wrapper is a thin, loud consumer — not a second gate

`scripts/heartbeat_wake_gate.py` owns NO verdict logic of its own. It runs
`heartbeat_tick.py <ws> --origin cron --wake-gate` as a subprocess (the gate
stays the single verdict authority, and `heartbeat_tick.py` stays the gate
host — a later monitor-removal slice must keep it) and maps the rc:

| gate rc | wrapper outcome | action | wrapper rc |
|---|---|---|---|
| 0 + `QUIET:` marker | quiet | inject nothing; no receipt; no output | 0 |
| 3 + `WAKE:` marker | wake | inject the loop prompt exactly once | 3 |
| 2 | stop | mandatory stop (#634), never inject | 2 |
| anything else / crash / timeout / marker mismatch | fault | LOUD + inject (fail toward waking) | 1 |

The marker cross-check is load-bearing: an rc-0 pass without the `QUIET:`
marker means the tick did not run in gate mode, and trusting it as quiet is
exactly the never-wakes failure. `classify()` refuses it as a fault.

Faults fail TOWARD waking (the session is handed the prompt anyway, rc stays
1). That mirrors the watchdog's own semantics — `step-failure` is a wake
reason, so a broken mechanical step wakes the session to repair it — and it
is the direction #1086 demands: silence on a fault would mean the system never
wakes, which is worse than waking once too often.

## D2 Delivery reuses the two faces that already own it

- **Payload**: `heartbeat_loop_prompt.build_prompt(ws)` — the emitter, never
  a re-embedded copy (#598 / the loop_scheduler precedent). The staged file
  `runs/.wake-gate-prompt.txt` is byte-identical to the emitter's output.
- **Turn**: the external kicker's D4 shape — `external_kicker.build_kick_command`
  (the argv single source) + a detached `claude -p` fed the prompt on stdin,
  cross-platform detach flags mirrored (Windows
  `CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS`, POSIX `start_new_session`).
- **Liveness**: `external_kicker.session_is_dead` (the #39 predicate, single
  source). A live session owns the wake: the wrapper stages the prompt and
  does NOT spawn — two orchestrators on one workspace is the concurrency
  defect #1042 exists to prevent. A dead/absent session gets the spawn.

New state is two files in the kicker's naming family:
`runs/.wake-gate-prompt.txt` (the staged payload) and
`runs/.wake-gate-receipt.json` (one row per non-quiet pass: outcome, gate rc,
delivery, ts). `runs/.wake-gate.json` stays the tick's quiet-streak state —
no shared file with the gate.

## D3 Registration is strings only (D5 precedent), and the cron keeps its job

`--print-registration` prints the crontab line and the schtasks args; nothing
installs anything. The emitted line carries `--wake-gate` — the acceptance
greps for it, and the wrapper REFUSES a pass without the flag (rc 2) so a
hand-trimmed registration fails fast instead of silently mis-registering.
The interval is refused at/over the 30-min activation TTL (the kicker's D6
bound; the value is single-sourced in `liveness_policy`).

The durable /loop cron is NOT deleted (#685 D5): it stays as the armed
watchdog and the `loop_registered` marker's carrier; the gate line is the
scheduler. SKILL.md keeps the CronCreate wording for the watchdog and adds
the gate line above it.

## D4 Contract changes are additive; the WAKE discipline is untouched

- SKILL.md activation block: one new line (the wrapper registration); the
  emitter line is relabeled (payload + watchdog), not removed. SKILL.md
  forbids issue numbers and self-narrative — the wording avoids them.
- The loop prompt body's step 0 gains `--wake-gate` and a QUIET branch that
  ends the turn; the pinned markers (`kunglao-agent heartbeat`,
  `--heartbeat-on`, `--loop-registered`, `--origin cron`, `watchdog`,
  `no-op`) are preserved; `idle fault`/`self-recover` stay out of the body.
- SKILL.md 1.4: the idle-fault sentence and the THINK EMPTY-forbidden rule
  are scoped to a WAKEN tick with an explicit QUIET carve-out; the WAKE
  sentence is verbatim.
- `--verify` guidance and REARM_ADVICE keep the words the existing pins
  require (`CronCreate`, `loop_registered`, `loop 5m`) and add the
  gate-first step.

## D5 Boundaries with the sibling slices

- S19 (event bus unify): untouched — the wrapper consumes the tick's verdict
  only; no `scheduler_events` knowledge here.
- S20 (gate-pass mechanisms): untouched — the wrapper runs the tick as-is;
  whether cheap mechanisms run in the zero-LLM pass is the tick's business.
- S21 (wake decision wiring): the wrapper's WAKE branch is one `inject()`
  call behind a seam — `intelligent_scheduling` slots in before it without
  touching the verdict map.
