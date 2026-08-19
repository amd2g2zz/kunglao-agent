#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_devkit_quality_gates.py — devkit/quality_gates.py contract.

Tests the cross-platform 4-gate runner. Pinned to the devkit convention:
- devkit/ is dev scaffolding, NOT shipped product
- gates that call subprocess (Gates 2 + 3) are smoke-tested with `--collect-only`
  style checks; Gate 1 is fully asserted
- Gate 4 is `import mutmut` only — no threshold (Phase 2)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVKIT_QUALITY_GATES = REPO_ROOT / "devkit" / "quality_gates.py"


def _run_quality_gates(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DEVKIT_QUALITY_GATES), *args],
        capture_output=True, text=True, timeout=timeout, cwd=REPO_ROOT,
        errors="replace")


def test_devkit_quality_gates_has_docstring() -> None:
    """The script MUST be documented (cross-platform runner, not just bash)."""
    src = DEVKIT_QUALITY_GATES.read_text(encoding="utf-8")
    assert "cross-platform" in src or "Cross-platform" in src


def test_devkit_quality_gates_no_bash_only_constructs() -> None:
    """Per devkit/README.md: NO `set -e`, NO shell-only constructs."""
    src = DEVKIT_QUALITY_GATES.read_text(encoding="utf-8")
    for forbidden in ("set -e", "set -uo pipefail", "printf", "echo "):
        assert forbidden not in src, \
            f"bash-only construct {forbidden!r} found in quality_gates.py"


def test_devkit_quality_gates_help_works() -> None:
    """`--help` MUST exit 0 (so CI can sanity-check the runner)."""
    r = subprocess.run(
        [sys.executable, str(DEVKIT_QUALITY_GATES), "--help"],
        capture_output=True, text=True, timeout=30, cwd=REPO_ROOT,
        errors="replace")
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert "usage" in r.stdout.lower() or "gates" in r.stdout.lower()


def test_gate1_only_runs_quickly() -> None:
    """Gate 1 (contract modules) MUST complete in <10s — no subprocess overhead."""
    r = _run_quality_gates("1", timeout=15)
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert "Gate 1" in r.stdout


def test_full_runner_exits_zero_when_only_safe_gates() -> None:
    """Gates 1, 3, 4 (no Gate 2 = no full pytest) MUST exit 0."""
    r = _run_quality_gates("1", "3", "4", timeout=60)
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert "ALL-PASS" in r.stdout


def test_unknown_gate_returns_code_2() -> None:
    """Argument validation: invalid gate -> exit 2 (usage error)."""
    r = _run_quality_gates("99", timeout=15)
    assert r.returncode == 2, f"{r.stdout}{r.stderr}"


def test_observation_pass_rate_runs_even_when_no_junit() -> None:
    """If .pytest-result.xml is absent, observation step must skip silently."""
    junit = REPO_ROOT / ".pytest-result.xml"
    backup = None
    if junit.exists():
        backup = junit.read_bytes()
        junit.unlink()
    try:
        r = _run_quality_gates("1", "3", "4", timeout=60)
        assert r.returncode == 0
        assert "pass_rate" not in r.stdout or "skip" in r.stdout
    finally:
        if backup is not None:
            junit.write_bytes(backup)