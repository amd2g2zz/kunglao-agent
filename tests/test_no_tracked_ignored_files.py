# -*- coding: utf-8 -*-
"""tests/test_no_tracked_ignored_files.py — tracked-vs-ignored global gate (#472).

gitignore only stops UNTRACKED files from being added. A file already in the
index ignores the ignore rule (git add -f, or a staging mishap) and nothing in
CI flags it — this leaked process artifacts onto dev three times (#454
97b4db1, #455 .review/RUNBOOK.md, #472 .review/baseline|final-failures.txt
via PR #460 squash f8119e8).

The naive cross-check is silently defeated: `git check-ignore <path>` is
index-aware and answers "not ignored" for tracked-but-ignored files. The gate
must pass --no-index to see the rule-level truth (paradigm: the tools/ subtree
check-ignore probe in tests/test_tools_structure_340.py:187, generalized to a
global invariant).

Invariant: no tracked file may match any gitignore rule unless explicitly
allowlisted below with a reason.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Legitimate tracked-but-ignored files. Each entry must carry its
# justification; the allowlist hygiene test below fails on stale entries.
TRACKED_IGNORED_ALLOWLIST: dict[str, str] = {
    # Golden-master fixtures: byte-for-byte replay inputs for
    # tests/test_suite_health.py::test_golden_replay (manifest.yaml cases
    # F-03/F-06). The bare `runs/` rule (.gitignore:32) matches directories
    # named runs/ at ANY depth — intended for live workspace state, it also
    # sweeps the fixture ws/ copies. Rule is not ours to narrow (#472: fix
    # enforcement, not rules); these files are deliberately committed.
    "tests/fixtures/golden/F-03/ws/runs/worker-status-w1.md":
        "golden fixture: F-03 replay input (runs/ rule over-matches depth)",
    "tests/fixtures/golden/F-03/ws/runs/worker-status-w2.md":
        "golden fixture: F-03 replay input (runs/ rule over-matches depth)",
    "tests/fixtures/golden/F-03/ws/runs/worker-status-w3.md":
        "golden fixture: F-03 replay input (runs/ rule over-matches depth)",
    "tests/fixtures/golden/F-06/ws/runs/worker-status-w1.md":
        "golden fixture: F-06 replay input (runs/ rule over-matches depth)",
}


def _tracked_ignored_paths() -> list[str]:
    """Tracked paths that match a gitignore rule (--no-index truth)."""
    ls = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True, check=True)
    tracked = [p for p in ls.stdout.decode("utf-8").split("\0") if p]
    if not tracked:
        return []
    chk = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--no-index",
         "--stdin", "--verbose"],
        input="\n".join(tracked).encode("utf-8"),
        capture_output=True)
    # check-ignore --stdin exits 0 if ANY input path is ignored,
    # 1 if none are; both are success states for the gate.
    out = chk.stdout.decode("utf-8")
    ignored: list[str] = []
    for line in out.splitlines():
        # --verbose lines are `<source>:<linenum>:<pattern>\t<path>`
        if "\t" in line:
            ignored.append(line.rsplit("\t", 1)[1])
    return ignored


def test_no_tracked_ignored_files() -> None:
    """No tracked file may be ignored unless allowlisted (#472)."""
    # Arrange: the offending set, minus known-good exceptions.
    unlisted = sorted(
        p for p in _tracked_ignored_paths() if p not in TRACKED_IGNORED_ALLOWLIST)

    # Act / Assert: leak class of #454/#455/#472 must fail CI by name.
    assert not unlisted, (
        "tracked-but-ignored files found (gitignore does not cover tracked "
        "files; either `git rm --cached` them or, if legitimate, add them to "
        f"TRACKED_IGNORED_ALLOWLIST with a reason) — {unlisted}")


def test_allowlist_has_no_stale_entries() -> None:
    """Allowlist entries must still be tracked AND still be ignored.

    A hygiene entry that stops being needed (rule changed, file untracked,
    file renamed) must be removed — otherwise the allowlist rots into a
    blind spot.
    """
    actual = set(_tracked_ignored_paths())
    stale = sorted(
        entry for entry in TRACKED_IGNORED_ALLOWLIST if entry not in actual)
    assert not stale, (
        "stale TRACKED_IGNORED_ALLOWLIST entries (no longer tracked-but-"
        f"ignored; delete them) — {stale}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0)
