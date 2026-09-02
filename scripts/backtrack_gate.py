# -*- coding: utf-8 -*-
"""backtrack_gate.py - detect workers stuck > N min without progress.

User pain point (verbatim, in Chinese): "kunglao-agent 不会回退 - 遇到了问题以及很长时间了, 但是还在做
无意义的尝试" ("kunglao-agent never backs off — a problem has persisted for a
long time yet it keeps making pointless attempts") (gets stuck in
repetitive failed attempts without backing off).

When a worker has been in_progress for > N min (configurable, default 20) WITHOUT
its status file mtime updating, it is "stuck". This gate REQUIRES a `## backtrack`
section in the stuck worker's status file with:
  - decision: continue | retry_different | escalate | redispatch
  - reason: <why stuck>
  - new_approach: <what's different in next attempt>

Usage:
  python backtrack_gate.py <workspace> [--stuck-min 20]
Exit codes:
  0 = no stuck workers (or all have valid backtrack)
  1 = stuck worker(s) without backtrack section
  2 = stuck worker(s) with backtrack but un-actioned for > 30 min
"""
from __future__ import annotations
import gate_telemetry as _gt
import hook_activation as ha


import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from _hooks_path import load_hooks_lib  # #863 Family B: loader delegation (#671 authority)

STATUS_RE = re.compile(r"^## Status\s*$", re.MULTILINE)
ALLOWED_DECISIONS = {"continue", "retry_different", "escalate", "redispatch"}


from harness_common import utc_now  # #863 Family F: single source (was a local def)


def parse_status(text: str) -> str | None:
    """#607/#444: delegate to lib_kunglao.parse_worker_status (THE single
    parse point). Legacy `## Status` section files keep working: the section
    body is normalized to a ``status:`` token so the canonical parser reads
    it — no more mirror regex drifting blind on inline-token files."""
    lib = load_hooks_lib()
    m = STATUS_RE.search(text)
    if m:
        rest = text[m.end():]
        for line in rest.splitlines():
            s = line.strip().lower()
            if s:
                text = text + f"\nstatus: {s}"
                break
    token = lib.parse_worker_status(text)
    return token.replace("-", "_") if token else None


def parse_backtrack(text: str) -> dict | None:
    m = re.search(r"## backtrack\s*(.+?)(?:\n## |\Z)", text, re.DOTALL)
    if not m:
        return None
    fields = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip().lower()] = v.strip()
    return fields if fields else None


@_gt.telemetry('backtrack_gate')
def check(workspace: Path, stuck_min: int) -> int:
    workers_dir = workspace / "runs"
    if not workers_dir.exists():
        print("NOOP: no runs/ directory")
        return 0

    now = utc_now()
    stuck = []
    valid_backtrack = []
    un_actioned = []

    for p in workers_dir.glob("worker-status-*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        status = parse_status(text)
        if status != "in_progress":
            continue
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        age_min = (now - mtime).total_seconds() / 60
        if age_min < stuck_min:
            continue
        bt = parse_backtrack(text)
        if bt is None:
            stuck.append({"file": p.name, "age_min": age_min, "status": "no_backtrack"})
            continue
        decision = bt.get("decision", "")
        if decision not in ALLOWED_DECISIONS:
            stuck.append({"file": p.name, "age_min": age_min,
                          "status": f"invalid_decision:{decision}"})
            continue
        valid_backtrack.append({"file": p.name, "age_min": age_min,
                                "decision": decision, "reason": bt.get("reason", "")})
        if age_min > 30 and decision != "redispatch":
            un_actioned.append({"file": p.name, "age_min": age_min, "decision": decision})

    if not stuck and not un_actioned:
        print(f"OK: no stuck workers (threshold {stuck_min}m)")
        return 0

    if stuck:
        print(f"REJECT: {len(stuck)} stuck worker(s) without valid backtrack (threshold {stuck_min}m):")
        for s in stuck:
            print(f"  - {s['file']} (age {s['age_min']:.1f}m, {s['status']})")
        print()
        print("ORCHESTRATOR MUST force worker to write `## backtrack` block in:")
        print("  ## backtrack")
        print("  decision: continue | retry_different | escalate | redispatch")
        print("  reason: <why stuck>")
        print("  new_approach: <what changes in next attempt>")
        print()
        print("Continuing without backtrack = mechanical retry loop = wasted cost.")
        return 1

    if un_actioned:
        print(f"HARD_PAUSE: {len(un_actioned)} worker(s) stuck > 30m without redispatch:")
        for u in un_actioned:
            print(f"  - {u['file']} (age {u['age_min']:.1f}m, decision={u['decision']})")
        print()
        print("Worker decided NOT to redispatch but is still stuck > 30m.")
        print("Orchestrator must escalate to user or override to redispatch.")
        return 2

    print(f"OK: {len(valid_backtrack)} stuck worker(s) have valid backtrack decisions")
    for v in valid_backtrack:
        print(f"  - {v['file']} (age {v['age_min']:.1f}m, decision={v['decision']})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtrack gate - stuck worker enforcement")

    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--stuck-min", type=int, default=20,
                        help="minutes without status-file update before considered stuck (default 20)")
    args = parser.parse_args()

    # F-10 selective activation: skip if hook is paused
    if not ha.is_active(Path(args.workspace), "backtrack_gate"):
        print("SKIP: backtrack_gate is paused (check .hook_state.json)")
        return 0
    return check(Path(args.workspace), stuck_min=args.stuck_min)


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())