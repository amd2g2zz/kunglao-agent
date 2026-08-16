# Design — stuck-worker-gate

## D1 — Mirror check_plan_drift for the backtrack gate
`check_backtrack_gate(paths)` runs `backtrack_gate.py <workspace>` via `_run_py`
(20s timeout, FAIL_OPEN — identical infrastructure to `check_plan_drift` and
`check_convergence_health` at worker_budget.py:71-112). rc map:

| backtrack_gate rc | meaning | check returns |
| --- | --- | --- |
| 0 | clean (no stuck workers, or stuck-but-valid-backtrack) | (True, "") |
| 1 | stuck worker(s) without a valid `## backtrack` block | (False, msg with "backtrack") |
| 2 | stuck >30m, decision != redispatch (stale un-actioned) | (False, msg with "escalate"/"redispatch") |
| None / other | subprocess failure or unknown rc | (True, "") FAIL_OPEN |

Inserted in `pre_check` checks list AFTER `('health', ...)` (line 728) so the
dispatch path mechanically rejects when a worker is stuck. This is the HARD
gate (REJECT rc=2 in pre_check).

Rejected alternative: calling `backtrack_gate.check()` directly via import.
The other two wired gates (plan_drift, convergence_health) deliberately use
the subprocess boundary so a script crash cannot take down the hook.
Mirroring that pattern keeps the FAIL_OPEN contract uniform.

## D2 — worker_pulse stale detection (soft, non-dispatch path)
`main()` currently returns 0 early when `not _was_dispatch(payload)` (line
171-172). Extension: on that path, scan `runs/worker-status-*.md` for
in-progress files whose mtime > STUCK_MIN (20min, mirrors backtrack_gate
default). If any, inject a soft `additionalContext` naming each stale worker
and its age. NEVER aborts (rc=0); the REJECT is worker_budget's job.

Rejected: running convergence_check on every PostToolUse (subprocess overhead
per Agent call). The direct mtime scan is cheap (one glob + stat per status
file) and targets exactly the stuck signal. convergence_check stuck_workers
already feeds the dispatch-complete pulse via `_build_pulse` flags; this
extends coverage to the non-dispatch path (a stuck worker that never
completes never triggers dispatch-complete).

## D3 — FAIL_OPEN contract (both pieces)
Missing workspace, missing script, subprocess timeout, unreadable status file
-> no false REJECT, no crash. A broken gate must not block dispatch; a broken
pulse must not abort. `check_backtrack_gate` fails open on `_run_py` returning
None or any rc outside {0,1,2}. `_check_stale_workers` returns '' on any
OSError or missing runs/ dir.

## D4 — Threshold
STUCK_MIN = 20 (module constant in worker_pulse, mirrors backtrack_gate
default `--stuck-min 20`). backtrack_gate itself is UNMODIFIED — this change
only wires it in.

## D5 — Status parsing (worker_pulse)
`STATUS_RE = re.compile(r"^\s*status\s*:\s*(\S+)", re.IGNORECASE | re.MULTILINE)`.
A worker is in-progress iff the LAST `status:` match (most recent state
wins, same convention as lib_kunglao.scan_active_workers and
backtrack_gate.parse_status) lowercased and `-`→`_` normalized equals
`in_progress`. This matches both `in-progress` and `in_progress` spellings.

## D6 — Test surface (RED -> GREEN)
Gate (`check_backtrack_gate`, monkeypatch `wb._run_py`):
- clean rc=0 -> (True, "").
- stuck rc=1 -> (False, "backtrack" in msg).
- stale rc=2 -> (False, "escalate" or "redispatch" in msg).
- failopen None -> (True, "").
- failopen no-workspace -> (True, "").
- failopen unknown rc -> (True, "").

Pulse (`_check_stale_workers`, temp workspace):
- stale: in-progress + mtime 25min -> non-empty, names the worker.
- fresh: in-progress + mtime 2min -> "".
- completed: status done + mtime 40min -> "" (not flagged).
- no runs/ dir -> "".

## D7 — Interaction with prior changes
- #37 (`active-workers-single-source`) made `check_workers_lt_3` read status
  files via `lib_kunglao.scan_active_workers`. `check_backtrack_gate` reuses
  `_run_py` + `_SKILL_ROOT` already in worker_budget; it does not read
  active_workers, so #37's refactor is orthogonal. Both gates compose in the
  checks list.
- v1.9.29 wired plan_drift + convergence_health with the same FAIL_OPEN
  subprocess pattern. This change is the same pattern applied to the third
  standalone gate, closing the built-but-not-wired gap for backtrack_gate.
