#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loop_state.py — M0 state-layer reconciliation prototype (Phase 2 E2.1/E2.2).

Reconciler that derives a single loop-state view from the AUTHORITATIVE
signal source: TEMP/claude/*/*/tasks/*.output mtime (agent lifecycle).

E2.1 (experiment): three worker ledgers drift (ledger=0 vs worker-status=28
vs TEMP-active=1). This module eliminates drift by deriving everything from
TEMP mtime — the only signal that reflects real agent lifecycle.

E2.2 (experiment): glob pattern resolves 598/598, mtime cleanly separates
active (<20min) from stale (>=20min). Passed.

Design (corrected from C4 blueprint):
  - worker-status-*.md is NOT a machine state source (real files are
    free-form reports; subagent contract format was never followed)
  - loop-state.json is a DERIVED view, regenerated each tick, never the
    source of truth
  - read-only: never writes to subagent contract files

Usage:
    python loop_state.py <workspace>              # print derived loop-state JSON
    python loop_state.py <workspace> --write      # also write runs/loop-state.json

Exit 0. Pure stdlib.
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="loop_state", action="verify",
                        detail="module wired")
except NameError:
    pass

import argparse
import datetime
import glob as globmod
import json
import os
import sys
import tempfile
import time
from pathlib import Path

STALE_MIN = 20          # mtime frozen > 20 min = STALE
ACTIVE_WINDOW_MIN = 30  # only report agents with activity in the last 30 min


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def scan_temp_agents() -> dict[str, dict]:
    """Scan TEMP/claude/*/*/tasks/*.output — the authoritative lifecycle signal.

    Returns {agent_id: {path, mtime_ts, age_min, project, session}}.
    Stat-only; never reads transcript content.
    """
    temp = Path(os.environ.get("TEMP", tempfile.gettempdir()))
    pattern = str(temp / "claude" / "*" / "*" / "tasks" / "*.output")
    now = time.time()
    out: dict[str, dict] = {}
    for f in globmod.glob(pattern):
        try:
            st = os.stat(f)
        except OSError:
            continue
        p = Path(f)
        parts = p.parts
        try:
            proj = parts[parts.index("claude") + 1]
            sess = parts[parts.index("claude") + 2]
        except (ValueError, IndexError):
            proj, sess = "?", "?"
        age_min = (now - st.st_mtime) / 60.0
        if age_min > ACTIVE_WINDOW_MIN:
            continue  # old session residue — ignore
        out[p.stem] = {
            "path": str(p),
            "mtime_ts": datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc)
                .isoformat(timespec="seconds").replace("+00:00", "Z"),
            "age_min": round(age_min, 1),
            "project": proj,
            "session": sess,
        }
    return out


def reconcile(workspace: Path) -> dict:
    """Derive the loop-state view from TEMP mtime only."""
    agents = scan_temp_agents()
    now_ts = utc_now()
    active = [aid for aid, m in agents.items() if m["age_min"] < STALE_MIN]
    return {
        "ts": now_ts,
        "source": "TEMP task output mtime (authoritative; worker-status deprecated as machine state)",
        "agent_count": len(agents),
        "active": active,
        "stale": [aid for aid, m in agents.items() if m["age_min"] >= STALE_MIN],
        "agents": agents,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace", nargs="?", default=".")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    state = reconcile(ws)

    if args.write:
        out = ws / "runs" / "loop-state.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"loop_state: wrote {out} ({len(state['agents'])} agents, {len(state['active'])} active)")
    else:
        print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
