#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_devkit_quality_gates.py — devkit/quality_gates.py contract.

Tests the cross-platform quality-gate runner. The gate count is derived
from the GATES registry and is NEVER hardcoded here (review N4: a
hardcoded "6" next to "the registry is the count's source of truth" is
a self-contradicting drift seed — see
test_gate_registry_lockstep_with_gate_functions). Pinned to the devkit
convention:
- devkit/ is dev scaffolding, NOT shipped product
- gates that call subprocess (Gates 2 + 3) are smoke-tested with `--collect-only`
  style checks; Gate 1 is fully asserted
- Gate 4 is `import mutmut` only — no threshold (Phase 2)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


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


_GATE_FUNC_RE = re.compile(r"^_gate(\d+)_\w+$")


def test_gate_registry_lockstep_with_gate_functions() -> None:
    """GATES registry is the gate count's ONLY source of truth (review N4).

    Derives the count from the module itself — no number is hardcoded in
    this file. Three lockstep faces, all mechanical:
    - every `_gate<N>_*` function defined in the module is registered in
      GATES (a gate implemented but never registered fails here)
    - every GATES entry has an implementation (a dangling registration
      fails here)
    - every registered gate NAME appears in the module docstring, so the
      prose gate list cannot drift from the registry either
    """
    sys.path.insert(0, str(REPO_ROOT / "devkit"))
    import quality_gates as qg  # noqa: E402

    defined: set[int] = set()
    for attr in dir(qg):
        m = _GATE_FUNC_RE.match(attr)
        if m:
            defined.add(int(m.group(1)))
    assert defined, "no _gate<N>_* functions found — import path broken?"
    assert defined == set(qg.GATES), (
        f"_gate<N>_ functions {sorted(defined)} != GATES keys "
        f"{sorted(qg.GATES)} — gate implemented without registration "
        "(or registered without implementation)"
    )
    doc = qg.__doc__ or ""
    for num, (gate_name, _fn) in sorted(qg.GATES.items()):
        assert gate_name in doc, (
            f"gate {num} name {gate_name!r} missing from quality_gates.py "
            "docstring — update the prose gate list when registering a gate"
        )