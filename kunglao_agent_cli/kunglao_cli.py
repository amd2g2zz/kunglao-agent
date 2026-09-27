# -*- coding: utf-8 -*-
"""Console-script wrapper (#416): `kunglao` -> scripts/kunglao.py.

Registration only — the router keeps its module-level main(); this wrapper
mirrors kunglao.py's own __main__ guard (UTF-8 boot, then main()) so
`kunglao ...` behaves exactly like `python scripts/kunglao.py ...`.
"""
from __future__ import annotations

from kunglao_agent_cli import load_script_module


def main() -> int:
    load_script_module("_boot.py").force_utf8()  # mirrors kunglao.py's guard
    return load_script_module("kunglao.py").main()
