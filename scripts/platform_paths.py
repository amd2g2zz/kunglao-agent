#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""platform_paths.py — cross-platform path resolution for the kunglao toolchain (#409).

Single source of truth for two platform-dependent locations that were
previously hardcoded to their Windows layouts:

  1. Ghidra analyzeHeadless: Windows ships ``support/analyzeHeadless.bat``;
     macOS/Linux ship ``support/analyzeHeadless`` with NO extension. A
     bare ``analyzeHeadless.bat`` constant made exists() always False on
     POSIX (observed on macOS with GHIDRA_HOME set).
  2. venv python: Windows layouts put the interpreter at ``Scripts/python.exe``,
     POSIX at ``bin/python``. The environment init check (env_check.py)
     probed ``<ws>/.venv/Scripts/python.exe`` and always FAILed on macOS.

Both are resolved by ``os.name`` (``'nt'`` = Windows) so callers never
duplicate platform branching. Skill-root helpers exist because the kunglao
venv lives at the SKILL root (uv run --project <skill_root>), NOT the
analysis workspace — see #389.
"""
from __future__ import annotations

import os
from pathlib import Path


def _is_nt() -> bool:
    """True on Windows (the codebase's existing platform predicate — see
    toolchain._run_cmd, test_toolchain platform-aware wrappers)."""
    return os.name == "nt"


def analyze_headless_name() -> str:
    """Platform analyzeHeadless basename: .bat on Windows, no extension on POSIX."""
    return "analyzeHeadless.bat" if _is_nt() else "analyzeHeadless"


def analyze_headless(ghidra_home: str | Path) -> Path:
    """<GHIDRA_HOME>/support/analyzeHeadless(.bat) — the platform-correct
    name under the Ghidra install root. Does NOT check existence (callers
    probe with .exists() / _file_exists)."""
    return Path(ghidra_home) / "support" / analyze_headless_name()


def venv_python_name() -> str:
    """Platform venv interpreter basename: python.exe on Windows, python on POSIX."""
    return "python.exe" if _is_nt() else "python"


def venv_python(venv_root: str | Path) -> Path:
    """The venv interpreter at <venv_root> for the current platform:
    <root>/Scripts/python.exe on Windows, <root>/bin/python on POSIX.

    venv_root is the venv DIRECTORY itself (e.g. <skill_root>/.venv), not the
    project root — uv creates the project venv at <project>/.venv, so callers
    pass ``SKILL_DIR / ".venv"``.
    """
    root = Path(venv_root)
    return root / ("Scripts" if _is_nt() else "bin") / venv_python_name()
