#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_unidbg.py — the registered operator face of the unidbg plan.

The INSTALL_PLANS registry in toolchain_install.py is the single
registration point for tool installation: this entry is a THIN caller of
install_script_plan("unidbg") — resolution (JDK prerequisite check),
implementation execution (install_unidbg.sh: remote clone, first build,
verify-after-repair), and the verify face all live in the registry. The
single source of installation LOGIC stays scripts/install_unidbg.sh.

Usage (mirrors the bash script):
  install_unidbg.py [--target DIR] [--force] [--dry-run]
Exit code propagates from the registry runner (0 green / 1 failed step / 2
usage error).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _boot import force_utf8  # noqa: E402
import toolchain_install  # noqa: E402  (the registry — single registration point)


def main(argv: list[str] | None = None) -> int:
    return toolchain_install.install_script_plan(
        "unidbg", list(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    force_utf8()
    sys.exit(main())
