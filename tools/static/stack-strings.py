#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/stack-strings.py — stack-constructed string detection (issue #278 PR-1b).

Absorbed from D:/works/samples/2026-06-10/scripts/check_stack_strings.py: the
`mov byte ptr [rsp+disp], imm8` (C6 44 24 disp val) scan that reconstructs
per-slot character strings written onto the stack — a classic shellcode string
construction idiom.  Sample-specific paths and hardcoded function offsets are
removed; the input and optional region bounds are CLI arguments.

Usage:
  stack-strings --in shellcode.bin
  stack-strings --in shellcode.bin --start 0x1000 --end 0x2000 --dword
  stack-strings --in shellcode.bin --json / --reproduce

Exit codes: 0 = found >=1 slot string, 1 = negative finding (input scanned, no
slot string), 2 = error (bad args / unreadable input).  Errors print a
structured JSON object to stderr: {"error": "...", "exit_code": 2}.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from common import (  # noqa: E402
    add_common_flags,
    error,
    negative,
    parse_int,
    read_bytes,
    report,
    sha256,
)

MOV_BYTE_RSP = b"\xc6\x44\x24"   # mov byte ptr [rsp+disp8], imm8
MOV_DWORD_RSP = b"\xc7\x44\x24"  # mov dword ptr [rsp+disp8], imm32


def scan(data: bytes, with_dword: bool = False) -> list[dict]:
    """Yield (offset, disp, value, width) per stack write: byte writes always,
    dword writes only when ``with_dword``."""
    writes = []
    n = len(data)
    i = 0
    while i < n:
        if data[i : i + 3] == MOV_BYTE_RSP and i + 5 <= n:
            writes.append({"offset": i, "disp": data[i + 3],
                           "value": data[i + 4], "width": 1})
            i += 5
            continue
        if with_dword and data[i : i + 3] == MOV_DWORD_RSP and i + 8 <= n:
            val = int.from_bytes(data[i + 4 : i + 8], "little")
            writes.append({"offset": i, "disp": data[i + 3],
                           "value": val, "width": 4})
            i += 8
            continue
        i += 1
    return writes


def build_strings(writes: list[dict], min_len: int) -> list[dict]:
    """Group writes per [rsp+disp] slot and reconstruct the char string in
    write order (non-printable bytes become '.')."""
    slots: dict[int, list[dict]] = {}
    for w in writes:
        slots.setdefault(w["disp"], []).append(w)
    out = []
    for disp, ws in sorted(slots.items()):
        chars = []
        for w in ws:
            if w["width"] == 1:
                chars.append(chr(w["value"]) if 32 <= w["value"] < 127 else ".")
            else:
                for shift in (0, 8, 16, 24):
                    c = (w["value"] >> shift) & 0xFF
                    chars.append(chr(c) if 32 <= c < 127 else ".")
        value = "".join(chars)
        if len(value) >= min_len:
            out.append({"slot": disp, "value": value, "writes": len(ws)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="stack-strings",
        description="detect stack-constructed strings (issue #278 PR-1b)")
    add_common_flags(ap)
    ap.add_argument("--start", metavar="OFF",
                    help="region start offset (0x hex or decimal, default 0)")
    ap.add_argument("--end", metavar="OFF",
                    help="region end offset (0x hex or decimal, default = EOF)")
    ap.add_argument("--min-len", type=int, default=2, metavar="N",
                    help="minimum reconstructed string length to report "
                         "(default 2)")
    ap.add_argument("--dword", action="store_true",
                    help="also detect `mov dword ptr [rsp+disp], imm32` "
                         "(C7 44 24 disp imm32)")
    args = ap.parse_args(argv)

    data = read_bytes(args.in_path)
    start = parse_int(args.start, "--start") if args.start else 0
    end = parse_int(args.end, "--end") if args.end else len(data)
    if start < 0 or end > len(data) or start > end:
        error(f"invalid region --start {args.start} --end {args.end}: file has "
              f"{len(data)} bytes — give 0 <= start <= end <= file size")
    region = data[start:end]

    strings = build_strings(scan(region, with_dword=args.dword), args.min_len)
    total = len(strings)
    input_sha = sha256(data)
    if not strings:
        return negative(args, "stack-strings", region_start=hex(start),
                        region_end=hex(end), total=0)

    text_lines = [f"slot=0x{s['slot']:x} value={s['value']!r} "
                  f"writes={s['writes']}" for s in strings]
    json_obj = {
        "tool": "stack-strings",
        "input_sha256": input_sha,
        "region": {"start": start, "end": end},
        "dword": args.dword,
        "total": total,
        "strings": [{"slot": s["slot"], "value": s["value"],
                     "writes": s["writes"]} for s in strings],
    }
    reproduce_rows = {
        "tool": "stack-strings",
        "input_sha256": input_sha,
        "region_start": hex(start),
        "region_end": hex(end),
        "dword": 1 if args.dword else 0,
        "total": total,
        "slots": ",".join(f"0x{s['slot']:x}" for s in strings),
    }
    return report(args, text_lines, json_obj, reproduce_rows)


if __name__ == "__main__":
    sys.exit(main())
