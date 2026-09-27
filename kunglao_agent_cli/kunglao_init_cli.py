# -*- coding: utf-8 -*-
"""Console-script wrapper (#416): `kunglao-init` -> scripts/kunglao-init.py.

Registration only — the hyphenated filename is an illegal module path, so
the target is loaded from its file path. Mirrors kunglao-init.py's own
__main__ guard exactly: _entry.run(globals()) — no UTF-8 boot — which
resolves module main(argv=None) and exits with its rc. Returning the rc
keeps the process exit code identical under the console-script shim.
"""
from __future__ import annotations

from kunglao_agent_cli import load_script_module


def main() -> int:
    return load_script_module("kunglao-init.py").main()
