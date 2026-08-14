# -*- coding: utf-8 -*-
"""env_file.py — CLAUDE_ENV_FILE loader (issue #309, #304 init linkage).

Absorbed idea: REA SessionStart hook supplying environment from a file,
re-implemented as a stdlib-only pure parser for the kunglao init path. The
#304 init change owns the hook wiring; this module is the single sanctioned
parser so both sides agree on the format:

    # comment lines and blank lines are ignored
    KEY=VALUE            # value may contain spaces; surrounding whitespace trimmed
    EMPTY=               # empty value allowed

Invalid lines (no '=') and NUL bytes raise ValueError — environment must
never be silently half-loaded.
"""
from __future__ import annotations

from pathlib import Path

CLAUDE_ENV_FILE = ".claude-env"


def parse_env_file(text: str) -> dict:
    """Parse KEY=VALUE lines into a dict. Raises ValueError on invalid input."""
    env: dict[str, str] = {}
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\x00" in line:
            raise ValueError(f"env file line {i}: NUL byte rejected")
        if "=" not in line:
            raise ValueError(f"env file line {i}: expected KEY=VALUE, got {line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f"env file line {i}: empty key")
        env[key] = value.strip()
    return env


def load_env_file(path: Path) -> dict:
    """Load an env file; missing file returns {} (never fatal at parse time)."""
    p = Path(path)
    if not p.exists():
        return {}
    return parse_env_file(p.read_text(encoding="utf-8", errors="replace"))
