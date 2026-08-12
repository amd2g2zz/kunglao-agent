# Design — drift detection (#43)

## Design Decisions

### D1. Drift signal = ledger signature rotation, not time

The ledger row is the loop's self-report. A row that differs from the
previous one in any decision-relevant field IS progress (the loop changed
something); a row that does not is a no-op spin. Therefore the drift signal
is the length of the run of consecutive IDENTICAL signatures ending at the
tail of `.convergence_ledger.jsonl`.

Signature tuple = `(decision, open_ids, partial_count, active_workers,
blockers, facts_total)` — **`ts` excluded** (a fresh timestamp on an
identical snapshot is exactly the F2/F3 false-alive signal, not progress) and
`open_count` excluded (derivable as `len(open_ids)`; the real ledger carries
it but it cannot diverge from `open_ids`). The six fields are the
decision-relevant state of the convergence loop: what it decided, what is
open, what is partial, who is running, what is blocked, how many facts exist.

### D2. Rotation counting: bounded read, corrupt rows skipped, never raise

`signature_rotation(ws, window=None)`:

- Reads the last `window` lines of `.convergence_ledger.jsonl` with
  `errors="replace"` decoding; default window =
  `max(ROTATION_WINDOW, DRIFT_ESCALATE_ROWS)` = 6 — exactly the horizon all
  decisions compare against (rotation ≥ 3, rotation ≥ 6). A bounded read
  keeps the gate O(6) on a ledger that grows all day.
- A line that fails to parse (bad JSON, missing field, empty line, non-dict)
  is **skipped** — it can neither anchor nor break a run. "A corrupt ledger
  line never crashes the gate"; a snapshot we cannot read is not evidence of
  progress, so it must not mask a frozen signature either.
- Reference = signature of the last VALID row in the window. Count walks
  backward over valid rows while `signature == reference`; first valid
  difference stops the run.
- Missing ledger / empty ledger / no valid row → `0`.

Malformed handling rationale: skipping (vs. breaking the run) is the
recovery-bias choice consistent with #39's D1 ("the kicker repairs broken
states, it does not preserve them") — a corrupt line mid-run cannot hide the
drift, and each counted row is still genuinely identical to the reference
(the count never fabricates a signature).

### D3. `workers_progressing`: scan targets mirror `_scan_active_workers`, freshness flips the rule

The legitimate-exemption problem: with the worker pool SATURATED the
orchestrator correctly waits — the ledger signature can freeze for longer
than `ROTATION_WINDOW` while three workers grind. Kicking that session would
destroy real work. The mechanical evidence of worker movement is the status
file mtime of an IN-PROGRESS worker.

- Scan targets mirror `convergence_check._scan_active_workers` exactly:
  `workspace/runs` PLUS `workspace.parent.glob(".wt-*/malware-analysis-workspace/runs")`
  (v1.9.13 worktree isolation: worker state lives in each worker's git
  worktree, not the main tree). Worker state LOCATION is single-sourced by
  that function; this helper must not invent a second location rule.
- Activity rule identical: the LAST `status:\s*(\S+)` line decides;
  lowercased; only `in-progress` counts. A `done`/`blocked`/stale file never
  exempts.
- Freshness rule FLIPS the stuck rule: `_scan_active_workers` flags mtime
  OLDER than `STUCK_MINUTES` (20) as stuck; `workers_progressing` returns
  True when mtime is YOUNGER than `WORKER_PROGRESS_MINUTES` (20) — the same
  constant value, the complement predicate. Any fresh in-progress status
  file → True (early return; one is enough).
- `now` is injectable (defaults to `datetime.now(timezone.utc)`) so tests
  are deterministic without sleeps — the `session_is_dead(hb, NOW, 10)`
  pattern from #39.

### D4. `should_kick` drift branch: escalate only past the cure window

`should_kick(workspace) -> bool` (new function in `external_kicker.py`, the
file's ONLY change in this issue):

```
drift branch:  drift_detected(ws) AND signature_rotation(ws) >= DRIFT_ESCALATE_ROWS
```

- `drift_detected` requires rotation ≥ `ROTATION_WINDOW` (3) — the
  alive-but-stuck regime is DETECTED at 3 frozen rows.
- Escalation to a kick requires rotation ≥ `DRIFT_ESCALATE_ROWS` (6). The
  3→6-row gap is the **cure-first window**: #44's `state_anchor` hook is the
  cure (re-anchor the dying session's state on PostToolUse); recovery (kick
  to a fresh session) must not preempt the cure. A drift that heals inside
  the window is never kicked; a drift that survives 6 rows is recovered.
- A progressing worker exempts at every level (`workers_progressing` is part
  of `drift_detected`) — never kick a session whose workers move.
- Import: function-level `from lib_kunglao import ...` — the file's existing
  lazy-import pattern (`from heartbeat_loop_prompt import build_prompt` in
  `tick()`). This keeps the top-level import section untouched, so the
  concurrent #45 edit (same file, `build_resume_prompt`) merges cleanly.
- WIRING INTO `tick()` IS DEFERRED on purpose: `tick()` currently skips any
  alive session (`session_is_dead == False → skip`); flipping that skip to
  honor the drift branch is the final integration step and belongs AFTER
  #44 lands (cure exists before recovery is wired). This issue ships the
  correct, tested decision function; #44 integrates it. Documented in the
  PR body.

### R1 (rejected): re-implement drift detection inside `tick()` inline

Rejected: `tick()` is #39's file, #45 is concurrently editing it, and the
drift decision needs to be independently testable. The pure decision
function in `external_kicker.py` + pure helpers in `lib_kunglao.py` is the
smallest, merge-safe, test-first surface.

### R2 (rejected): put the helpers in `hooks/lib_kunglao.py` next to `scan_active_workers`

Rejected: the hooks namespace and the scripts namespace are separate
sys.path domains (`hooks/` is not on the path when `external_kicker.py` runs
standalone as `python scripts/external_kicker.py <ws>`). The repo's existing
convention is byte-for-byte MIRRORS across the boundary (hooks/lib_kunglao ↔
convergence_check), not cross-imports. `scripts/lib_kunglao.py` mirrors the
scan-location rule; the #37 mirror contract between hooks and scripts is
untouched. (Issue #43 text names `scripts/lib_kunglao.py` explicitly.)

### R3 (rejected): time-gap detection instead of signature rotation

Rejected — this is the very blind spot the issue fixes. F2/F3: the ledger
writes on schedule while the state never changes; "last row 25 min ago" is
False while drift is True. Only state-signature comparison sees the
frozen-but-alive loop.
