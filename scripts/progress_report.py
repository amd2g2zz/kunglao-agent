"""progress_report.py - emit a single-line progress summary for kunglao-agent.

User pain point: "进度管理" - no visual progress indicator.

This script reads claim-register.yaml and emits a compact, scannable
progress report:
  - Total claims
  - Status breakdown (OPEN / IN_PROGRESS / STALE / terminal)
  - Open workers (count of worker-status-*.md with in_progress)
  - Active blockers (after stale-blocker prune)
  - C0-C7 status (read from converge-checklist.md if exists)
  - Last activity timestamp

Output is a markdown block suitable for both human eyes AND CI log capture.

Usage:
  python progress_report.py <workspace>
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from status_defs import TERMINAL as TERMINAL_STATUSES


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _load_yaml(p):
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def report(workspace: Path) -> int:
    reg = _load_yaml(workspace / "claim-register.yaml")
    claims = (reg or {}).get("claims", []) or []
    by_status = {}
    for c in claims:
        s = (c.get("status") or "UNKNOWN").upper()
        by_status[s] = by_status.get(s, 0) + 1

    runs_dir = workspace / "runs"
    active_workers = 0
    stuck_workers = 0
    if runs_dir.exists():
        cutoff_age = timedelta(minutes=20)
        now = utc_now()
        for p in runs_dir.glob("worker-status-*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                if "in-progress" in text.lower():
                    active_workers += 1
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                if (now - mtime) > cutoff_age:
                    stuck_workers += 1
            except OSError:
                continue

    blockers_dir = workspace / "blockers"
    active_blockers = 0
    if blockers_dir.exists():
        active_blockers = sum(1 for p in blockers_dir.glob("*.md") if p.is_file())

    c07_text = ""
    checklist = workspace / "converge-checklist.md"
    if checklist.exists():
        c07_text = checklist.read_text(encoding="utf-8", errors="replace")[:500]

    last_activity = None
    for c in claims:
        for f in ("last_activity_at", "dispatched_at", "created_at", "updated_at"):
            v = c.get(f)
            if v:
                last_activity = v
                break

    terminal = sum(v for k, v in by_status.items() if k in TERMINAL_STATUSES)
    open_n = by_status.get("OPEN", 0)
    stale_n = by_status.get("STALE", 0)
    pct = (terminal / len(claims) * 100) if claims else 0

    lines = []
    lines.append(f"# kunglao-agent progress report ({utc_now().strftime('%Y-%m-%dT%H:%M:%SZ')})")
    lines.append("")
    lines.append(f"## Claims: {len(claims)} total ({terminal} terminal = {pct:.0f}% converged)")
    for s in sorted(by_status.keys()):
        lines.append(f"  - {s}: {by_status[s]}")
    lines.append(f"## Workers: {active_workers} in-flight; {stuck_workers} potentially stuck (>20m no update)")
    lines.append(f"## Blockers: {active_blockers} active (run stale_blocker_prune.py to resolve)")
    if last_activity:
        lines.append(f"## Last activity: {last_activity}")
    if c07_text:
        lines.append(f"## C0-C7 (excerpt):")
        for line in c07_text.splitlines()[:5]:
            if line.strip():
                lines.append(f"  {line}")
    print("\n".join(lines))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="kunglao-agent progress report")
    parser.add_argument("workspace", help="workspace root")
    args = parser.parse_args()
    return report(Path(args.workspace))


if __name__ == "__main__":
    sys.exit(main())