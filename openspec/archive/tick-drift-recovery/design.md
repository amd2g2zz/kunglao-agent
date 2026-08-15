# Design — tick() evaluates alive-but-stuck drift on fresh heartbeat (#79)

## Design Decisions

### D1. Single drift definition: `should_kick()` is the one predicate

#43 deliberately shipped the drift decision as a standalone pure function:
`external_kicker.should_kick(workspace)` = `drift_detected(ws) AND
signature_rotation(ws) >= DRIFT_ESCALATE_ROWS (6)`, where
`drift_detected` = rotation >= ROTATION_WINDOW (3) AND NOT
`workers_progressing` (fresh-mtime in-progress status file = the legal
SATURATED wait). This issue does NOT add a second drift definition or
reimplement signature logic — `tick()` evaluates the SAME `should_kick()`
that the pure tests already prove. The only production change is *where*
the predicate is called.

### D2. Drift branch placement: inside the fresh-heartbeat skip, before return

Current `tick()` flow (scripts/external_kicker.py L662-L737):

```
validate_interval -> acquire_kick_lock -> heartbeat fresh? -> skip (return 0)
-> has_fresh_workers? -> skip -> hooks ensure -> prompt -> kick -> receipt
```

New flow — the fresh-heartbeat branch evaluates the drift predicate before
returning:

```
validate_interval -> acquire_kick_lock
-> heartbeat fresh?
     -> should_kick(ws)?  (NEW)
          -> True  (drift): fall through to the recovery path below
          -> False: skip "session alive" (return 0, unchanged)
-> has_fresh_workers? -> skip
-> hooks ensure -> prompt -> kick -> receipt (reason="drift" if drift)
```

Falling through (rather than duplicating the kick body) guarantees the
drift path reaches the SAME guarded recovery path as a stale session:
same lock (already held by this tick), same project-hooks ensure, same
`build_resume_prompt` staging to `runs/.kicker-prompt.txt`, same
`dry_run` semantics (spawn vs. would-spawn), same `runs/.kicker-last.json`
receipt writer. The `finally: release_kick_lock` is shared, so lock
semantics are identical for both paths.

### D3. DRIFT_KICK receipt: optional `reason` key, stale receipts untouched

The issue requires "a distinct DRIFT_KICK/replan receipt". The single
sanctioned receipt is `runs/.kicker-last.json`; the drift kick adds one
key:

```
{"kick_ts": "...", "prompt_file": "...", "pid": 0, "reason": "drift"}
```

- Stale-session receipts keep the EXACT current shape
  `{kick_ts, prompt_file, pid}` — no `reason` key — satisfying the
  acceptance criterion "the stale-session path ... does not regress"
  (receipt consumers and existing tests see byte-identical output).
- The spawn-failure record (pid=-1) also carries `reason: "drift"` when
  the kick was drift-initiated, so operators can classify failures.
- Log line distinguishes the path: a `kicker: DRIFT-KICK — session alive
  but stuck ...` line precedes the shared `kicker: KICK ...` line.

### D4. Fresh-worker race: handled by the predicate + the existing guard

The race "a worker status file lands while drift persists" is closed twice,
consistently:

1. `should_kick()` embeds `workers_progressing` (mtime < 20 min) — a fresh
   in-progress file makes `drift_detected` False → no drift kick. This is
   the deterministic, testable decision.
2. The recovery path's existing `has_fresh_workers(runs, FRESH_WORKER_MINUTES)`
   check re-verifies at kick time — a worker that lands between the
   predicate evaluation and the kick (real-time race, not reachable in the
   single-threaded tests) still skips before spawning.

Both use the same freshness constant (20 min) and the same last-status-line
parsing, so they cannot disagree about what "moving" means.

### D5. Repeated ticks: re-evaluate every tick, lock released each round

The lock is acquired at tick start and released in `finally` — consecutive
ticks are independent rounds. A drift kick in dry-run mode does not spawn a
real session, so the heartbeat stays fresh and the ledger stays frozen: the
next tick re-evaluates the same state and produces the same drift receipt —
deterministic, no state coupling between rounds. In non-dry-run, the fresh
session refreshes `last_tick_ts` (renew tick) within the tick interval, so
the drift heals (heartbeat signals refresh) and subsequent ticks skip —
recovery converges to one kick per drift episode in production.

## Rejected Alternatives

### R1. Separate receipt file for drift kicks (e.g. `runs/.kicker-drift.json`)

Rejected: two receipt sources split the recovery audit trail and require
new cleanup/rotation rules. The single `.kicker-last.json` with a `reason`
discriminator keeps one consumer contract; "distinct" is satisfied by the
reason key + distinct log line. The stale path stays byte-identical, which
a separate file would NOT provide for free either (it would duplicate
state).

### R2. Re-implement the drift predicate inline in `tick()`

Rejected by the issue text: "Do NOT reimplement the signature logic or
introduce a second drift definition." `should_kick()` is already proven by
the #43 pure tests; an inline copy would be a second definition that can
drift out of sync with the documented cure window.

### R3. Add `reason: "stale"` to stale-session receipts too

Rejected: the acceptance criterion is "the stale-session path ... does not
regress" — a shape change to the stale receipt is a regression risk for
existing consumers/tests with zero benefit (the receipt already means
"kicked for a stale session" in that path). The `reason` key exists ONLY
on drift receipts, making the drift kick unambiguous by its presence.
