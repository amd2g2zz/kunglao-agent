# Wire backtrack_gate into dispatch + extend worker_pulse stale detection

## Summary
`scripts/backtrack_gate.py` (built + tested earlier; detects workers stuck
>20min without progress, rc 0/1/2) is NOT wired into the dispatch path —
`worker_budget.pre_check`'s 10-check list never calls it. C-207 stuck for
71min before manual discovery. This change wires backtrack_gate as the 11th
pre_check gate (mirror `check_plan_drift`: subprocess + FAIL_OPEN + rc map)
and extends `worker_pulse` to surface mtime-stale workers on ANY Agent
PostToolUse (not just dispatch completion), cutting stuck-worker truncation
from 71min to 20min mechanical enforcement.

## Motivation
- **C-207** stuck 71min (discovered manually). backtrack_gate existed but was
  unwired — built-but-not-connected, the same class of defect that R3 of the
  research-tree alignment targets.
- **Unattended operation**: a stuck worker that never completes never triggers
  worker_pulse today (it only fires on dispatch completion). Soft stale
  detection on every Agent PostToolUse catches stuck workers even when they
  never finish, so the orchestrator is nudged to intervene or force a
  `## backtrack` block.

## What Changes
- `hooks/worker_budget.py`: add `check_backtrack_gate(paths)` (mirror
  `check_plan_drift` FAIL_OPEN; backtrack_gate rc 1/2 -> REJECT) and wire it
  as the 11th check after `('health', ...)`.
- `hooks/worker_pulse.py`: add `_check_stale_workers(ws)` (scan
  `runs/worker-status-*.md` for in-progress + mtime > STUCK_MIN); call it on
  the non-dispatch PostToolUse path (soft additionalContext, never aborts).
- `scripts/test_stuck_gate.py` (new): RED tests for the gate + pulse stale
  detection.

## Scope
- **In**: wire the existing backtrack_gate (NO backtrack_gate.py edit) +
  worker_pulse stale extension + tests.
- **Out**: changing backtrack_gate thresholds/logic; auto-revival. The hard
  REJECT is worker_budget's job; worker_pulse stays a soft heuristic.

## Relationship to prior work
- `backtrack_gate.py` was delivered as a standalone gate with a CLI. This
  change is the wiring step (R3: built-but-not-wired fix), analogous to how
  v1.9.29 wired plan_drift + convergence_health into pre_check.
- `active-workers-single-source` (#37) refactored scan_active_workers into a
  shared host; `check_backtrack_gate` is orthogonal — it does not read
  active_workers, only the backtrack_gate subprocess rc.
