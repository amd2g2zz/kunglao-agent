#!/usr/bin/env python3
"""lib_kunglao.py — scripts-side shared library for kunglao-agent (#43).

Drift detection (alive-but-stuck): the session's heartbeat stays fresh
(heartbeat_touch hook on every tool call) and the ledger keeps writing rows,
but state makes ZERO progress — a frozen loop. Time-based dead-session
detection (external_kicker.session_is_dead) cannot see it (deep-research
F2/F3, wf_5c50b792-f7c); ledger SIGNATURE ROTATION can: if the
decision-relevant signature is identical for N consecutive rows, the loop is
spinning, not converging.

Design (openspec/changes/drift-detection/design.md D1-D3):
  D1 signature = (decision, open_ids, partial_count, active_workers,
     blockers, facts_total) — ts excluded (a fresh timestamp on an identical
     snapshot is the F2/F3 false-alive signal, not progress), open_count
     excluded (derivable as len(open_ids)).
  D2 rotation counting: bounded tail read (window tracks the thresholds),
     corrupt rows skipped — a corrupt ledger line never crashes the gate.
  D3 workers_progressing: scan targets mirror
     convergence_check._scan_active_workers (main runs/ + .wt-*/ worktree
     runs/, last `status:` line decides); freshness flips the stuck rule.

Sibling of hooks/lib_kunglao.py — the scripts namespace and the hooks
namespace are separate sys.path domains (each script runs with its own
directory at sys.path[0]); the repo convention is byte-for-byte mirrors
across the boundary, not cross-imports.

Pure stdlib. Pure functions, no state.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---- drift thresholds (issue #43, tunable) ----
ROTATION_WINDOW = 3            # consecutive identical signatures = drift detected
DRIFT_ESCALATE_ROWS = 6        # persistent drift = escalate to a kick
WORKER_PROGRESS_MINUTES = 20   # in-progress status file younger than this = moving

LEDGER_FILE = ".convergence_ledger.jsonl"

# D1: decision-relevant fields — ts excluded (false-alive), open_count
# excluded (derivable as len(open_ids)).
_SIGNATURE_FIELDS = ("decision", "open_ids", "partial_count",
                     "active_workers", "blockers", "facts_total")

_STATUS_RE = re.compile(r"status:\s*(\S+)")


def _tail_signatures(ws: Path, window: int) -> list[tuple]:
    """Last `window` valid signature tuples, oldest-first; malformed rows skipped.

    errors="replace" decoding + per-row parse guard: a corrupt ledger line
    can neither crash the gate nor anchor a run (D2). Missing/empty ledger →
    [].
    """
    path = Path(ws) / LEDGER_FILE
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    sigs: list[tuple] = []
    for line in lines[-window:]:
        try:
            row = json.loads(line)
            sig = tuple(row.get(k) for k in _SIGNATURE_FIELDS)
        except (ValueError, AttributeError, TypeError):
            continue
        if any(v is None for v in sig):
            continue
        sigs.append(sig)
    return sigs


def signature_rotation(ws, window: int | None = None) -> int:
    """Consecutive identical ledger signatures ending at the tail (D1/D2).

    Reads the last `window` rows (default max(ROTATION_WINDOW,
    DRIFT_ESCALATE_ROWS) — exactly the horizon all decisions compare
    against), builds signature tuples, and counts the run of rows equal to
    the last VALID row's signature walking backwards. Malformed rows are
    skipped; 0 when there is no valid row to anchor the run.
    """
    n = window if window is not None else max(ROTATION_WINDOW, DRIFT_ESCALATE_ROWS)
    sigs = _tail_signatures(Path(ws), n)
    if not sigs:
        return 0
    ref = sigs[-1]
    count = 0
    for s in reversed(sigs):
        if s == ref:
            count += 1
        else:
            break
    return count


def workers_progressing(ws, now: datetime | None = None,
                        fresh_minutes: int = WORKER_PROGRESS_MINUTES) -> bool:
    """True when ANY in-progress worker status file is younger than fresh_minutes.

    The legitimate-SATURATED exemption: with the worker pool full the
    orchestrator correctly waits — the ledger signature can freeze longer
    than ROTATION_WINDOW while workers grind. A freshly-written in-progress
    status file is mechanical evidence of movement (D3).

    Scan targets mirror convergence_check._scan_active_workers: workspace
    runs/ PLUS every .wt-*/malware-analysis-workspace/runs worktree dir
    (v1.9.13 worktree isolation); the LAST `status:` line decides (lowercased);
    only `in-progress` counts; mtime YOUNGER than fresh_minutes. OSError on
    glob/read/stat skips that file.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(minutes=fresh_minutes)
    ws = Path(ws)
    dirs = [ws / "runs"]
    try:
        for wt in ws.parent.glob(".wt-*/malware-analysis-workspace/runs"):
            dirs.append(wt)
    except OSError:
        pass
    for runs in dirs:
        if not runs.exists():
            continue
        try:
            files = list(runs.glob("worker-status-*.md"))
        except OSError:
            continue
        for p in files:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            last_status = None
            for line in text.splitlines():
                m = _STATUS_RE.search(line)
                if m:
                    last_status = m.group(1).lower()
            if last_status != "in-progress":
                continue
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if mtime > cutoff:
                return True
    return False


def drift_detected(ws) -> bool:
    """Alive-but-stuck: rotation >= ROTATION_WINDOW AND no worker movement.

    The regime time-based detection cannot see: heartbeat fresh, ledger
    writing every loop, zero state progress (F2/F3, wf_5c50b792-f7c).
    """
    return signature_rotation(ws) >= ROTATION_WINDOW and not workers_progressing(ws)
