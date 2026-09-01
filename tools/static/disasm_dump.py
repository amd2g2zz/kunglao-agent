#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/disasm_dump.py — per-site PE disassembly dumper CLI (issue #278 PR-1c).

Absorbed from D:/works/samples/2026-06-10/scripts/disasm_dllmain.py +
disasm_stage3.py, de-hardcoded (the sources had dump paths, base addresses and
RVA lists as literals): given a PE and a list of RVAs/VAs, dump capstone
disassembly at each site; optional x64 prolog scan and printable-string
extraction.

REUSES tools/_lib/lib_disasm.py (issue #284, home per #340): load_pe / va_to_offset / capstone_for
are imported — the VA->file-offset core is not duplicated.

#277 contract: parameterized (--binary / --rvas / --vas), read-only +
deterministic (idempotent), three-state exit codes, --json (default single
JSON object), --reproduce field=value lines (kunglao L1 gate), errors carry
guidance.

Exit codes:
  0 = every requested site disassembled (>= 1 instruction) and every requested
      scan found results;
  1 = negative outcome (a site is unmapped or yielded no instructions, or a
      requested scan found nothing);
  2 = operational error (missing file, not a PE, no operation requested).

Usage:
  python disasm_dump.py --binary sample.exe --rvas 0x1010,0x5b80
  python disasm_dump.py --binary sample.exe --vas 0x140001010 --prologs --strings
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()


import argparse
import hashlib
import json
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
_LIB_DIR = _THIS_DIR.parent / "_lib"   # shared cross-category lib home (#340)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import ascii_strings, x64_prolog_offsets  # noqa: E402
from lib_disasm import capstone_for, load_pe, va_to_offset  # noqa: E402

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.

DEFAULT_LENGTH = 512
DEFAULT_MIN_STRING_LEN = 6
DEFAULT_MAX_STRINGS = 100


def _error(code: int, message: str) -> None:
    print(json.dumps({"error": message, "exit_code": code}), file=sys.stderr)
    sys.exit(code)


def _parse_hex_list(text: str, flag: str) -> list[int]:
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part, 16))
        except ValueError:
            _error(2, f"invalid {flag} value {part!r}: expected hex like 0x1010. "
                      f"Re-run with e.g. --rvas 0x1010,0x2000")
    return out


