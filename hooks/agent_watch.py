#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.9.39 — agent_watch.py: mechanical subagent lifecycle watch.

Monitoring gap (user report 2026-08-05): a NEW subagent is invisible to
reconcile until it writes a worker-status file. Agents in bootstrap (pre-first-
status-write) or of types that never write status (red-team, generic) are blind
spots; there is no 'agent started' event from the platform — task-notification
fires only on completion.

Fix: every subagent's transcript output file lives at
    <temp>/claude/<project>/<session>/tasks/<agentId>.output
Its creation = agent START. Its mtime advancing = agent ALIVE. Its mtime frozen
past a threshold = agent STALE (stuck / finished-but-resumable). Scanning this
directory and diffing against a snapshot is a PURELY MECHANICAL lifecycle signal:
no worker-status file needed, no LLM cognition, no transcript content read.

This hook scans the tasks dir, diffs against runs/.agent-snapshot.json, appends
events to runs/.agent-events.jsonl. Wired as PostToolUse matcher=Agent (fires
right after every Agent dispatch/completion) AND called from heartbeat_tick.py
every tick. NEVER reads .output content (transcripts are huge — stat only).
"""
import json
import os
import sys
import glob as globmod
import tempfile
import datetime
from pathlib import Path

STALE_MIN = 20          # mtime frozen > 20 min = STALE candidate (specialist tolerance is 10-20)
ACTIVE_WINDOW_MIN = 30  # only report agents with activity in the last 30 min (ignore old sessions)
TEMP = Path(os.environ.get("TEMP", tempfile.gettempdir()))


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve_ws(arg: str | None) -> Path:
    """Workspace root: explicit arg wins; else probe cwd; else hard error.

    Issue #228: the old fallback defaulted to one operator's absolute Windows
    workspace path — silently wrong on any other machine. Never guess
    a workspace: a wrong one means state written to the wrong tree.
    """
    if arg:
        return Path(arg).resolve()
    cwd = Path(os.getcwd())
    for cand in (cwd, cwd / "malware-analysis-workspace"):
        if (cand / "claim-register.yaml").exists() or (cand / "analysis_state.txt").exists():
            return cand.resolve()
    print(f"ERROR: no workspace found under cwd ({cwd}); pass the workspace "
          f"explicitly: python {Path(sys.argv[0]).name} <workspace>",
          file=sys.stderr)
    sys.exit(2)


def scan_agents() -> dict[str, dict]:
    """Return {agentId: {path, mtime_ts, size}} for all current session task outputs."""
    out = {}
    pattern = str(TEMP / "claude" / "*" / "*" / "tasks" / "*.output")
    for f in globmod.glob(pattern):
        try:
            st = os.stat(f)
        except OSError:
            continue
        agent_id = Path(f).stem
        out[agent_id] = {
            "path": f,
            "mtime_ts": datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "size": st.st_size,
        }
    return out


def main() -> int:
    ws = _resolve_ws(sys.argv[1] if len(sys.argv) > 1 else None)
    snapshot_path = ws / "runs" / ".agent-snapshot.json"
    events_path = ws / "runs" / ".agent-events.jsonl"
    now = datetime.datetime.now(datetime.timezone.utc)

    prev = {}
    if snapshot_path.exists():
        try:
            prev = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    cur = scan_agents()
    events = []
    now_iso = utc_now()

    for aid, meta in cur.items():
        mtime = datetime.datetime.fromisoformat(meta["mtime_ts"].replace("Z", "+00:00"))
        age_min = (now - mtime).total_seconds() / 60.0
        if age_min > ACTIVE_WINDOW_MIN:
            continue  # old session residue — ignore
        if aid not in prev:
            events.append({"ts": now_iso, "type": "NEW", "agent_id": aid, "detail": f"age={age_min:.1f}min size={meta['size']}"})
        elif age_min > STALE_MIN:
            prev_meta = prev.get(aid, {})
            prev_ts = prev_meta.get("mtime_ts", "")
            grew = bool(prev_ts) and prev_ts != meta["mtime_ts"]
            if not grew:
                events.append({"ts": now_iso, "type": "STALE", "agent_id": aid, "detail": f"mtime frozen {age_min:.1f}min (size {prev_meta.get('size', '?')}->{meta['size']})"})

    for aid in prev:
        if aid not in cur:
            events.append({"ts": now_iso, "type": "GONE", "agent_id": aid, "detail": "output file disappeared"})

    if events:
        with open(events_path, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
    snapshot_path.write_text(json.dumps(cur, indent=2), encoding="utf-8")

    active = [a for a in cur if (datetime.datetime.fromisoformat(cur[a]["mtime_ts"].replace("Z", "+00:00")) - now).total_seconds() > -ACTIVE_WINDOW_MIN * 60]
    print(f"agent_watch: active={len(active)} events={len(events)}", *(f"{e['type']}:{e['agent_id'][:12]}" for e in events))
    return 0 if not [e for e in events if e["type"] == "STALE"] else 1


if __name__ == "__main__":
    sys.exit(main())
