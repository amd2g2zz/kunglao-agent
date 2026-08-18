# -*- coding: utf-8 -*-
"""reconcile_workers.py - rebuild [active_workers] from worktree status files.

Extracted from hook_activation.py (T-2 split) — the --reconcile job.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _worker_protocol():
    """hooks/lib_kunglao.py — THE worker-liveness protocol owner (#444), by
    path under the unique name lib_kunglao_hooks (bare `import lib_kunglao`
    is ambiguous under pytest — scripts/lib_kunglao.py shares the name).
    seg_re below is the [active_workers] segment WRITE format of
    analysis_state.txt, a different protocol — it stays local."""
    import importlib.util
    name = "lib_kunglao_hooks"
    lib = sys.modules.get(name)
    if lib is None:
        path = Path(__file__).resolve().parent.parent / "hooks" / "lib_kunglao.py"
        spec = importlib.util.spec_from_file_location(name, path)
        lib = importlib.util.module_from_spec(spec)
        sys.modules[name] = lib
        spec.loader.exec_module(lib)
    return lib


def reconcile_workers(workspace: Path) -> int:
    """Rebuild [active_workers] from the GROUND TRUTH — worker status files
    in every .wt-*/ worktree (and the main workspace runs/).

    A worker is ACTIVE iff its LAST status token says "in-progress"
    (hooks/lib_kunglao.parse_worker_status, #444 — the canonical protocol;
    scan targets here match it: main runs/ + every .wt-*/ worktree runs/).
    This removes zombie [active_workers] entries that appear when the
    PostToolUse remove_worker hook never fires (hooks not wired /
    settings.json rewritten). Returns the active count.
    """
    parse_status = _worker_protocol().parse_worker_status
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
        statuses = list(runs.glob("worker-status-*.md"))
        for p in statuses:
            last = parse_status(p.read_text(encoding="utf-8", errors="replace"))
            if last == "in-progress":
                active_ids.add(p.stem)
        # red-team verifiers write plan-redteam-*.md (start) + verify-redteam-*.md (end).
        # ACTIVE iff plan exists but its verify report is not yet written.
        for p in runs.glob("plan-redteam-*.md"):
            target = p.stem[len("plan-redteam-"):]
            if not (runs / f"verify-redteam-{target}.md").exists():
                active_ids.add(f"verifier-redteam-{target}")
        # worker plans (issue #239): runs/plan-<task>.md is the FIRST artifact
        # a dispatched worker writes (kunglao-worker.md golden rule #3 — PLAN
        # FIRST, execute second), before its worker-status file. A runs dir
        # with NO worker-status files at all while plan files exist means
        # worker(s) started but never wrote a status file (crash / PostToolUse
        # remove_worker never fired) — keep those slots visible so the worker
        # budget is not silently overshot. Dirs WITH any status file are
        # skipped: in-progress workers are already counted above, and done
        # files mean the plans are completed-work leftovers.
        if not statuses:
            for p in runs.glob("plan-*.md"):
                if p.stem.startswith("plan-redteam-"):
                    continue  # handled above
                active_ids.add(f"worker-plan-{p.stem[len('plan-'):]}")

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
