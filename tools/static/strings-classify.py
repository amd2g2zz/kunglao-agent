#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/strings-classify.py — string entropy/printable/decodable
classification (issue #278 PR-1b).

Absorbed from two accumulation scripts:
- D:/works/samples/2026-06-10/scripts/analyze_decrypted.py — byte Shannon
  entropy + printable ASCII string extraction;
- D:/works/samples/2026-07-01/scripts/floss_filter.py — per-string entropy and
  base64 / hex candidate classification (^[A-Za-z0-9+/]{40,}={0,2}$ /
  ^[0-9a-fA-F]{16,256}$).
Sample-specific dump paths are removed; input, thresholds, and encodings are
CLI arguments.

Usage:
  strings-classify --in sample.bin
  strings-classify --in sample.bin --min-len 6 --encoding ascii
  strings-classify --in sample.bin --json / --reproduce

Classifies each extracted string: Shannon entropy (bits/char), printable ratio,
and decodable flags (base64 / hex candidates, utf-8).  Exit codes: 0 = found
>=1 string, 1 = negative finding, 2 = error (bad args / unreadable input).
Errors print a structured JSON object to stderr: {"error": "...", "exit_code": 2}.
"""
from __future__ import annotations

import argparse
import math
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

# floss_filter.py classification regexes (D:/works/samples/2026-07-01/scripts/).
B64_RE = re.compile(r"^[A-Za-z0-9+/]{40,}={0,2}$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{16,256}$")

ENCODINGS = ("ascii", "utf16le")


def _shannon(data: bytes) -> float:
    """Byte Shannon entropy in bits (analyze_decrypted.py entropy())."""
    if not data:
        return 0.0
    counts: dict[int, int] = {}
    for b in data:
        counts[b] = counts.get(b, 0) + 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    return sum(1 for b in data if 0x20 <= b <= 0x7E) / len(data)


def classify(value: str, offset: int, encoding: str) -> dict:
    raw = value.encode("utf-8", errors="replace")
    return {
        "offset": offset,
        "encoding": encoding,
        "length": len(value),
        "entropy": round(_shannon(raw), 3),
        "printable_ratio": round(_printable_ratio(raw), 3),
        "base64": bool(B64_RE.match(value)),
        "hex": bool(HEX_RE.match(value)),
        "value": value,
    }


def extract_strings(data: bytes, min_len: int, encoding: str) -> list[dict]:
    """Extract printable strings (ASCII and/or UTF-16LE) and classify each."""
    results = []
    if encoding in ("ascii", "both"):
        pat = re.compile(rb"[\x20-\x7e]{%d,}" % max(1, min_len))
        for m in pat.finditer(data):
            value = m.group().decode("ascii", "replace")
            results.append(classify(value, m.start(), "ascii"))
    if encoding in ("utf16le", "both"):
        pat = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % max(1, min_len))
        for m in pat.finditer(data):
            raw = m.group()
            value = raw.decode("utf-16-le", errors="replace")
            results.append(classify(value, m.start(), "utf16le"))
    results.sort(key=lambda item: (item["offset"], item["encoding"]))
    return results


def inventory(strings: list[dict]) -> dict:
    """floss_filter.py-style summary statistics."""
    total = len(strings)
    unique = len({s["value"] for s in strings})
    entropies = [s["entropy"] for s in strings]
    avg = round(sum(entropies) / total, 3) if total else 0.0
    return {
        "total": total,
        "unique": unique,
        "avg_entropy_bits_per_char": avg,
        "max_entropy_bits_per_char": round(max(entropies), 3) if entropies else 0.0,
        "long_strings_count": sum(1 for s in strings if s["length"] >= 32),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="strings-classify",
        description="string entropy/printable/decodable classification "
                    "(issue #278 PR-1b)")
    add_common_flags(ap)
    ap.add_argument("--min-len", type=int, default=4, metavar="N",
                    help="minimum string length (default 4)")
    ap.add_argument("--encoding", choices=("ascii", "utf16le", "both"),
                    default="both",
                    help="string encodings to extract (default both)")
    args = ap.parse_args(argv)

    data = read_bytes(args.in_path)
    input_sha = sha256(data)
    strings = extract_strings(data, args.min_len, args.encoding)

    if not strings:
        return negative(args, "strings-classify", min_len=args.min_len,
                        encoding=args.encoding, total=0)

    inv = inventory(strings)
    text_lines = [
        f"off=0x{s['offset']:x} enc={s['encoding']} len={s['length']} "
        f"entropy={s['entropy']:.3f} printable={s['printable_ratio']:.3f} "
        f"b64={int(s['base64'])} hex={int(s['hex'])} value={s['value']!r}"
        for s in strings
    ]
    json_obj = {
        "tool": "strings-classify",
        "input_sha256": input_sha,
        "min_len": args.min_len,
        "encodings": ENCODINGS if args.encoding == "both" else [args.encoding],
        "inventory": inv,
        "strings": strings,
    }
    reproduce_rows = {
        "tool": "strings-classify",
        "input_sha256": input_sha,
        "min_len": args.min_len,
        "encoding": args.encoding,
        "total": inv["total"],
        "unique": inv["unique"],
        "avg_entropy": inv["avg_entropy_bits_per_char"],
        "max_entropy": inv["max_entropy_bits_per_char"],
        "long_strings": inv["long_strings_count"],
    }
    return report(args, text_lines, json_obj, reproduce_rows)


if __name__ == "__main__":
    sys.exit(main())
