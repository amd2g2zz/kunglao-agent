# -*- coding: utf-8 -*-
"""_hooks_path.py — scripts-side bridge to the hooks/ by-path loader (#863
Family B, #671 authority).

scripts/ and hooks/ are separate sys.path domains (each script runs with its
own directory at sys.path[0]), so the scripts-side former importlib loader
prologues cannot bare-import the hooks/ authority without this one
membership step. The bridge:

  - APPENDS hooks/ (guarded, once) — never insert(0): reordering hooks/
    ahead of scripts/ is the exact shared-name-twin shadow #671 removes
    (completion_gate / heartbeat_touch / lib_kunglao). Appending keeps every
    scripts/ entry ranked above the appended hooks/ entry.
  - re-exports `load_hooks_lib` and `load_module_by_path` from
    hooks/_path_hygiene.py — the ONE importlib.util by-path load site in
    the repo (#863 Family B).

Unique module name across both trees, so the import is order-independent.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HOOKS_DIR = str(Path(__file__).resolve().parent.parent / "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.append(_HOOKS_DIR)

from _path_hygiene import load_hooks_lib, load_module_by_path  # noqa: E402,F401  (#671 authority)
