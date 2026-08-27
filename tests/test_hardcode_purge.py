# -*- coding: utf-8 -*-
"""Issue #356 W3 — hardcode purge contract.

The pre-#356 tree shipped the original author's machine paths in production
code (C:/Users/hr/...) and a bare VM shell port constant. #356 W3 removes  # HISTORICAL-PATH-EXAMPLE
them: real code paths derive from Path(__file__) or are parameterized,
docstring examples use <HOME>/ placeholders, and VM_SHELL_PORT reads
KUNGLAO_VM_SHELL_PORT (default 9876 — covered in tests/test_toolchain.py).

The docstring and comment lines below cite the purged pre-#356 shapes
verbatim; each carries the HISTORICAL-PATH-EXAMPLE line sentinel (#690)
so the no-absolute-paths guard skips documented historical references.

Issue #367 MEDIUM: the scan covered only scripts/+tools/(+templates/hooks/
agents) — the .claude/git-hooks/pre-commit key-path hardcode slipped through.
The scan is now WHOLE-TREE over git-tracked paths (git grep), matching the
issue acceptance `git grep -E "C:/Users/[a-z]" -- .claude/` -> zero hits.  # HISTORICAL-PATH-EXAMPLE

ALLOWLIST = tracked files that legitimately reference a Windows user path:
  - CHANGELOG.md                 — historical prose RECORDING the #356 purge
  - tests/test_hardcode_purge.py — this scan (states the ban)
  - tests/test_suite_health.py   — legacy fixture-manifest rebase constants
                                   (functional: maps pre-#356 captured paths
                                   onto the current machine)
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Windows user paths: C:/Users/<name> or C:\Users\<name>, lowercase username  # HISTORICAL-PATH-EXAMPLE
# start (the issue acceptance pattern C:/Users/[a-z]; the standard  # HISTORICAL-PATH-EXAMPLE
# C:\Users\Public dir is not a personal username and does not match).  # HISTORICAL-PATH-EXAMPLE
_HARDCODED_USER = re.compile(r"C:[/\\]+Users[/\\]+[a-z]")

# Tracked files exempt from the ban, each with a functional reason (above).
ALLOWLIST = {
    "CHANGELOG.md",
    "tests/test_hardcode_purge.py",
    "tests/test_suite_health.py",
    "tests/test_review_hook_install.py",  # states the pre-#367 ban itself
}


def _tracked_hits() -> list[str]:
    """git grep over EVERY tracked path (whole tree, not a dir subset).

    git grep rc: 0 = matches found, 1 = no matches, >1 = git failure.
    A git failure is itself a test failure (fail-closed: unverifiable
    invariant != satisfied invariant).
    """
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "grep", "-l", "-I", "-E",
         r"C:[/\\]+Users[/\\]+[a-z]", "--", "."],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode > 1:
        raise AssertionError(
            f"git grep failed (rc={proc.returncode}): {proc.stderr.strip()}")
    files = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    unallowlisted = sorted(f for f in files if f not in ALLOWLIST)
    # allowlisted entries must still exist (a stale allowlist entry hides
    # nothing once the file is gone — prune it)
    stale = sorted(a for a in ALLOWLIST if a not in files)
    assert not stale, f"stale ALLOWLIST entries (file no longer matches): {stale}"
    return unallowlisted


def test_no_hardcoded_windows_user_paths_in_tracked_tree() -> None:
    hits = _tracked_hits()
    assert not hits, (
        f"Windows user path (C:/Users/<name>) remains in tracked files: "  # HISTORICAL-PATH-EXAMPLE
        f"{hits} — derive from Path(__file__), use <HOME> placeholders in "
        "prose, or install-time stamping for hook templates (#356 W3, #367)")


def test_vm_shell_port_not_bare_constant() -> None:
    """toolchain.py VM_SHELL_PORT must be env-driven (KUNGLAO_VM_SHELL_PORT),
    same _parse_port defensive pattern as FRIDA_PORT — no bare 9876."""
    src = (ROOT / "scripts" / "toolchain.py").read_text(encoding="utf-8")
    assert "KUNGLAO_VM_SHELL_PORT" in src, \
        "VM_SHELL_PORT must read KUNGLAO_VM_SHELL_PORT (#356 W3)"
    m = re.search(r"^VM_SHELL_PORT\s*=\s*(.+)$", src, re.M)
    assert m, "VM_SHELL_PORT assignment not found"
    assert "_parse_port" in m.group(1), \
        f"VM_SHELL_PORT must use _parse_port, got: {m.group(1)!r}"
