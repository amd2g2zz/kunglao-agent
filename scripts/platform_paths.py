#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""platform_paths.py — cross-platform path resolution for the kunglao toolchain (#409).

Single source of truth for platform-dependent locations that were previously
hardcoded to their Windows layouts:

  Ghidra analyzeHeadless: Windows ships ``support/analyzeHeadless.bat``;
  macOS/Linux ship ``support/analyzeHeadless`` with NO extension. A bare
  ``analyzeHeadless.bat`` constant made exists() always False on POSIX
  (observed on macOS with GHIDRA_HOME set).

Resolved by ``os.name`` (``'nt'`` = Windows) so callers never duplicate
platform branching.

issue 207: the venv-interpreter helpers (venv_python / venv_python_name) were
removed — the environment check probes the SKILL-root uv project through
``uv run --project <skill_root>`` (uv owns the interpreter path), so no caller
needs platform venv-layout knowledge anymore.
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
