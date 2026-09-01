"""search_gate.py - enforce search-before-research on every dispatch.

User pain point: "struct or data structure - actually searching online can solve,
but kunglao-agent insists on researching it itself."

This gate runs AFTER worker returns + BEFORE orchestrator promotes the fact.
The worker_status file MUST contain a `search_before_work` field documenting
1+ documentation search the worker performed BEFORE the main analysis.

If absent: REJECT with "B1f search-first skipped" so the worker re-runs WITH
a search attempt (not just documents one).

Exception cases (allow skip_search_when = offline / pure-static / no-network):
  - claim explicitly tagged offline_first in claim-register.yaml
  - sample is fully self-contained (e.g. no struct, no API)

Usage:
  python search_gate.py <workspace> <claim_id> [--allow-offline]
Exit 0 if search_before_work present OR explicit offline exception; 1 otherwise.
"""
from __future__ import annotations
import gate_telemetry as _gt
import hook_activation as ha


import argparse
import sys
from pathlib import Path

SEARCH_REQUIRED_MARKER = "## search_before_work"
ALLOWED_OFFLINE_TAG = "offline_first"


def find_worker_status(workspace: Path, claim_id: str) -> Path | None:
    workers_dir = workspace / "runs"
    if not workers_dir.exists():
        return None
    for p in workers_dir.glob("worker-status-*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if claim_id in text:
            return p
    return None


def find_claim_register(workspace: Path) -> Path | None:
    candidates = [
        workspace / "claim-register.yaml",
        workspace / "claim_register.yaml",
        workspace / "malware-analysis-workspace" / "claim-register.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def has_search_before_work(workspace: Path, claim_id: str, allow_offline: bool) -> tuple:
    """Returns (ok, reason)."""
    status = find_worker_status(workspace, claim_id)
    text = status.read_text(encoding="utf-8", errors="replace") if status else ""

    if status and (SEARCH_REQUIRED_MARKER in text or "## search_attempted" in text):
        return True, "search_before_work section present"

    # Worker status may be missing entirely; check offline tag before rejecting
    if allow_offline:
        reg = find_claim_register(workspace)
        if reg is not None:
            try:
                text_reg = reg.read_text(encoding="utf-8", errors="replace")
                if ALLOWED_OFFLINE_TAG in text_reg and claim_id in text_reg:
                    return True, "offline_first tag in claim-register.yaml"
            except OSError:
                pass

    if status is None:
        return False, f"no worker-status file for {claim_id}"

    return False, (
        f"REJECT: worker must document search_before_work in {status.name}.\n"
        "  At minimum: 1 query + 1 source URL + 1 hit/miss result.\n"
        "  Without this, we waste time on internals that 5 sec of Google could answer.\n"
        "  Exception: add 'offline_first: true' to claim-register.yaml if the\n"
        "  claim is explicitly offline-only (no internet available)."
    )


@_gt.telemetry('search_gate')
def check(workspace: Path, claim_id: str, allow_offline: bool) -> int:
    ok, reason = has_search_before_work(workspace, claim_id, allow_offline)
    print(reason)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Search-first dispatch gate")

    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("claim_id", help="claim being verified (e.g. C-007)")
    parser.add_argument("--allow-offline", action="store_true",
                        help="allow skip if claim-register.yaml tags claim as offline_first")
    args = parser.parse_args()

    # F-10 selective activation: skip if hook is paused
    if not ha.is_active(Path(args.workspace), "search_gate"):
        print("SKIP: search_gate is paused (check .hook_state.json)")
        return 0
    return check(Path(args.workspace), args.claim_id, args.allow_offline)


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())