def _disasm_site(pe, raw: bytes, va: int, length: int, max_insns: int) -> dict:
    off = va_to_offset(pe, va)
    site = {"va": hex(va), "rva": hex(va - pe.OPTIONAL_HEADER.ImageBase)}
    if off is None:
        site["error"] = (f"VA {hex(va)} is not mapped by any PE section "
                         f"(image base {hex(pe.OPTIONAL_HEADER.ImageBase)})")
        return site
    site["offset"] = hex(off)
    md = capstone_for(pe)
    insns = []
    for ins in md.disasm(raw[off:off + length], va):
        insns.append({
            "addr": hex(ins.address),
            "mnemonic": ins.mnemonic,
            "op_str": ins.op_str,
            "bytes": " ".join(f"{b:02x}" for b in ins.bytes),
        })
        if max_insns and len(insns) >= max_insns:
            break
    site["instructions"] = insns
    if not insns:
        site["error"] = f"no instructions decoded in the {length}-byte window at {hex(va)}"
    return site


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="per-site PE disassembly dumper (capstone) — issue #278 PR-1c")
    ap.add_argument("--binary", required=True, help="PE file to disassemble")
    ap.add_argument("--rvas", metavar="LIST",
                    help="comma-separated hex RVAs (relative to ImageBase), e.g. 0x1010,0x2000")
    ap.add_argument("--vas", metavar="LIST",
                    help="comma-separated hex VAs (absolute virtual addresses)")
    ap.add_argument("--length", type=int, default=DEFAULT_LENGTH,
                    help=f"bytes to disassemble per site (default {DEFAULT_LENGTH})")
    ap.add_argument("--max-insns", type=int, default=0, metavar="N",
                    help="cap instructions per site (default 0 = all in window)")
    ap.add_argument("--prologs", action="store_true",
                    help="scan x64 function prologs (file offsets)")
    ap.add_argument("--strings", action="store_true",
                    help="extract printable ASCII strings")
    ap.add_argument("--min-string-len", type=int, default=DEFAULT_MIN_STRING_LEN,
                    help=f"minimum string length (default {DEFAULT_MIN_STRING_LEN})")
    ap.add_argument("--max-strings", type=int, default=DEFAULT_MAX_STRINGS,
                    help=f"cap reported strings (default {DEFAULT_MAX_STRINGS})")
    ap.add_argument("--json", action="store_true", help="emit JSON on stdout (default)")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value lines (kunglao L1 mechanical gate)")
    args = ap.parse_args(argv)

    rvas = _parse_hex_list(args.rvas, "--rvas") if args.rvas else []
    vas = _parse_hex_list(args.vas, "--vas") if args.vas else []
    if not rvas and not vas and not args.prologs and not args.strings:
        _error(2, "no operation requested: give --rvas/--vas, or --prologs/--strings. "
                  "Example: python disasm_dump.py --binary sample.exe --rvas 0x1010")

    path = Path(args.binary)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _error(2, f"cannot read --binary {path}: {exc}. "
                  f"Check the path and re-run: python disasm_dump.py --binary {path}")
    if raw[:2] != b"MZ":
        _error(2, f"{path} is not a PE (no MZ magic at offset 0). "
                  f"Pass a PE file; for raw blobs use shellcode-scan.")
    try:
        pe = load_pe(path)
    except Exception as exc:  # noqa: BLE001
        _error(2, f"pefile could not parse {path}: {exc}. "
                  f"The file may be truncated or not a PE; try another sample.")

    base = pe.OPTIONAL_HEADER.ImageBase
    sites = [{"va": v, "source": "--vas"} for v in vas]
    sites += [{"va": base + r, "source": "--rvas"} for r in rvas]
    site_results = [_disasm_site(pe, raw, s["va"], args.length, args.max_insns) for s in sites]
    for s, r in zip(sites, site_results):
        r["source"] = s["source"]

    prologs = x64_prolog_offsets(raw) if args.prologs else None
    strings = ascii_strings(raw, args.min_string_len, args.max_strings) if args.strings else None

    payload = {
        "tool": "disasm-dump",
        "binary": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "machine": hex(pe.FILE_HEADER.Machine),
        "image_base": hex(base),
        "sites": site_results,
    }
    if prologs is not None:
        payload["prologs"] = prologs
    if strings is not None:
        payload["strings"] = strings

    if args.reproduce:
        rows = {
            "tool": "disasm-dump",
            "binary": str(path),
            "machine": hex(pe.FILE_HEADER.Machine),
            "image_base": hex(base),
            "sites": len(site_results),
        }
        for i, r in enumerate(site_results):
            rows[f"site_{i}_va"] = r["va"]
            rows[f"site_{i}_rva"] = r["rva"]
            if "offset" in r:
                rows[f"site_{i}_offset"] = r["offset"]
                rows[f"site_{i}_instructions"] = len(r["instructions"])
                if r["instructions"]:
                    rows[f"site_{i}_first_bytes"] = r["instructions"][0]["bytes"]
            else:
                rows[f"site_{i}_error"] = r["error"]
        if prologs is not None:
            rows["prologs"] = len(prologs)
        if strings is not None:
            rows["strings"] = strings["total"]
        for k, v in rows.items():
            print(f"{k}={v}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    site_ok = all("error" not in r for r in site_results)
    scans_ok = True
    if prologs is not None and not prologs:
        scans_ok = False
    if strings is not None and strings["total"] == 0:
        scans_ok = False
    return 0 if (site_ok and scans_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
