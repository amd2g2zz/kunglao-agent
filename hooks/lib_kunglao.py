#!/usr/bin/env python3
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
from datetime import datetime, timezone
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
