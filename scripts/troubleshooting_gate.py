# -*- coding: utf-8 -*-
"""troubleshooting_gate.py - enforce pre-cap troubleshooting checklist.

User pain point: "VM network不通 折腾一下午, 最后告诉我 VM 是坏的, 其实只要 ping 一下".
kunglao-agent's worker_budget.py::check_promotion_attempts caps promotion_attempts at 3,
then forces DEFERRED. But there's no enforcement that the worker actually
checked basic infrastructure health before declaring the claim unpromotable.

This script runs BEFORE promotion check: if promotion_attempts >= 2 (about to
be capped), require a troubleshooting_report in worker-status-<id>.md or the
dispatch metadata. The report must include:
  - infra_health: ping/curl/nslookup result(s) - what was checked
  - search_attempted: 1+ documentation/issue search with result
  - fallback_tried: any alternate path attempted (different tool, different host, etc.)

Missing any of the 3 -> REJECT + log "B1e troubleshooting-incomplete" so the
dispatch must continue trying, not skip.

Usage:
  python troubleshooting_gate.py <workspace> <claim_id>
Exit 0 if report present + complete; 1 if missing/incomplete.
"""
from __future__ import annotations
import gate_telemetry as _gt
import hook_activation as ha


import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_SECTIONS = ["infra_health", "search_attempted", "fallback_tried"]


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_worker_status(workspace: Path, claim_id: str) -> Path | None:
    """Find worker-status-*.md that mentions this claim_id."""
    workers_dir = workspace / "runs"
    if not workers_dir.exists():
        return None
    for p in workers_dir.glob("worker-status-*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if claim_id in text:
            return p
    return None


def has_troubleshooting_report(workspace: Path, claim_id: str) -> tuple:
    """Check if worker_status file has all 3 required sections.

    Returns (ok, missing_sections).
    """
    status = find_worker_status(workspace, claim_id)
    if status is None:
        return False, REQUIRED_SECTIONS

    text = status.read_text(encoding="utf-8", errors="replace").lower()
    missing = [s for s in REQUIRED_SECTIONS if f"## {s}" not in text and f"### {s}" not in text]
    return len(missing) == 0, missing


@_gt.telemetry('troubleshooting_gate')
def check(workspace: Path, claim_id: str) -> int:
    ok, missing = has_troubleshooting_report(workspace, claim_id)
    if ok:
        print(f"OK: {claim_id} has complete troubleshooting report")
        return 0
    print(f"REJECT: {claim_id} missing troubleshooting sections: {missing}")
    print(f"  Worker must add these to worker-status-<id>.md BEFORE re-attempting promotion:")
    print(f"  ## infra_health    # ping/curl/nslookup/SSH attempts + results")
    print(f"  ## search_attempted  # at least 1 doc search with result + URL")
    print(f"  ## fallback_tried  # alternate path attempted (different tool, different host, etc.)")
    print(f"  This gate exists because claiming 'infrastructure is broken' without")
    print(f"  basic checks wastes hours of orchestrator time.")
    return 1


def write_placeholder_report(workspace: Path, claim_id: str, worker_id: str = "unknown") -> Path:
    """Helper: write a stub troubleshooting report so workers can see the schema."""
    workers_dir = workspace / "runs"
    workers_dir.mkdir(parents=True, exist_ok=True)
    out = workers_dir / f"worker-status-{worker_id}.md"
    fm = (
        f"# Worker status - {worker_id} - claim {claim_id} - {utc_now()}\n\n"
        f"## Status\nin-progress\n\n"
        f"## Claim\n{claim_id}\n\n"
        f"## infra_health\n- ping <target>: <result>\n- curl <url>: <result>\n\n"
        f"## search_attempted\n- query: <what you searched>\n- result: <URL + summary>\n\n"
        f"## fallback_tried\n- alternate: <what you tried instead>\n- result: <result>\n\n"
    )
    out.write_text(fm, encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Troubleshooting gate pre-promotion check")

    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("claim_id", help="claim being promoted (e.g. C-007)")
    parser.add_argument("--stub", action="store_true", help="write a stub troubleshooting report template")
    parser.add_argument("--worker-id", default="unknown", help="worker ID for stub filename")
    args = parser.parse_args()

    # F-10 selective activation: skip if hook is paused
    if not ha.is_active(Path(args.workspace), "troubleshooting_gate"):
        print("SKIP: troubleshooting_gate is paused (check .hook_state.json)")
        return 0

    workspace = Path(args.workspace)
    if args.stub:
        out = write_placeholder_report(workspace, args.claim_id, args.worker_id)
        print(f"WROTE stub: {out}")
        return 0
    return check(workspace, args.claim_id)


if __name__ == "__main__":
    sys.exit(main())