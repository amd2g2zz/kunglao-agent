#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.8.x enforcement-gates smoke launcher (issue #230 scripts governance).

SKILL.md documents the smoke gate as `python scripts/test_v1_8_enforcement_gates.py`;
the suite itself lives in tests/test_v1_8_enforcement_gates.py (migrated from
scripts/ in refactor #128 / #174). This thin wrapper runs that suite through
pytest so the documented command keeps working.

Exit 0 if all pass, 1 if any fail.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "tests" / "test_v1_8_enforcement_gates.py"


def main() -> int:
    return subprocess.call([sys.executable, "-m", "pytest", str(SUITE), "-q"], cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
