#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""init_state.py — single source of truth for kunglao init-completeness (#304).

The init-completeness predicate used to be duplicated in three places:
  - scripts/kunglao-init.py   is_init_complete()
  - scripts/env_check.py      check_init_complete()
  - hooks/env_check_gate.py   _check_init_complete()
Drift between the copies would let one gate pass a workspace another rejects.
F6 (#304 review) extracts the predicate here; all three call sites reference
this module.
"""
from __future__ import annotations

from pathlib import Path

VALID_TYPES = ("windows", "linux", "android")
MARKER = "[initialized]"


def read_project_type(ws: Path) -> str | None:
    """Read project_type=<type> from analysis_state.txt (None if absent)."""
    state = ws / "analysis_state.txt"
    if not state.exists():
        return None
    for line in state.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("project_type="):
            return line.split("=", 1)[1].strip()
    return None


def init_complete(ws: Path) -> tuple[bool, str]:
    """#304 predicate: [initialized] marker AND valid project_type declared.

    Returns (complete, detail). When incomplete, detail names the missing
    piece and the fix (run kunglao-init.py <ws> --type <type>).
    """
    reg = ws / "claim-register.yaml"
    if not reg.exists():
        return False, (
            "claim-register.yaml missing — run kunglao-init.py <ws> --type <type>"
        )
    if MARKER not in reg.read_text(encoding="utf-8", errors="replace"):
        return False, (
            "workspace not initialized (no [initialized] marker) — "
            "run kunglao-init.py <ws> --type <type>"
        )
    ptype = read_project_type(ws)
    if ptype is None:
        return False, (
            "project_type not declared in analysis_state.txt — "
            "run kunglao-init.py <ws> --type <type>"
        )
    if ptype not in VALID_TYPES:
        return False, (
            f"invalid project_type={ptype!r} — "
            "run kunglao-init.py <ws> --type <windows|linux|android>"
        )
    return True, f"init complete: project_type={ptype}"


def is_init_complete(ws: Path) -> bool:
    """Convenience boolean form of init_complete()."""
    return init_complete(ws)[0]
