#!/usr/bin/env python3
"""CI YAML lint — repo-owned so CI 损坏可本地复现（issue #147 P0）。

Parses .github/workflows/*.yml with yaml.safe_load and prints any parse
error with line context. Exit 0 = all parse; 1 = at least one broken.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def main() -> int:
    broken = False
    for p in sorted(WORKFLOWS.glob("*.yml")):
        text = p.read_text(encoding="utf-8")
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            broken = True
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark else "?"
            print(f"YAML BROKEN: {p} line {line}: {exc}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
