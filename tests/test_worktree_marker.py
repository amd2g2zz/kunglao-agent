# -*- coding: utf-8 -*-
"""test_worktree_marker.py — verify .kunglao-worktree marker gating (#137)."""
from __future__ import annotations
import tempfile
from pathlib import Path


def test_wt_dir_without_marker_not_scanned():
    """A .wt-* directory without .kunglao-worktree marker must NOT be scanned."""
    with tempfile.TemporaryDirectory() as tmp:
        ws_parent = Path(tmp)
        # Fake worktree dir WITHOUT marker
        fake_wt = ws_parent / ".wt-fake" / "malware-analysis-workspace" / "runs"
        fake_wt.mkdir(parents=True)
        (fake_wt / "worker-status-X.md").write_text("status: in-progress\n")

        # The protocol scan must NOT count an unmarked .wt-* dir (863-d:
        # _scan_active_workers shell retired; drive _scan_workers directly)
        import sys
        sys.path.insert(0, str(Path("scripts").resolve()))
        from convergence_check import _scan_workers
        active, stuck = _scan_workers(ws_parent / "ws")[:2]
        assert active == 0, f"Expected 0 active (no marker), got {active}"


def test_wt_dir_with_marker_scanned():
    """A .wt-* directory WITH .kunglao-worktree marker MUST be scanned."""
    with tempfile.TemporaryDirectory() as tmp:
        ws_parent = Path(tmp)
        ws = ws_parent / "ws"
        (ws / "runs").mkdir(parents=True)

        # Real worktree WITH marker
        real_wt = ws_parent / ".wt-real" / "malware-analysis-workspace" / "runs"
        real_wt.mkdir(parents=True)
        (ws_parent / ".wt-real" / ".kunglao-worktree").write_text("active")
        (real_wt / "worker-status-Y.md").write_text("status: in-progress\n")

        import sys
        sys.path.insert(0, str(Path("scripts").resolve()))
        from convergence_check import _scan_workers
        active, stuck = _scan_workers(ws)[:2]
        assert active == 1, f"Expected 1 active (with marker), got {active}"
