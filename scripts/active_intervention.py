# -*- coding: utf-8 -*-
"""active_intervention.py - enforce orchestrator responds to worker help requests.

User pain point: "subagent reports problem, orchestrator pretends not to see,
doesn't give guidance or help, just mechanically cycles through problems."

When a worker posts to its worker-status-<id>.md a `## help_request` section,
the orchestrator MUST respond within 5 minutes (one heartbeat tick) by one of:
  (a) SendMessage with a workaround (URL, snippet, hint)
  (b) redispatch the claim with a different agent (per priority.py)
  (c) explicit B1d log (no workable path; mark block + reason)

Failure to respond = section 6-pre F-7 violation (orchestrator passive when worker asks help).

Isolation boundary (#88): no agent-team features — workers are isolated
subagents that never message each other; SendMessage orchestrator↔worker is
the sanctioned channel. kunglao-monitor.py runs as a BACKGROUND process; its
output never blocks the loop's scheduled tick actions (re-dispatch / verify).

This script:
  1. Scans runs/ for worker-status-*.md files with `## help_request` sections
  2. Checks the response log (heartbeat_actions.md) for matching SendMessage / redispatch / B1d
  3. Returns the list of unresponded help requests (must be empty per heartbeat)

Usage:
  python active_intervention.py <workspace> [--max-age-min 5]
Exit 0 if all help requests have orchestrator response OR are stale (> max-age-min).
Exit 1 if any in-window help request is unresponded (orchestrator must act).
Exit 2 if no help requests found (no-op).
"""
from __future__ import annotations
import gate_telemetry as _gt
import hook_activation as ha


import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HELP_REQUEST_MARKER = "## help_request"
RESPONSE_MARKER = "## orchestrator_response"
HEARTBEAT_LOG = "heartbeat_actions.md"


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def find_help_requests(workspace: Path) -> list:
    """Find all help_request sections in worker-status-*.md, with timestamps."""
    workers_dir = workspace / "runs"
    if not workers_dir.exists():
        return []
    out = []
    for p in workers_dir.glob("worker-status-*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if HELP_REQUEST_MARKER not in text:
            continue
        m = re.search(r"#\s*Worker status\s*[—–\-]\s*([\w-]+)\s*[—–\-]\s*claim\s*(\S+)\s*[—–\-]\s*(\S+)", text)
        if not m:
            continue
        worker_id, claim_id, ts = m.groups()
        try:
            ts_dt = parse_iso(ts)
        except ValueError:
            continue
        out.append({
            "file": p.name,
            "worker_id": worker_id,
            "claim_id": claim_id,
            "timestamp": ts_dt,
            "text_excerpt": _excerpt_help(text),
        })
    return out


def _excerpt_help(text: str) -> str:
    """Pull the first 5 non-empty lines after ## help_request."""
    lines = text.splitlines()
    in_help = False
    excerpt = []
    for ln in lines:
        if ln.startswith("## help_request"):
            in_help = True
            continue
        if in_help:
            if ln.startswith("## ") or ln.startswith("# "):
                break
            if ln.strip():
                excerpt.append(ln.strip())
            if len(excerpt) >= 5:
                break
    return " | ".join(excerpt) if excerpt else "(empty help request)"


def find_responses(workspace: Path) -> list:
    """Find all orchestrator_response sections in heartbeat_actions.md."""
    log = workspace / HEARTBEAT_LOG
    if not log.exists():
        return []
    out = []
    text = log.read_text(encoding="utf-8", errors="replace")
    in_resp = False
    cur_claim = None
    cur_text = []
    for ln in text.splitlines():
        if ln.startswith("## orchestrator_response"):
            in_resp = True
            cur_text = []
            continue
        if in_resp:
            if ln.startswith("## ") and not ln.startswith("## orchestrator_response"):
                if cur_claim:
                    out.append({"claim_id": cur_claim, "text": " ".join(cur_text)})
                in_resp = False
                cur_claim = None
                cur_text = []
                continue
            m = re.match(r"claim:\s*(\S+)", ln)
            if m:
                cur_claim = m.group(1)
            elif ln.strip():
                cur_text.append(ln.strip())
    if in_resp and cur_claim:
        out.append({"claim_id": cur_claim, "text": " ".join(cur_text)})
    return out


@_gt.telemetry('active_intervention')
def check(workspace: Path, max_age_min: int = 5) -> int:
    """Check for unresponded help requests in the last max_age_min minutes."""
    reqs = find_help_requests(workspace)
    if not reqs:
        print("NOOP: no help requests found")
        return 2

    responses = find_responses(workspace)
    responded_claims = {r["claim_id"] for r in responses}

    now = utc_now()
    in_window = []
    for r in reqs:
        age_min = (now - r["timestamp"]).total_seconds() / 60
        if age_min > max_age_min:
            continue
        if r["claim_id"] in responded_claims:
            continue
        in_window.append(r)

    if not in_window:
        print(f"OK: all help requests either responded or > {max_age_min}m old")
        return 0

    print(f"REJECT: {len(in_window)} help request(s) unresponded within {max_age_min}m:")
    for r in in_window:
        age_min = (now - r["timestamp"]).total_seconds() / 60
        print(f"  - {r['claim_id']} (W={r['worker_id']}, age {age_min:.1f}m, file={r['file']})")
        print(f"    > {r['text_excerpt']}")
    print()
    print("ORCHESTRATOR MUST respond within 5 min by one of:")
    print("  (a) SendMessage with workaround + log ## orchestrator_response in heartbeat_actions.md")
    print("  (b) redispatch the claim with a different agent (per priority_ratio.py)")
    print("  (c) explicit B1d log + mark claim as blocked with reason")
    print()
    print("Ignoring help requests for > 5 min wastes worker time and cascades")
    print("into false 'blocked' status that looks like real failures.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Active intervention check")

    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--max-age-min", type=int, default=5,
                        help="max age (min) before help request is considered stale (default 5)")
    args = parser.parse_args()

    # F-10 selective activation: skip if hook is paused
    # v1.9.9 fix: is_active() needs a Path, not a str (Path / str raises TypeError)
    if not ha.is_active(Path(args.workspace), "active_intervention"):
        print("SKIP: active_intervention is paused (check .hook_state.json)")
        return 0
    return check(Path(args.workspace), max_age_min=args.max_age_min)


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())