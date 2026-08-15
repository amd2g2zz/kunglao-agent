# -*- coding: utf-8 -*-
"""Issue #356 W3 — hardcode purge contract.

The pre-#356 tree shipped the original author's machine paths in production
code (C:/Users/hr/...) and a bare VM shell port constant. #356 W3 removes
them: real code paths derive from Path(__file__) or are parameterized,
docstring examples use <HOME>/ placeholders, and VM_SHELL_PORT reads
KUNGLAO_VM_SHELL_PORT (default 9876 — covered in tests/test_toolchain.py).

This file pins the *scan* side (issue acceptance #3:
git grep -E "C:/Users/hr" scripts/ tools/ -> zero hits).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The one author-machine path that must never come back.
_HARDCODED_USER = re.compile(r"C:/Users/hr|C:\\\\Users\\\\hr|C:\\Users\\hr")

# Scanned surfaces: production code + shipped templates (tests may quote the
# banned string while asserting its absence; that is the scan, not a leak).
SCANNED_DIRS = ("scripts", "tools", "templates", "hooks", "agents")


def _scan_hits() -> list[str]:
    hits: list[str] = []
    for d in SCANNED_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if not p.is_file() or p.suffix not in (".py", ".md", ".tmpl",
                                                   ".js", ".yaml", ".yml"):
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if _HARDCODED_USER.search(text):
                hits.append(p.relative_to(ROOT).as_posix())
    return hits


def test_no_hardcoded_author_home_in_production_surfaces() -> None:
    hits = _scan_hits()
    assert not hits, (
        f"author-machine path C:/Users/hr remains in: {hits} — derive from "
        "Path(__file__) or use <HOME> placeholders in docstrings (#356 W3)")


def test_vm_shell_port_not_bare_constant() -> None:
    """toolchain.py VM_SHELL_PORT must be env-driven (KUNGLAO_VM_SHELL_PORT),
    same _parse_port defensive pattern as FRIDA_PORT — no bare 9876."""
    src = (ROOT / "scripts" / "toolchain.py").read_text(encoding="utf-8")
    assert "KUNGLAO_VM_SHELL_PORT" in src, \
        "VM_SHELL_PORT must read KUNGLAO_VM_SHELL_PORT (#356 W3)"
    m = re.search(r"^VM_SHELL_PORT\s*=\s*(.+)$", src, re.M)
    assert m, "VM_SHELL_PORT assignment not found"
    assert "_parse_port" in m.group(1), \
        f"VM_SHELL_PORT must use _parse_port, got: {m.group(1)!r}"
