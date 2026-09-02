# -*- coding: utf-8 -*-
"""progress_report.py - emit a single-line progress summary for kunglao-agent.

User pain point (verbatim, in Chinese): "进度管理" ("progress management") - no visual progress indicator.

This script reads claim-register.yaml and emits a compact, scannable
progress report:
  - Total claims
  - Status breakdown (OPEN / IN_PROGRESS / STALE / terminal)
  - Open workers (in-progress count from the canonical liveness protocol)
  - Active blockers (after stale-blocker prune)
  - Anomaly observation count (#663 — `boundary_type: anomaly` in notes/)
  - C0-C7 status (read from converge-checklist.md if exists)
  - Last activity timestamp

Output is a markdown block suitable for both human eyes AND CI log capture.

Usage:
  python progress_report.py <workspace>
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import yaml

from status_defs import TERMINAL as TERMINAL_STATUSES
from _hooks_path import load_hooks_lib  # #863 Family B: loader delegation (#671 authority)


def _worker_protocol():
    """hooks/lib_kunglao.py — THE worker-liveness protocol owner (#444).
    Review F-1: this module previously counted active workers by SUBSTRING
    presence ("in-progress" in text), which counts every normally-completed
    worker (its append-only file keeps historical in-progress lines) as
    active — the exact double representation #444 removes.
    #863 Family B: the by-path prologue collapsed into the canonical loader
    (hooks/_path_hygiene.load_hooks_lib, via scripts/_hooks_path) — the
    loud-missing guard stays HERE (its message is part of the contract)."""
    path = Path(__file__).resolve().parent.parent / "hooks" / "lib_kunglao.py"
    if not path.exists():
        raise RuntimeError(
            f"worker-liveness protocol missing: {path} — hooks/ and scripts/ "
            "ship together; reinstall the kunglao-agent skill")
    return load_hooks_lib()


from harness_common import utc_now  # #863 Family F: single source (was a local def)


def _load_yaml(p):
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _count_anomaly_notes(workspace: Path) -> int:
    """Count `boundary_type: anomaly` notes under <workspace>/notes/.

    Per issue #663 acceptance criterion #3: progress_report output must
    surface the anomaly observation count so operators do not have to
    count notes/*.md by hand. Data source is the post-scan ground truth
    (anomaly_detector._write_anomaly_note writes these notes after
    scan_anomalies flags a fact — see scripts/anomaly_detector.py:332-374).

    Tolerant frontmatter parsing: extracts the YAML block (between the
    first two `---` markers when both exist) and falls back to scanning
    the whole file when the note uses line-level frontmatter (no closing
    `---`). Substring search for `boundary_type: anomaly` catches both
    canonical and hand-written forms.

    Fail-open: any error (missing dir, glob error, read error) returns 0
    — a broken notes/ directory must not break the rest of the report.
    """
    try:
        notes_dir = workspace / "notes"
        if not notes_dir.is_dir():
            return 0
        n = 0
        for p in notes_dir.glob("*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue  # skip unreadable file (fail-open)
            # Restrict search to the frontmatter section when both `---`
            # markers are present; otherwise search the whole file.
            parts = text.split("\n---\n", 2)
            head = parts[1] if len(parts) >= 3 else text
            if "boundary_type: anomaly" in head:
                n += 1
        return n
    except Exception:
        return 0


def report(workspace: Path) -> int:
    reg = _load_yaml(workspace / "claim-register.yaml")
    claims = (reg or {}).get("claims", []) or []
    by_status = {}
    for c in claims:
        s = (c.get("status") or "UNKNOWN").upper()
        by_status[s] = by_status.get(s, 0) + 1

    # Worker liveness from the canonical protocol (#444, review F-1): last
    # `status:` token wins over both line shapes, main runs/ + .wt-*
    # worktrees. `stuck` keeps its pre-F-1 advisory semantics: any status
    # file older than 20 min is "potentially stuck" (label says potentially —
    # mtime only, not the canonical active+stale rule).
    states = _worker_protocol().iter_worker_states(Path(workspace))
    active_workers = sum(1 for s in states if s["status"] == "in-progress")
    cutoff_age = timedelta(minutes=20)
    now = utc_now()
    stuck_workers = sum(1 for s in states if (now - s["mtime"]) > cutoff_age)

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
    anomaly_n = _count_anomaly_notes(Path(workspace))
    lines.append(f"## Anomalies: {anomaly_n} observation notes (notes/*.md with boundary_type: anomaly)")
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
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())