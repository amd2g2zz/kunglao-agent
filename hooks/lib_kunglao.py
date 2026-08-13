#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_kunglao.py — kunglao-agent shared library (Phase 2 E2.4).

Consolidates duplicated implementations across hooks:
  - workspace resolution (dispatch_gate._resolve_workspace / worker_pulse._resolve_workspace / worker_budget._resolve_paths)
  - DISPATCH_RE (dispatch_gate + worker_pulse)
  - activation check (dispatch_gate hand-written JSON+expiry vs worker_pulse is_active_strict)

E2.4 criteria: lib singleton behavior-equivalent to each original
implementation — same fixture output, byte-identical diff.

Design: single module imported by all hooks; pure functions, no state.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---- dispatch prefix regex (single source) ----
DISPATCH_RE = re.compile(
    r"\[T(\d)\s+tools=([^\]]+)\]\s+claim\s+(C-\d+)"
)


def parse_dispatch(text: str) -> tuple[int, list[str], str | None]:
    """Parse '[T<N> tools=a,b] claim C-NN' -> (tier, tools, claim_id). (0, [], None) if absent."""
    m = DISPATCH_RE.search(text)
    if not m:
        return (0, [], None)
    tier = int(m.group(1))
    tools = [t.strip() for t in m.group(2).split(",") if t.strip()]
    return (tier, tools, m.group(3))


# ---- workspace resolution (single source) ----
def resolve_workspace(payload: dict) -> Path | None:
    """Resolve the kunglao-agent workspace from a hook payload.

    Candidates (first match wins):
      1. payload['workspace'] if it has analysis_state.txt
      2. payload['cwd'] (and its child 'malware-analysis-workspace')
      3. cwd if it has analysis_state.txt
    Returns None if no candidate resolves.
    """
    def _is_ws(p: Path) -> bool:
        return (p / "analysis_state.txt").exists()

    cands: list[Path] = []
    for key in ("workspace", "cwd"):
        v = payload.get(key)
        if v:
            p = Path(v)
            cands.extend([p, p / "malware-analysis-workspace"])
    cands.append(Path.cwd())
    for c in cands:
        if _is_ws(c):
            return c
    return None


# ---- activation check (single source) ----
def is_active(ws: Path, hook_name: str, ttl_minutes: int = 30) -> bool:
    """Check kunglao-agent activation with ONE semantic (strict).

    Returns True only if: .hook_state.json exists AND expires_at is in the
    future AND hook_name is in the active set (or set is empty = all active).
    Missing state file = NOT active (strict default; legacy permissive
    default is removed).
    """
    state_file = ws / ".hook_state.json"
    if not state_file.exists():
        return False
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return False
    expires = state.get("expires_at", "")
    try:
        exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if datetime.now(timezone.utc) >= exp:
        return False
    active = state.get("active", {})
    if isinstance(active, dict):
        hook_set = active.get("hooks", [])
    else:
        hook_set = active
    return hook_name in hook_set or not hook_set


# ---- active-worker scan (single source of truth, issue #37) ----
# Byte-for-byte mirror of scripts/convergence_check.py:_scan_active_workers so the
# worker_budget gate and the convergence decision share ONE count source. Do NOT
# let these drift — a gate/decision count mismatch is the exact double-truth-source
# bug issue #37 fixes (gate read the state cache while convergence read status files).

STUCK_MINUTES = 20  # mirror scripts/convergence_check.py


def scan_active_workers(workspace: Path) -> tuple[int, list]:
    """Count active + stuck workers from runs/worker-status-*.md.

    Active = a worker whose LAST ``status:`` line is ``in-progress``. Scans the
    workspace ``runs/`` dir plus every ``.wt-*/ with .kunglao-worktree marker``
    worktree dir (v1.9.13 worktree isolation: worker state lives in each worker's
    own worktree, not the main tree). Stuck = active files older than
    STUCK_MINUTES. OSError on glob/read/stat skips that file.

    Byte-for-byte mirror of scripts/convergence_check.py:_scan_active_workers.
    """
    status_line = re.compile(r"status:\s*(\S+)")
    dirs = [workspace / "runs"]
    try:
        for wt in workspace.parent.glob(".wt-*/.kunglao-worktree"):
            runs_dir = wt.parent / "malware-analysis-workspace" / "runs"
            if runs_dir.exists():
                dirs.append(runs_dir)
    except OSError:
        pass
    active = 0
    stuck = []
    cutoff = timedelta(minutes=STUCK_MINUTES)
    now = datetime.now(timezone.utc)
    for runs in dirs:
        if not runs.exists():
            continue
        for p in runs.glob("worker-status-*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # last status line decides activity
            last_status = None
            for line in text.splitlines():
                m = status_line.search(line)
                if m:
                    last_status = m.group(1).lower()
            if last_status != "in-progress":
                continue
            active += 1
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if (now - mtime) > cutoff:
                stuck.append({"worker": p.stem, "age_min": int((now - mtime).total_seconds() // 60)})
    return active, stuck
