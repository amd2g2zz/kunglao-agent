#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_devkit_pass_rate_metric.py — devkit/pass_rate_metric.py contract.

JUnit XML schema (pytest --junitxml):
  <testsuite tests="N" failures="F" errors="E" skipped="S" ...>
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PASS_RATE = REPO_ROOT / "devkit" / "pass_rate_metric.py"


def _write_junit(tmp_path: Path, tests: int, failures: int = 0,
                 errors: int = 0, skipped: int = 0) -> Path:
    """Write a fake junit XML file for testing."""
    p = tmp_path / "junit.xml"
    p.write_text(
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<testsuite name="x" tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}" time="0">'
        f'</testsuite>',
        encoding="utf-8")
    return p


def test_compute_basic(tmp_path: Path) -> None:
    """Tests/Failures/Errors/Skipped are parsed correctly."""
    sys.path.insert(0, str(REPO_ROOT / "devkit"))
    from pass_rate_metric import compute

    p = _write_junit(tmp_path, tests=10, failures=1, skipped=2)
    rate, passed, failed, skipped = compute(p)
    # passed = 10 - 1 - 0 - 2 = 7
    assert passed == 7
    assert failed == 1
    assert skipped == 2
    assert abs(rate - 70.0) < 0.01


def test_compute_zero_tests(tmp_path: Path) -> None:
    """No tests run = 0% pass rate, no crash."""
    sys.path.insert(0, str(REPO_ROOT / "devkit"))
    from pass_rate_metric import compute

    p = _write_junit(tmp_path, tests=0)
    rate, passed, _, _ = compute(p)
    assert rate == 0.0
    assert passed == 0


def test_compute_all_passing(tmp_path: Path) -> None:
    """100% pass rate when no failures/errors/skipped."""
    sys.path.insert(0, str(REPO_ROOT / "devkit"))
    from pass_rate_metric import compute

    p = _write_junit(tmp_path, tests=5)
    rate, passed, _, _ = compute(p)
    assert rate == 100.0
    assert passed == 5


def test_cli_missing_junit_exits_1(tmp_path: Path) -> None:
    """Missing junit file = exit 1 (CI gate signal)."""
    fake_junit = tmp_path / "nonexistent.xml"
    r = subprocess.run(
        [sys.executable, str(PASS_RATE), "--junit", str(fake_junit)],
        capture_output=True, text=True, timeout=15,
        errors="replace")
    assert r.returncode == 1, f"{r.stdout}{r.stderr}"
    assert "not found" in r.stderr.lower()


def test_cli_below_99_fails(tmp_path: Path) -> None:
    """Pass rate <99% MUST exit 1 (gate enforcement)."""
    junit = _write_junit(tmp_path, tests=10, failures=2, skipped=0)  # 80%
    r = subprocess.run(
        [sys.executable, str(PASS_RATE),
         "--junit", str(junit), "--threshold", "99"],
        capture_output=True, text=True, timeout=15, errors="replace")
    assert r.returncode == 1, f"{r.stdout}{r.stderr}"
    assert "FAIL" in r.stderr


def test_cli_at_99_passes(tmp_path: Path) -> None:
    """Pass rate ==99% (boundary, ≤threshold) MUST exit 0."""
    junit = _write_junit(tmp_path, tests=100, failures=1)  # 99%
    r = subprocess.run(
        [sys.executable, str(PASS_RATE),
         "--junit", str(junit), "--threshold", "99"],
        capture_output=True, text=True, timeout=15, errors="replace")
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert "pass_rate=99.00%" in r.stdout


def test_cli_writes_out_file(tmp_path: Path) -> None:
    """`--out` flag MUST write metric line to the given file."""
    junit = _write_junit(tmp_path, tests=10)
    out = tmp_path / "out.txt"
    r = subprocess.run(
        [sys.executable, str(PASS_RATE),
         "--junit", str(junit), "--out", str(out), "--threshold", "50"],
        capture_output=True, text=True, timeout=15, errors="replace")
    assert r.returncode == 0
    assert out.read_text(encoding="utf-8").startswith("pass_rate=")