# Proposal — tick() evaluates alive-but-stuck drift on fresh heartbeat (#79)

## Why

#43 shipped the **drift predicate** but never wired it into the actual tick
path. Today `tick()` returns immediately whenever the heartbeat is fresh:

- `should_kick()` implements the persistent-drift predicate (six-row
  escalation threshold `DRIFT_ESCALATE_ROWS` + fresh-worker exemption):
  scripts/external_kicker.py L279-L307.
- `tick()` returns immediately whenever the heartbeat is fresh:
  scripts/external_kicker.py L650-L685 — it NEVER calls `should_kick()`
  before returning.

Controlled reproduction (temporary workspace, six identical ledger
signatures + current `runs/.heartbeat.json`, production functions with
`dry_run=True`):

```
should_kick= True
kicker: skip - session alive (heartbeat fresh)
tick_rc= 0
kick_receipt_exists= False
```

The system recognizes persistent alive-but-stuck drift, then DISCARDS that
fact on the actual tick path. A process that keeps touching its heartbeat
while its state signature stays frozen can remain stuck indefinitely —
exactly the long-horizon failure mode that looks healthy for hours/days
while making no progress (F2/F3 regime shift, wf_5c50b792-f7c).

## What Changes

- **`scripts/external_kicker.py`** `tick()` (the ONLY file changed in this
  issue):
  - In the fresh-heartbeat branch, evaluate the EXISTING drift predicate
    (`should_kick`) before returning.
  - When persistent drift is true and no fresh-worker exemption applies,
    fall through to the existing lock, hooks-ensure, dry-run, prompt, and
    receipt path used for recovery — same guarded path as a stale session —
    and emit a DISTINCT receipt (`"reason": "drift"` in
    `runs/.kicker-last.json`, plus a distinct log line).
  - The stale-session path, lock behavior, and no-real-spawn unit-test
    guarantees are untouched (regression-free).
- **`tests/test_drift_detection.py`**: add `tick()` integration tests
  alongside the existing pure-function tests:
  - fresh heartbeat + six frozen ledger rows → deterministic drift receipt
    in dry-run mode, same guarded recovery path as a stale session;
  - fresh heartbeat + progressing worker / fewer than six frozen rows /
    healed (cure-window) state → NO kick;
  - repeated ticks (both produce drift receipts, no crash, no lock deadlock);
  - fresh-worker race (worker status file lands while drift persists → skip);
  - stale-session path regression (existing `test_kick_stages_resume_prompt`
    behavior unchanged).

Not in scope: no new signature logic, no second drift definition — reuse
`should_kick()` verbatim. No change to `lib_kunglao.py`, `convergence_check.py`,
hooks, or the real workspace. No change to the drift-detection constants
(`ROTATION_WINDOW = 3`, `DRIFT_ESCALATE_ROWS = 6`, `WORKER_PROGRESS_MINUTES = 20`).

## Capabilities

### Added Capabilities

- `tick-drift-recovery`: the external kicker now recovers alive-but-stuck
  sessions (fresh heartbeat + persistent frozen ledger signature) through
  the same guarded recovery path as dead sessions, with a distinct
  `reason: drift` receipt — closing the #43 wiring gap.

## Impact

- `scripts/external_kicker.py`: `tick()` grows a drift branch (~15 lines)
  inside the fresh-heartbeat skip; receipt records gain an optional
  `reason` key for drift kicks only (stale-session receipts byte-identical).
- `tests/test_drift_detection.py`: +7 integration tests (~120 lines).
- Suite impact: `tests/` and `scripts/` suites stay green apart from the 6
  pre-existing failures (SKILL.md 510>500, 4x test_convergence_completeness,
  test_acceptance meta-gate — all pre-existing, not touched by this change).
- Related: #39 (external-kicker skeleton), #43 (drift predicate, parent of
  this issue), #44 (state_anchor — the cure this recovery gives a window
  to), #45 (fired-predicate resume prompt, used by the shared kick path).
