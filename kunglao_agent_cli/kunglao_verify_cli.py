# -*- coding: utf-8 -*-
"""Console-script wrapper (#416): `kunglao-verify` -> scripts/kunglao-verify.py.

Registration only. Mirrors kunglao-verify.py's own __main__ guard exactly:
_entry.run(globals()) with no UTF-8 boot (implementation lives in
scripts/kunglao_verify.py; the hyphenated file re-exports its main).
Returning the rc keeps the process exit code identical under the
console-script shim.
"""
from __future__ import annotations

from kunglao_agent_cli import load_script_module


def main() -> int:
    return load_script_module("kunglao-verify.py").main()
