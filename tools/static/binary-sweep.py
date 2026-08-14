#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/binary-sweep.py — raw byte-pattern sweep with offsets (issue #278 PR-1b).

Absorbed from D:/works/samples/2026-07-01/scripts/binary_sweep.py: the direct
URL / IPv4 / domain byte regexes with validity filters (Go binaries keep static
strings in a runtime table that floss-static sometimes misses).  Generalized
per issue #278: every match reports its file offset, and arbitrary byte
patterns can be swept via --pattern (every occurrence reported, no dedup).

Usage:
  binary-sweep --in sample.bin                   # url+ipv4+domain
  binary-sweep --in sample.bin --kind url
  binary-sweep --in sample.bin --pattern 'S3CR3T'
  binary-sweep --in sample.bin --json / --reproduce

Exit codes: 0 = found >=1 match, 1 = negative finding (input scanned, no
match), 2 = error (bad args / unreadable input).  Errors print a structured
JSON object to stderr: {"error": "...", "exit_code": 2}.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from common import (  # noqa: E402
    add_common_flags,
    error,
    negative,
    read_bytes,
    report,
    sha256,
)

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

URL = re.compile(rb"https?://[a-zA-Z0-9./_:%?=&@#~+\-,;()\[\]!$]{4,300}")
IPV4 = re.compile(rb"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b")
DOMAIN = re.compile(
    rb"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    rb"(?:com|net|org|io|app|dev|xyz|biz|info|cloud|win|store|top|club|site|"
    rb"online|me|tv|cn|ru|de|fr|jp|uk|as|asia|wiki|edu|gov|mil|space)"
    rb"(?::\d{1,5})?\b", re.I)

BUILTIN_PATTERNS = {"url": URL, "ipv4": IPV4, "domain": DOMAIN}
KINDS = ("url", "ipv4", "domain")
BAD_TAIL = (",", ";", "<", ">", '"', "'", "\\")


def _valid_ipv4(host_part: str) -> bool:
    octets = host_part.split(".")
    if len(octets) != 4:
        return False
    try:
        return all(0 <= int(o) <= 255 for o in octets)
    except ValueError:
        return False


def sweep_kind(data: bytes, kind: str) -> list[dict]:
    """Built-in sweep for ``kind``: unique values with first-offset reporting."""
    matches = []
    seen = set()
    for m in BUILTIN_PATTERNS[kind].finditer(data):
        raw = m.group(0)
        if raw in seen:
            continue
        seen.add(raw)
        value = raw.decode("ascii", "replace")
        if kind == "url" and (value.endswith(BAD_TAIL)
                              or not (4 <= len(value) <= 250)):
            continue
        if kind == "ipv4" and not _valid_ipv4(value.split(":", 1)[0]):
            continue
        if kind == "domain" and (value.endswith(BAD_TAIL) or len(value) > 200):
            continue
        matches.append({"offset": m.start(), "value": value})
    return matches


def sweep_pattern(data: bytes, pattern: str) -> list[dict]:
    """Custom sweep: report every occurrence (no dedup, no filtering)."""
    try:
        compiled = re.compile(pattern.encode("ascii"))
    except (UnicodeEncodeError, re.error) as exc:
        error(f"invalid --pattern {pattern!r}: {exc} — give an ASCII regex "
              f"applied to raw bytes")
    return [{"kind": "pattern", "offset": m.start(),
             "value": m.group(0).decode("ascii", "replace")}
            for m in compiled.finditer(data)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="binary-sweep",
        description="raw byte-pattern sweep with offsets (issue #278 PR-1b)")
    add_common_flags(ap)
    ap.add_argument("--kind", choices=("url", "ipv4", "domain", "all"),
                    default="all", help="built-in pattern family (default all)")
    ap.add_argument("--pattern", metavar="REGEX",
                    help="custom byte regex (ASCII, raw bytes); overrides "
                         "--kind, reports every occurrence")
    ap.add_argument("--max", type=int, default=60, dest="max_lines",
                    metavar="N",
                    help="cap of printed matches per kind in text mode "
                         "(default 60)")
    args = ap.parse_args(argv)

    data = read_bytes(args.in_path)
    input_sha = sha256(data)

    if args.pattern:
        matches = sweep_pattern(data, args.pattern)
        kinds = ["pattern"]
    else:
        selected = KINDS if args.kind == "all" else [args.kind]
        matches = []
        for kind in selected:
            for m in sweep_kind(data, kind):
                matches.append({"kind": kind, **m})
        kinds = selected

    if not matches:
        return negative(args, "binary-sweep", kinds=",".join(kinds), total=0)

    counts = {k: sum(1 for m in matches if m["kind"] == k) for k in kinds}
    text_lines = []
    for kind in kinds:
        for m in [x for x in matches if x["kind"] == kind][: args.max_lines]:
            text_lines.append(f"{kind}@{m['offset']:#x}: {m['value']}")
    json_obj = {
        "tool": "binary-sweep",
        "input_sha256": input_sha,
        "kinds": kinds,
        "counts": counts,
        "matches": [{"kind": m["kind"], "offset": m["offset"],
                     "value": m["value"]} for m in matches],
    }
    reproduce_rows = {
        "tool": "binary-sweep",
        "input_sha256": input_sha,
        "kinds": ",".join(kinds),
        "total": len(matches),
    }
    for kind in kinds:
        reproduce_rows[f"count_{kind}"] = counts[kind]
    first = matches[0]
    reproduce_rows["first_offset"] = hex(first["offset"])
    reproduce_rows["first_value"] = first["value"]
    return report(args, text_lines, json_obj, reproduce_rows)


if __name__ == "__main__":
    sys.exit(main())
