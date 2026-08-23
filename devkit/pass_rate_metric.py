#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pass_rate_metric.py — extract pass rate from pytest junit XML (#463, D3).

Computes pass_rate = passed / (passed + failed + skipped) × 100%
and writes to stdout (and optionally a file via --out).

Excludes deselected tests (e.g. via -m "not load_sensitive") — those
don't count toward total. Per issue #463 D3 spec: skipped DOES count
(a skipped test is a test not running).

Usage:
  uv run python scripts/pass_rate_metric.py [--out pass-rate.txt]
  # prints "pass_rate=99.06% (2141/2161)" and exits 0 if ≥99%
  # exits 1 if < 99% (CI gate)
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

THRESHOLD = 99.0


def compute(junit_path: Path) -> tuple[float, int, int, int]:
    """Return (pass_rate, passed, failed, skipped) from junit XML.

    JUnit XML schema (pytest --junitxml):
      <testsuite tests="N" failures="F" errors="E" skipped="S" ...>
    """
    tree = ET.parse(junit_path)
    root = tree.getroot()
    tests = int(root.get("tests", 0))
    failures = int(root.get("failures", 0))
    errors = int(root.get("errors", 0))
    skipped = int(root.get("skipped", 0))
    passed = tests - failures - errors - skipped
    if tests == 0:
        return 0.0, 0, 0, 0
    return (passed / tests * 100.0), passed, failures + errors, skipped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--junit", default=".pytest-result.xml", type=Path,
                   help="path to pytest junit XML (default: .pytest-result.xml)")
    p.add_argument("--out", type=Path, default=None,
                   help="write metric line to this file too")
    p.add_argument("--threshold", type=float, default=THRESHOLD,
                   help=f"pass rate threshold (default {THRESHOLD}%)")
    args = p.parse_args(argv)

    if not args.junit.exists():
        print(f"pass_rate_metric: {args.junit} not found", file=sys.stderr)
        return 1

    rate, passed, failed, skipped = compute(args.junit)
    line = (f"pass_rate={rate:.2f}% "
            f"({passed}/{passed + failed + skipped}; "
            f"failed={failed} skipped={skipped})")
    print(line)
    if args.out:
        args.out.write_text(line + "\n", encoding="utf-8")

    if rate < args.threshold:
        print(f"pass_rate_metric: FAIL — {rate:.2f}% < {args.threshold}%",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
