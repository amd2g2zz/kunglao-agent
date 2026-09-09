#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_boot.py — THE CLI boot module (single home of entry-time insurance).

Every script entry used to carry its own slice of boot machinery: the
utf8 stdio module, per-file try/reconfigure blocks, and the
script-directory sys.path prologue. This module is their one home:

  force_utf8()               PYTHONUTF8 setdefault + stdout/stderr
                             reconfigure (subprocess tree + console)
  ensure_utf8_stderr(s)      stderr unified to utf-8/replace, fail-open
  reconfigure_stdout()       stdout-only reconfigure, fail-open (the
                             scoped CLI-face pattern: importing a module
                             must never mutate the importer's stdout)
  ensure_own_dir_on_path()   guard-insert this directory at sys.path[0]
                             so sibling imports resolve for every
                             invocation style (direct, by path, pytest)

Usage (entry scripts):
    if __name__ == "__main__":
        from _boot import force_utf8
        force_utf8()
        sys.exit(main())

Import-order rule: _boot imports NOTHING from its own directory — it is
the first module an entry loads and must stay dependency-free.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_APPLIED = False


def force_utf8() -> None:
    """Idempotent: repeat calls are no-ops. Any failure is swallowed —
    an insurance layer never blocks the entry."""
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True
    try:
        os.environ.setdefault("PYTHONUTF8", "1")
    except Exception:  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def ensure_utf8_stderr(stream=None) -> bool:
    """stderr unified to utf-8/replace (stdout already is).

    A GBK-default stderr next to a utf-8 stdout garbles the mixed terminal
    stream. Fail-open on streams without reconfigure (returns False,
    never raises)."""
    target = sys.stderr if stream is None else stream
    reconfigure = getattr(target, "reconfigure", None)
    if reconfigure is None:
        return False
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        return False
    return True


def reconfigure_stdout() -> bool:
    """stdout-only reconfigure, fail-open (bool = whether it applied).

    The scoped CLI-face pattern: several CLIs reconfigure INSIDE main()
    (or at module import) so that importing the module never mutates the
    importer's stdout, and so captured streams (pytest capsys) are
    tolerated instead of raising."""
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return False
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        return False
    return True


def ensure_own_dir_on_path() -> None:
    """Guard-insert THIS directory at sys.path[0].

    The prologue every entry carried by hand (`if str(SCRIPTS) not in
    sys.path: sys.path.insert(0, ...)`) so sibling imports resolve for
    every invocation style: direct, by absolute path, pytest."""
    here = str(Path(__file__).resolve().parent)
    # drop EVERY occurrence (an ambient duplicate anywhere would shadow the
    # front-of-path guarantee), then insert exactly once at [0]
    sys.path[:] = [p for p in sys.path if p != here]
    sys.path.insert(0, here)
