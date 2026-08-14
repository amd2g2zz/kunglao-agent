#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/common.py — shared CLI plumbing for the tools/static CLIs.

Issue #278 PR-1b absorbs 6 zero-dependency static-analysis CLIs into
tools/static/.  This module holds the #277 CLI-checklist mechanics they all
reuse (not a tool itself — not registered in tools/_INDEX.yaml):

  - structured error JSON on stderr with guidance, exit code 2
  - three-state exit codes: 0 = ok, 1 = negative finding (ran, no result),
    2 = error (bad args / unreadable input) — mirrors tools/crypto/crypto-tool.py
  - default text output: one line per result
  - --json: a single JSON object on stdout
  - --reproduce: field=value lines for the kunglao L1 mechanical gate
    (keys must match `^[A-Za-z_][\\w.]*[:=]`, see scripts/kunglao_verify.py)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# r2-278-1b H1: decoded binary content can carry U+FFFD (decode(errors="replace"));
# a GBK console (Windows) cannot encode it and a bare UnicodeEncodeError traceback
# would break the "structured error, never a traceback" CLI contract. Emit with
# errors="replace" so output never crashes on console encoding.
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

EXIT_OK = 0
EXIT_NEGATIVE = 1
EXIT_ERROR = 2

# kunglao L1 mechanical gate: field=value lines.
L1_FIELD_RE = re.compile(r"^[A-Za-z_][\w.]*[:=]")


def error(message: str, code: int = EXIT_ERROR) -> None:
    """Print a structured error JSON to stderr and exit with ``code``."""
    print(json.dumps({"error": message, "exit_code": code}), file=sys.stderr)
    sys.exit(code)


def add_common_flags(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--in", dest="in_path", metavar="PATH",
                    help="input file to analyze (required)")
    ap.add_argument("--json", action="store_true",
                    help="emit a single JSON object on stdout")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value lines for the kunglao L1 "
                         "mechanical gate")


def read_bytes(path: str | None, flag: str = "--in") -> bytes:
    """Read the input file; exit 2 with guidance when missing/unreadable."""
    if not path:
        error(f"missing input: {flag} PATH is required (see --help)")
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        error(f"cannot read {flag} {path}: {exc} — check the path exists and "
              f"is readable")


def read_text(path: str | None, flag: str = "--in") -> str:
    """Read the input file as text; exit 2 with guidance when unreadable."""
    if not path:
        error(f"missing input: {flag} PATH is required (see --help)")
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        error(f"cannot read {flag} {path}: {exc} — check the path exists and "
              f"is readable")


def parse_int(value: str, flag: str) -> int:
    """Parse a decimal or 0x-hex integer; exit 2 with guidance on failure."""
    try:
        return int(value, 0)
    except ValueError:
        error(f"invalid {flag} value {value!r}: expected an integer "
              f"(decimal or 0x-prefixed hex)")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_line(line: str) -> tuple[str | None, str]:
    """Split a disassembly listing line into (address, instruction text).

    A leading token is treated as an address only when 0x-prefixed, followed
    by ':'/'|', or at least 4 hex digits — so short mnemonics like ``add`` or
    ``bad`` are not misread as addresses.  Lines without an address map to
    (None, stripped_line).
    """
    m = re.match(r"^\s*(?:(0x[0-9a-fA-F]+)|([0-9a-fA-F]{4,}))\s*[:|]?\s+(.+)$", line)
    if m:
        return (m.group(1) or m.group(2)), m.group(3)
    return None, line.strip()


def report(args, text_lines: list[str], json_obj: dict,
           reproduce_rows: dict) -> int:
    """Emit per the #277 contract: --reproduce > --json > one line per result."""
    if args.reproduce:
        for key, value in reproduce_rows.items():
            print(f"{key}={value}")
    elif args.json:
        print(json.dumps(json_obj, ensure_ascii=False))
    else:
        for line in text_lines:
            print(line)
    return EXIT_OK


def negative(args, tool: str, **rows) -> int:
    """Negative finding: input scanned, nothing found (exit 1)."""
    data = {"tool": tool, "status": "NEGATIVE"}
    data.update(rows)
    if args.json and not args.reproduce:
        print(json.dumps(data, ensure_ascii=False))
    else:
        for key, value in data.items():
            print(f"{key}={value}")
    return EXIT_NEGATIVE
