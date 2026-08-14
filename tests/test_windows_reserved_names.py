# -*- coding: utf-8 -*-
"""Windows reserved device names guard (#317, #314 A3): no repo path
component may be a DOS device name (AUX / CON / NUL / PRN / COM1-9 /
LPT1-9).

Background: on Windows, git cannot even track a path like ``tools/aux/``
(AUX is a reserved device name) — issue #307's agent created
tools/aux/sanitize.py and ``git add`` failed. The rename precedent is
``tools/auxiliary/``. A Linux checkout would not be blocked by the OS, so
this test is the portable mechanical guard.

Rule: for directories the full name is checked; for files the stem is
checked (``aux.py`` is reserved too). Matching is case-insensitive and
case-preserving-agnostic (Windows is case-insensitive here).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_RESERVED = {"con", "prn", "aux", "nul"} | \
    {f"com{i}" for i in range(1, 10)} | \
    {f"lpt{i}" for i in range(1, 10)}


def test_no_windows_reserved_device_names():
    violators = []
    for p in sorted(ROOT.rglob("*")):
        if ".git" in p.parts:
            continue
        name = p.stem.lower() if p.is_file() else p.name.lower()
        if name in _RESERVED:
            violators.append(str(p.relative_to(ROOT)))
    assert not violators, (
        f"{len(violators)} path(s) use a Windows reserved device name "
        f"(git cannot track them on Windows; use tools/auxiliary/ etc.):\n" +
        "\n".join(f"  {v}" for v in violators)
    )
