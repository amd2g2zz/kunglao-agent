#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/shellcode_scan.py — shellcode blob scanner CLI (issue #278 PR-1c).

Absorbed from the shellcode-extraction parts of
D:/works/samples/2026-06-10/scripts/disasm_stage3.py (entry disassembly,
prolog scan, string extraction), extended with a capstone code-region scan
and PEB-access detection: given any binary blob (decoded stage, section dump,
or a full PE), locate and characterize shellcode.

#277 contract: parameterized (--binary + operation flags), read-only +
deterministic (idempotent), three-state exit codes, --json (default single
JSON object), --reproduce field=value lines (kunglao L1 gate), errors carry
guidance.

Exit codes:
  0 = at least one requested operation found results;
  1 = negative finding (all requested operations ran but found nothing);
  2 = operational error (missing file, no operation requested, bad args).

Usage:
  python shellcode_scan.py --binary stage3_xor_decoded.bin --scan --prologs --strings
  python shellcode_scan.py --binary blob.bin --entry 0x448 --peb --reproduce
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import capstone

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from _common import (  # noqa: E402
    PEB_ACCESS_PATTERNS,
    ascii_strings,
    find_all,
    x64_prolog_offsets,
)

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

DEFAULT_LENGTH = 512
DEFAULT_STEP = 16
DEFAULT_MIN_RATIO = 0.6
DEFAULT_MIN_INSNS = 5
DEFAULT_MIN_STRING_LEN = 6
DEFAULT_MAX_STRINGS = 100


def _error(code: int, message: str) -> None:
    print(json.dumps({"error": message, "exit_code": code}), file=sys.stderr)
    sys.exit(code)


def _disasm_entry(data: bytes, entry: int, base: int, length: int, bits: int) -> dict:
    mode = capstone.CS_MODE_64 if bits == 64 else capstone.CS_MODE_32
    md = capstone.Cs(capstone.CS_ARCH_X86, mode)
    insns = []
    for ins in md.disasm(data[entry:entry + length], base + entry):
        insns.append({
            "addr": hex(ins.address),
            "mnemonic": ins.mnemonic,
            "op_str": ins.op_str,
            "bytes": " ".join(f"{b:02x}" for b in ins.bytes),
        })
    return {"entry": hex(entry), "base": hex(base),
            "instructions": insns, "count": len(insns)}


