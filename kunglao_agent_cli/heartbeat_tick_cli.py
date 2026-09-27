# -*- coding: utf-8 -*-
"""Console-script wrapper (#416): `heartbeat-tick` -> scripts/heartbeat_tick.py.

Registration only. Mirrors heartbeat_tick.py's own __main__ guard: UTF-8
boot, then main(argv=None).
"""
from __future__ import annotations

from kunglao_agent_cli import load_script_module


def main() -> int:
    load_script_module("_boot.py").force_utf8()  # mirrors heartbeat_tick.py's guard
    return load_script_module("heartbeat_tick.py").main()
