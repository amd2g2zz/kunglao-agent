# -*- coding: utf-8 -*-
"""Console-script wrapper (#416): `convergence-check` -> scripts/convergence_check.py.

Registration only. Mirrors convergence_check.py's own __main__ guard: UTF-8
boot, then main(argv=None).
"""
from __future__ import annotations

from kunglao_agent_cli import load_script_module


def main() -> int:
    load_script_module("_boot.py").force_utf8()  # mirrors convergence_check.py's guard
    return load_script_module("convergence_check.py").main()
