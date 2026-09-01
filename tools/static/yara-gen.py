#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/yara-gen.py — generate a YARA rule from a byte pattern or
string (issue #313, kunglao-native extension — the REVERSE direction of
yara-scan: analysis findings become detection rules).

Round-trip contract: a generated rule, fed back to yara-scan against a blob
containing the pattern, MUST hit (test_yara_tools.py asserts this).

Contract (#277): --hex or --string (one required), --name, --meta k=v pairs;
YARA rule text on stdout; exit 0 generated / 2 error with guidance.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402

EXIT_OK = 0
EXIT_NEGATIVE = 1
EXIT_ERROR = 2

META_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _error(msg: str) -> int:
    print(json.dumps({"error": msg, "exit_code": EXIT_ERROR}), file=sys.stderr)
    return EXIT_ERROR


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="yara-gen.py",
        description="generate a YARA rule from a hex pattern or string "
                    "(issue #313)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--hex", metavar="HEX",
                   help="byte pattern as hex (wildcards ? and ?? allowed)")
    g.add_argument("--string", metavar="TEXT",
                   help="literal text pattern (auto-escaped)")
    ap.add_argument("--name", required=True,
                    help="rule name (identifier: [A-Za-z_][A-Za-z0-9_]*)")
    ap.add_argument("--meta", action="append", default=[],
                    metavar="K=V",
                    help="rule meta entry (repeatable), e.g. "
                         "--meta sha256=<x> --meta source=C-011")
    ap.add_argument("--wide", action="store_true",
                    help="also match UTF-16LE form (ascii wide alternative)")
    return ap.parse_args(argv)


def _hex_wildcards(pattern: str) -> str:
    """Normalize user hex into yara hex-string syntax (spaces every byte)."""
    cleaned = re.sub(r"\s+", "", pattern)
    if not re.fullmatch(r"[0-9a-fA-F?]+", cleaned):
        raise ValueError(
            f"--hex contains non-hex characters: {pattern!r} — allowed: "
            f"hex digits and ? wildcards")
    if len(cleaned) % 2 != 0:
        raise ValueError(
            f"--hex has odd digit count ({len(cleaned)}) — pad with a leading 0")
    return " ".join(cleaned[i:i + 2] for i in range(0, len(cleaned), 2))


def _escaped_ascii(text: str) -> str:
    """Escape a string for a YARA double-quoted string: printable ASCII kept,
    everything else as UTF-8 byte escapes (\\xNN per byte — a non-ASCII char
    like 中文 must become its full UTF-8 sequence, not a truncated byte)."""
    out = []
    for ch in text:
        if 32 <= ord(ch) < 127 and ch not in '\\"':
            out.append(ch)
        else:
            out.extend(f"\\x{b:02x}" for b in ch.encode("utf-8"))
    return "".join(out)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.name):
        return _error(f"--name {args.name!r} is not a valid rule identifier — "
                      f"use [A-Za-z_][A-Za-z0-9_]*")

    meta_lines = ["author = \"kunglao-agent yara-gen\""]
    for entry in args.meta:
        m = META_KEY_RE.match(entry)
        if not m:
            return _error(f"--meta entry {entry!r} is not K=V with an "
                          f"identifier key — e.g. --meta sha256=deadbeef")
        key, value = m.group(1), m.group(2)
        # r1-313-yara H2: an unescaped quote in the value would produce
        # uncompilable YARA — escape backslashes and quotes.
        value = value.replace("\\", "\\\\").replace('"', '\\"')
        meta_lines.append(f"{key} = \"{value}\"")

    if args.hex:
        try:
            hex_pat = _hex_wildcards(args.hex)
        except ValueError as exc:
            return _error(str(exc))
        strings_block = f"        $s0 = {{ {hex_pat} }}"
        condition_extra = "$s0"
    else:
        if not args.string:
            return _error("one of --hex / --string is required")
        esc = _escaped_ascii(args.string)
        if args.wide:
            strings_block = (f"        $s0 = \"{esc}\"\n"
                             f"        $s0w = \"{esc}\" wide")
            condition_extra = "any of them"
        else:
            strings_block = f"        $s0 = \"{esc}\""
            condition_extra = "$s0"

    rule = (
        f"rule {args.name} {{\n"
        f"    meta:\n"
        + "".join(f"        {line}\n" for line in meta_lines) +
        f"    strings:\n"
        f"{strings_block}\n"
        f"    condition:\n"
        f"        {condition_extra}\n"
        f"}}\n"
    )
    print(rule, end="")
    return EXIT_OK


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
