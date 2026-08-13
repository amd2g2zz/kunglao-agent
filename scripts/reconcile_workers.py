# -*- coding: utf-8 -*-
"""reconcile_workers.py - rebuild [active_workers] from worktree status files.

Extracted from hook_activation.py (T-2 split) — the --reconcile job.
"""
from __future__ import annotations

import re
from pathlib import Path


def reconcile_workers(workspace: Path) -> int:
    """Rebuild [active_workers] from the GROUND TRUTH — worker status files
    in every .wt-*/ worktree (and the main workspace runs/).

    A worker is ACTIVE iff its LAST status line says "in-progress". This
    removes zombie [active_workers] entries that appear when the PostToolUse
    remove_worker hook never fires (hooks not wired / settings.json
    rewritten). Returns the active count.
    """
    status_re = re.compile(r"status:\s*(\S+)")
    active_ids = set()
    dirs = [workspace / "runs"]
    try:
        for _m in sorted(workspace.parent.glob(".wt-*/.kunglao-worktree")):
            _r = _m.parent / "malware-analysis-workspace" / "runs"
            if _r.is_dir():
                dirs.append(_r)
    except OSError:
        pass
    for runs in dirs:
        if not runs.is_dir():
            continue
        for p in runs.glob("worker-status-*.md"):
            last = None
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                m = status_re.search(line)
                if m:
                    last = m.group(1).lower()
            if last == "in-progress":
                active_ids.add(p.stem)
        # red-team verifiers write plan-redteam-*.md (start) + verify-redteam-*.md (end).
        # ACTIVE iff plan exists but its verify report is not yet written.
        for p in runs.glob("plan-redteam-*.md"):
            target = p.stem[len("plan-redteam-"):]
            if not (runs / f"verify-redteam-{target}.md").exists():
                active_ids.add(f"verifier-redteam-{target}")

    # rewrite the [active_workers] segment of analysis_state.txt
    state_path = workspace / "analysis_state.txt"
    text = state_path.read_text(encoding="utf-8", errors="replace")
    seg_re = re.compile(r"\[active_workers\].*?\[/active_workers\]", re.DOTALL)
    entries = [f"worker_id={wid} | claim_id= | dispatched_at=0 | tier=0 | tools=" for wid in sorted(active_ids)]
    block = "[active_workers]\n" + "\n".join(entries) + ("\n" if entries else "") + "[/active_workers]"
    new_text, n_subs = seg_re.subn(block, text, count=1)
    if n_subs == 0:
        new_text = text.rstrip("\n") + "\n\n" + block + "\n"
    state_path.write_text(new_text, encoding="utf-8")
    return len(active_ids)
