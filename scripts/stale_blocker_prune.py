# -*- coding: utf-8 -*-
"""stale_blocker_prune.py - auto-resolve blockers when their claim is closed.

User pain point (verbatim, in Chinese): "状态管理很差 - 一些任务以及过期了或者以及解决了还显示的blocker"
("poor state management — tasks that expired or were already resolved
still show as blockers")

When a claim transitions to PROVEN / REFUTED / DEFERRED / NEGATIVE, any blocker
file in <workspace>/blockers/ that references that claim becomes stale. The
blocker file should NOT appear in active-blocker lists, and the orchestrator
should NOT surface it as "open work".

This script:
  1. Reads claim-register.yaml to get all claims with non-OPEN status
  2. Walks <workspace>/blockers/*.md and parses each file's claim reference
  3. For each blocker whose referenced claim is closed:
     a. Move file to <workspace>/blockers/.resolved/<original-name>
     b. Append to blockers/.resolved/INDEX.md (append-only)
  4. Returns:
     rc=0: no stale blockers (or none to prune)
     rc=1: pruned N stale blockers (informational, not a failure)

A blocker file's "claim reference" is detected by:
  - Frontmatter field: `claim_id: C-NNN`
  - OR inline `claim C-NNN` / `claim_id: C-NNN` in the body
  - OR filename: `B1x-<timestamp>-C-NNN.md`

Usage:
  python stale_blocker_prune.py <workspace> [--dry-run]
"""
from __future__ import annotations
import gate_telemetry as _gt
from status_defs import TERMINAL

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml(path: Path):
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def get_closed_claims(workspace: Path) -> set:
    """Return set of claim IDs whose status is terminal (or STALE)."""
    reg = _load_yaml(workspace / "claim-register.yaml")
    out = set()
    for c in (reg or {}).get("claims", []) or []:
        cid = c.get("id")
        status = (c.get("status") or "").upper()
        if cid and status in TERMINAL:
            out.add(cid)
    return out


def parse_blocker_claim(blocker_path: Path) -> str | None:
    """Extract the claim_id this blocker file references."""
    name = blocker_path.name
    m = re.search(r"(C-\d+)", name)
    if m:
        return m.group(1)
    text = blocker_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^claim_id:\s*(C-\d+)\s*$", text, re.MULTILINE)
    if m:
        return m.group(1)
    m = re.search(r"\bclaim\s+(C-\d+)\b", text)
    if m:
        return m.group(1)
    return None


@_gt.telemetry('stale_blocker_prune')
def check(workspace: Path, dry_run: bool = False) -> int:
    blockers_dir = workspace / "blockers"
    if not blockers_dir.exists():
        print("NOOP: no blockers/ directory")
        return 0

    closed = get_closed_claims(workspace)
    if not closed:
        print("OK: no closed claims; nothing to prune")
        return 0

    candidates = [p for p in blockers_dir.glob("*.md") if p.is_file()]
    resolved_dir = blockers_dir / ".resolved"
    moved = []
    skipped_unknown = []

    for p in candidates:
        claim_id = parse_blocker_claim(p)
        if claim_id is None:
            skipped_unknown.append(p.name)
            continue
        if claim_id not in closed:
            continue
        if not dry_run:
            resolved_dir.mkdir(parents=True, exist_ok=True)
            dest = resolved_dir / p.name
            shutil.move(str(p), str(dest))
            moved.append((p.name, claim_id))

    if moved and not dry_run:
        idx = resolved_dir / "INDEX.md"
        if not idx.exists():
            idx.write_text("# Resolved blockers index\n\n", encoding="utf-8")
        with idx.open("a", encoding="utf-8") as f:
            for name, cid in moved:
                f.write(f"- {utc_now()}: {name} (claim {cid} closed)\n")

    if not moved:
        print(f"OK: {len(candidates)} blocker(s) checked, none stale (closed claims: {len(closed)})")
        if skipped_unknown:
            print(f"  (skipped {len(skipped_unknown)} blocker(s) with no claim_id detectable)")
        return 0

    print(f"{'DRY-RUN: ' if dry_run else ''}Pruned {len(moved)} stale blocker(s) to .resolved/:")
    for name, cid in moved:
        print(f"  - {name} (claim {cid} closed)")
    if skipped_unknown:
        print(f"  (skipped {len(skipped_unknown)} blocker(s) with no claim_id: {skipped_unknown[:5]})")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune stale blockers whose claim is closed")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--dry-run", action="store_true", help="show what would be pruned, no writes")
    args = parser.parse_args()
    return check(Path(args.workspace), dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())