#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_unidbg.py — typed CLI face for scripts/install_unidbg.sh (#165).

The bash installer carries the unidbg deployment preconditions (JDK + Maven
checks, remote clone of the MCP-capable master line, first-build dependency
resolution, verify-after-repair). This wrapper exists so the installer is
reachable through the house tool surface: the ext-index scanner enumerates
scripts/*.py CLIs (type: tool, consume: invoke) and does not enumerate
shell scripts, so the index entry delegates here, and here delegates to the
bash implementation. Single source of logic: scripts/install_unidbg.sh.

Usage mirrors the bash script:
  install_unidbg.py [--target DIR] [--force] [--dry-run]
Exit code propagates from the bash script (0 green / 1 failed step / 2
usage error).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "install_unidbg.sh"


def main(argv: list[str] | None = None) -> int:
    if not _SCRIPT.is_file():
        print(f"install_unidbg: implementation missing: {_SCRIPT}", file=sys.stderr)
        return 1
    try:
        result = subprocess.run(["bash", str(_SCRIPT), *(argv or sys.argv[1:])], check=False)
    except OSError as exc:
        print(f"install_unidbg: cannot execute installer: {exc}", file=sys.stderr)
        return 1
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