def _scan_regions(data: bytes, bits: int, window: int, step: int,
                  min_ratio: float, min_insns: int) -> list[dict]:
    """Slide a window over the blob; a window 'looks like code' when capstone
    consumes >= min_ratio of its bytes as valid instructions. Consecutive
    qualifying windows are merged into candidate regions."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64 if bits == 64 else capstone.CS_MODE_32)
    window = min(window, len(data)) or 1
    regions: list[dict] = []
    cur = None
    for off in range(0, max(len(data) - window + 1, 0), step):
        chunk = data[off:off + window]
        consumed, n = 0, 0
        for ins in md.disasm(chunk, 0):
            consumed += ins.size
            n += 1
        if consumed / window < min_ratio or n < min_insns:
            cur = None
            continue
        if cur is not None and off == cur["last"] + step:
            cur["last"] = off
            cur["windows"] += 1
            cur["insns"] += n
            cur["max_ratio"] = max(cur["max_ratio"], round(consumed / window, 3))
        else:
            if cur is not None:
                regions.append(cur)
            cur = {"start": off, "last": off, "windows": 1, "insns": n,
                   "max_ratio": round(consumed / window, 3)}
    if cur is not None:
        regions.append(cur)
    for r in regions:
        r["end"] = r.pop("last") + window
    return regions


def _peb_hits(data: bytes) -> list[dict]:
    out = []
    for needle, name in PEB_ACCESS_PATTERNS:
        for off in find_all(data, needle):
            out.append({"offset": off, "pattern": name})
    return sorted(out, key=lambda d: d["offset"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="shellcode blob scanner (entry disasm / code-region scan / "
                    "prologs / PEB access / strings) — issue #278 PR-1c")
    ap.add_argument("--binary", required=True, help="blob or PE to scan")
    ap.add_argument("--entry", metavar="OFFSET", help="disassemble at this file offset (hex)")
    ap.add_argument("--base", type=lambda v: int(v, 16), default=0, metavar="N",
                    help="VA base for --entry disassembly (hex, default 0)")
    ap.add_argument("--length", type=int, default=DEFAULT_LENGTH,
                    help=f"bytes per window (default {DEFAULT_LENGTH})")
    ap.add_argument("--bits", type=int, choices=(32, 64), default=64,
                    help="disassembly mode (default 64)")
    ap.add_argument("--scan", action="store_true", help="code-region scan (capstone validity)")
    ap.add_argument("--step", type=int, default=DEFAULT_STEP,
                    help=f"code-scan step (default {DEFAULT_STEP})")
    ap.add_argument("--min-ratio", type=float, default=DEFAULT_MIN_RATIO,
                    help=f"valid-bytes ratio to report a region (default {DEFAULT_MIN_RATIO})")
    ap.add_argument("--min-insns", type=int, default=DEFAULT_MIN_INSNS,
                    help=f"min instructions per window (default {DEFAULT_MIN_INSNS})")
    ap.add_argument("--prologs", action="store_true", help="x64 prolog scan")
    ap.add_argument("--peb", action="store_true", help="PEB-access signature scan")
    ap.add_argument("--strings", action="store_true", help="printable ASCII extraction")
    ap.add_argument("--min-string-len", type=int, default=DEFAULT_MIN_STRING_LEN,
                    help=f"minimum string length (default {DEFAULT_MIN_STRING_LEN})")
    ap.add_argument("--max-strings", type=int, default=DEFAULT_MAX_STRINGS,
                    help=f"cap reported strings (default {DEFAULT_MAX_STRINGS})")
    ap.add_argument("--json", action="store_true", help="emit JSON on stdout (default)")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value lines (kunglao L1 mechanical gate)")
    args = ap.parse_args(argv)

    if args.step < 1:
        _error(2, f"--step must be >= 1 (got {args.step}); a zero step would "
                  f"never advance the scan window.")

    if not (args.entry or args.scan or args.prologs or args.peb or args.strings):
        _error(2, "no operation requested: give --entry/--scan/--prologs/--peb/--strings. "
                  "Example: python shellcode_scan.py --binary blob.bin --scan --strings")

    path = Path(args.binary)
    try:
        data = path.read_bytes()
    except OSError as exc:
        _error(2, f"cannot read --binary {path}: {exc}. "
                  f"Check the path and re-run: python shellcode_scan.py --binary {path}")

    payload = {
        "tool": "shellcode-scan",
        "binary": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "bits": args.bits,
    }
    found: dict[str, int] = {}

    if args.entry:
        try:
            entry = int(args.entry, 16)
        except ValueError:
            _error(2, f"invalid --entry {args.entry!r}: expected hex like 0x448. "
                      f"Re-run with --entry 0x448")
        if entry < 0 or entry >= len(data):
            _error(2, f"--entry 0x{entry:x} is outside the file (size {len(data)}). "
                      f"Pass an offset within the blob.")
        result = _disasm_entry(data, entry, args.base, args.length, args.bits)
        payload["entry"] = result
        found["entry"] = result["count"]

    if args.scan:
        regions = _scan_regions(data, args.bits, args.length, args.step,
                                args.min_ratio, args.min_insns)
        payload["regions"] = regions
        found["scan"] = len(regions)

    if args.prologs:
        prologs = x64_prolog_offsets(data)
        payload["prologs"] = prologs
        found["prologs"] = len(prologs)

    if args.peb:
        hits = _peb_hits(data)
        payload["peb_hits"] = hits
        found["peb"] = len(hits)

    if args.strings:
        strings = ascii_strings(data, args.min_string_len, args.max_strings)
        payload["strings"] = strings
        found["strings"] = strings["total"]

    if args.reproduce:
        rows = {"tool": "shellcode-scan", "binary": str(path), "size": len(data)}
        for op, count in found.items():
            rows[op] = count
        for k, v in rows.items():
            print(f"{k}={v}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    return 0 if any(count > 0 for count in found.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
