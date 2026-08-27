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

import json
from datetime import datetime, timezone
from pathlib import Path

# #728: "web" is the labs browser-JS type (WARN-only toolchain face,
# docker-default channel — see openspec/changes/issue-728-web-labs-type).
# #760: "macos" is the labs Mach-O type (same WARN-only lab shape — otool/
# class-dump presence probes, no VM channel; openspec/changes/issue-760-dispatch-tools).
VALID_TYPES = ("windows", "linux", "android", "web", "macos")
MARKER = "[initialized]"
# #625: the dedicated state file is the PRIMARY init-completeness truth —
# a text-editor rewrite of the YAML comment can no longer silently drop it.
# The YAML marker stays as a legacy fallback for pre-#625 workspaces.
STATE_FILE = ".kunglao-init.json"


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_init_marker(ws: Path, *, state_hash: str, project_type: str,
                      seed_count: int) -> dict:
    """#625: persist init-completeness into a dedicated JSON state file.

    Fields: state_hash / project_type / seed_count / ts (ISO8601 Z). Fail-loud
    on invalid type so init never writes a marker the predicate will reject."""
    if project_type not in VALID_TYPES:
        raise ValueError(f"project_type {project_type!r} not in {VALID_TYPES}")
    record = {
        "state_hash": state_hash,
        "project_type": project_type,
        "seed_count": seed_count,
        "ts": _utc_now(),
    }
    (Path(ws) / STATE_FILE).write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def _read_init_marker(ws: Path) -> dict | None:
    path = Path(ws) / STATE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


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
    """#304 predicate: initialized (marker) AND valid project_type declared.

    #625: PRIMARY truth is .kunglao-init.json (survives YAML rewrites); the
    YAML `[initialized]` comment is the legacy fallback (one version window).
    Returns (complete, detail). When incomplete, detail names the missing
    piece and the fix (run kunglao-init.py <ws> --type <type>).
    """
    marker = _read_init_marker(ws)
    if marker is not None:
        ptype = marker.get("project_type")
        if ptype not in VALID_TYPES:
            return False, (
                f"invalid project_type={ptype!r} — "
                "run kunglao-init.py <ws> --type <windows|linux|android|web|macos>"
            )
        return True, f"init complete: project_type={ptype} (state file)"
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
            "run kunglao-init.py <ws> --type <windows|linux|android|web|macos>"
        )
    return True, f"init complete: project_type={ptype}"


def is_init_complete(ws: Path) -> bool:
    """Convenience boolean form of init_complete()."""
    return init_complete(ws)[0]
