# -*- coding: utf-8 -*-
"""Console-script wrapper (#416): `kunglao-upgrade` -> scripts/kunglao_upgrade.py.

Registration only. The issue's naming table says `kunglao-upgrade`; the
backing file in reality is the underscore module (no kunglao-upgrade.py
exists). Mirrors kunglao_upgrade.py's own __main__ guard: UTF-8 boot, then
main(argv=None).
"""
from __future__ import annotations

from kunglao_agent_cli import load_script_module


def main() -> int:
    load_script_module("_boot.py").force_utf8()  # mirrors kunglao_upgrade.py's guard
    return load_script_module("kunglao_upgrade.py").main()
