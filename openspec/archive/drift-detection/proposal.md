# Proposal — drift detection (alive-but-stuck) (#43)

## Why

#39's `external_kicker` detects **dead** sessions (heartbeat stale beyond
`stale_minutes`, both signals) and recovers with a fresh session. There is a
second, invisible regime it cannot see: **alive-but-stuck** — the session's
heartbeat stays fresh (`activity_ts` written by the heartbeat_touch hook on
every tool call), the ledger keeps writing rows every loop iteration, but
state makes ZERO progress. Time-based detection ("no ledger row for 25 min")
never fires because the ledger is not stale — it is frozen in a loop of
identical snapshots.

Deep-research evidence (`wf_5c50b792-f7c`, `.claude/PRPs/research/long-horizon-agent-failure.md`):
- **F2**: LLM long-trajectory degradation is a qualitative *regime shift*,
  non-linear decay — a session can look perfectly healthy (fresh heartbeat)
  while already past the collapse threshold.
- **F3**: SED execution drift is step-local-invisible — "an agent can
  complete a task successfully while systematically violating constraints".

Both mean liveness signals (heartbeat, ledger writes) are **necessary but not
sufficient** evidence of progress. The missing signal is *state change*:
if the ledger's decision-relevant signature is identical for N consecutive
rows, the loop is spinning, not converging.

## What Changes

- **`scripts/lib_kunglao.py`** (new, scripts-side shared lib — same role as
  `hooks/lib_kunglao.py` for the hooks namespace):
  - `signature_rotation(ws) -> int`: reads the tail of
    `.convergence_ledger.jsonl`, builds signature tuples
    `(decision, open_ids, partial_count, active_workers, blockers, facts_total)`
    — **`ts` excluded** (and derivable `open_count`) — and counts the
    consecutive identical run ending at the last valid row.
  - `workers_progressing(ws) -> bool`: True when ANY in-progress
    `worker-status-*.md` (last `status:` line == `in-progress`, scanned in
    `workspace/runs` plus `.wt-*/malware-analysis-workspace/runs`, mirroring
    `convergence_check._scan_active_workers`) has mtime younger than
    `WORKER_PROGRESS_MINUTES` (20) — the legitimate SATURATED-wait exemption.
  - `drift_detected(ws) -> bool`: `rotation >= ROTATION_WINDOW (3)` AND NOT
    `workers_progressing`.
  - Tunable constants: `ROTATION_WINDOW = 3`, `DRIFT_ESCALATE_ROWS = 6`,
    `WORKER_PROGRESS_MINUTES = 20`.
- **`scripts/external_kicker.py`**: add the `should_kick` **drift branch**
  (the ONLY change to this file): kick only when drift persists
  `>= DRIFT_ESCALATE_ROWS (6)` — cure-first-before-recovery: the 3→6-row gap
  leaves a window for the #44 `state_anchor` hook to heal the drift without a
  fresh session. Function-level import of `lib_kunglao` (same lazy-import
  pattern as the existing `from heartbeat_loop_prompt import build_prompt` in
  `tick()`), so no top-level import section is touched — clean concurrent
  merge with #45.
- **`tests/test_drift_detection.py`** (new): synthetic-workspace tests, RED
  first.

Not in scope: wiring `should_kick` into `tick()` (deliberate — #44
`state_anchor` is the cure that must land first; recovery-on-drift wiring is
the final step of the #43→#44 sequence, see design D4). No change to
`hooks/lib_kunglao.py`, `convergence_check.py`, or the real workspace.

## Capabilities

### Added Capabilities

- `drift-detection`: detect the alive-but-stuck regime (fresh heartbeat +
  frozen ledger signature) that time-based dead-session detection cannot see,
  and escalate to a kick only after the drift persists beyond the cure
  window.

## Impact

- `scripts/lib_kunglao.py`: new module, ~120 lines (3 functions + 3
  constants + ledger/status-file helpers).
- `scripts/external_kicker.py`: +1 function (`should_kick`, ~20 lines, drift
  branch only — no other edit).
- `tests/test_drift_detection.py`: new, ~200 lines, ~18 tests.
- Suite impact (baseline measured at b401d89): `scripts/` 226 passed → 226+N
  passed; `tests/` 243 passed + 1 skipped + 6 pre-existing failures unchanged
  (SKILL.md 510>500, 4x test_convergence_completeness, test_acceptance
  meta-gate — all pre-existing, not touched by this change).
- Related: #39 (external-kicker skeleton, parent), #44 (state_anchor, the
  cure this detection gives a window to), #45 (fired-predicate resume,
  concurrent).
