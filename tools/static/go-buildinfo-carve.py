#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/go-buildinfo-carve.py — Go build info carving (issue #278 PR-1b).

Absorbed from:
- D:/works/samples/2026-06-10/evidence/pe-analysis/verify_go_buildinfo.py —
  `Go buildinf` blob location, `path\\t` module line, `dep\\t` dependency
  count, `go1.x.y` version regex;
- D:/works/samples/2026-06-10/scripts/gap_determinative.py — buildinfo end
  detection via a 32-consecutive-null boundary.
Sample-specific hashes/paths are removed; input and window are CLI arguments.

Usage:
  go-buildinfo-carve --in sample.bin
  go-buildinfo-carve --in sample.bin --window 100000 --zero-run 64
  go-buildinfo-carve --in sample.bin --json / --reproduce

Exit codes: 0 = found >=1 buildinfo blob, 1 = negative finding (input scanned,
no blob), 2 = error (bad args / unreadable input).  Errors print a structured
JSON object to stderr: {"error": "...", "exit_code": 2}.
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()


import argparse
import re
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from common import (  # noqa: E402
    add_common_flags,
    negative,
    read_bytes,
    report,
    sha256,
)

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.

MARKER = b"Go buildinf"
GO_VER_RE = re.compile(rb"go(1\.\d+\.?\d*)")
PATH_RE = re.compile(rb"path\t([^\r\n]+)")
MOD_RE = re.compile(rb"mod\t")
DEP_RE = re.compile(rb"dep\t")
BUILD_RE = re.compile(rb"build\t")


def carve(data: bytes, window: int = 50000, zero_run: int = 32) -> list[dict]:
    """Locate every `Go buildinf` marker and parse its metadata block.

    A blob ends at the first run of ``zero_run`` consecutive null bytes within
    ``window`` bytes of the marker (gap_determinative.py boundary heuristic),
    or at the window end when no such run exists.
    """
    blobs = []
    pos = 0
    while True:
        idx = data.find(MARKER, pos)
        if idx < 0:
            break
        end = min(idx + window, len(data))
        run_start = None
        for j in range(idx, end):
            if data[j] == 0:
                if run_start is None:
                    run_start = j
                if j - run_start + 1 >= zero_run:
                    end = run_start
                    break
            else:
                run_start = None
        block = data[idx:end]
        m_ver = GO_VER_RE.search(block)
        m_path = PATH_RE.search(block)
        blobs.append({
            "offset": idx,
            "size": end - idx,
            "go_version": m_ver.group(1).decode("ascii") if m_ver else None,
            "path": m_path.group(1).decode("utf-8", "replace") if m_path else None,
            "mod_count": len(MOD_RE.findall(block)),
            "dep_count": len(DEP_RE.findall(block)),
            "build_count": len(BUILD_RE.findall(block)),
        })
        pos = idx + 1
    return blobs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="go-buildinfo-carve",
        description="Go build info carving (issue #278 PR-1b)")
    add_common_flags(ap)
    ap.add_argument("--window", type=int, default=50000, metavar="N",
                    help="max bytes per blob when no null boundary is found "
                         "(default 50000)")
    ap.add_argument("--zero-run", type=int, default=32, metavar="N",
                    help="consecutive null bytes that end a blob (default 32)")
    args = ap.parse_args(argv)

    data = read_bytes(args.in_path)
    input_sha = sha256(data)
    blobs = carve(data, window=args.window, zero_run=args.zero_run)

    total = len(blobs)
    if not blobs:
        return negative(args, "go-buildinfo-carve", total=0)

    text_lines = [
        f"off=0x{b['offset']:x} go={b['go_version'] or '?'} "
        f"path={b['path'] or '?'} mods={b['mod_count']} deps={b['dep_count']} "
        f"builds={b['build_count']} size={b['size']}"
        for b in blobs
    ]
    json_obj = {
        "tool": "go-buildinfo-carve",
        "input_sha256": input_sha,
        "window": args.window,
        "zero_run": args.zero_run,
        "total": total,
        "blobs": blobs,
    }
    reproduce_rows = {
        "tool": "go-buildinfo-carve",
        "input_sha256": input_sha,
        "total": total,
        "first_offset": hex(blobs[0]["offset"]),
        "first_size": blobs[0]["size"],
        "first_mods": blobs[0]["mod_count"],
        "first_deps": blobs[0]["dep_count"],
    }
    if blobs[0]["go_version"]:
        reproduce_rows["first_go"] = blobs[0]["go_version"]
    if blobs[0]["path"]:
        reproduce_rows["first_path"] = blobs[0]["path"]
    return report(args, text_lines, json_obj, reproduce_rows)


if __name__ == "__main__":
    sys.exit(main())
