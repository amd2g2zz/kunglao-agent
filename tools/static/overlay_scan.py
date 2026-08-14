#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/overlay_scan.py — PE overlay analyzer CLI (issue #278 PR-1c).

3-in-1 merge of the D:/works/samples/2026-06-10/scripts overlay tools
(de-hardcoded — both sources had PATH / overlay offsets as literals):

  overlay_analysis.py    --mode reloc   reloc-based overlay characterization
                                        (IMAGE_BASE_RELOCATION block walk,
                                         remainder entropy + signature search)
  true_overlay_check.py  --mode true    true-overlay check (past last section):
                                        hex/entropy/uniformity, Go-signature
                                        search, valid pclntab scan, cert check
  overlay_analysis.py    --mode mz      MZ-in-overlay search (embedded PE scan
                                        with e_lfanew/PE-signature validation)

#277 contract: parameterized (--binary), read-only + deterministic
(idempotent), three-state exit codes, --json (default single JSON object),
--reproduce field=value lines (kunglao L1 gate), errors carry guidance.

Exit codes:
  0 = overlay present and the mode's primary question answered positively
      (reloc → looks like a relocation table; mz → embedded PE found;
       true → Go evidence found; all → overlay characterized);
  1 = negative finding (no overlay at all, or the mode-specific negative);
  2 = operational error (missing file, not a PE, bad args).

Usage:
  python overlay_scan.py --binary sample.exe
  python overlay_scan.py --binary sample.exe --mode mz
  python overlay_scan.py --binary sample.exe --mode reloc --reproduce
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import pefile

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
_TOOLS_DIR = _THIS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from _common import (  # noqa: E402
    EXE_SIGNATURES,
    byte_entropy,
    find_all,
    scan_valid_pclntab,
    signature_hits,
    uniform_variance,
)
from lib_disasm import load_pe  # noqa: E402  (VA/offset core reuse, issue #284)

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

RELOC_TYPE_NAMES = {0: "ABSOLUTE", 3: "HIGHLOW", 10: "DIR64"}
MAX_RELOC_BLOCK = 0x10000
MAX_PCLNTAB_SEARCH = 10 * 1024 * 1024


def _error(code: int, message: str) -> None:
    print(json.dumps({"error": message, "exit_code": code}), file=sys.stderr)
    sys.exit(code)


def _load(args) -> tuple[bytes, pefile.PE]:
    path = Path(args.binary)
    try:
        data = path.read_bytes()
    except OSError as exc:
        _error(2, f"cannot read --binary {path}: {exc}. "
                  f"Check the path and re-run: python overlay_scan.py --binary {path}")
    if data[:2] != b"MZ":
        _error(2, f"{path} is not a PE (no MZ magic at offset 0). "
                  f"Pass a PE file with a possible overlay.")
    try:
        pe = load_pe(path)
    except Exception as exc:  # noqa: BLE001
        _error(2, f"pefile could not parse {path}: {exc}. "
                  f"The file may be truncated or not a PE; try another sample.")
    return data, pe


def _overlay(data: bytes, pe: pefile.PE) -> tuple[int, bytes]:
    start = max((s.PointerToRawData + s.SizeOfRawData for s in pe.sections), default=0)
    return start, data[start:]


def _reloc_scan(ov: bytes, max_search: int) -> dict:
    out: dict = {"is_reloc_table": False}
    if len(ov) < 8:
        out["reason"] = "overlay smaller than one relocation block header (8 bytes)"
        return out
    first_page = struct.unpack_from("<I", ov, 0)[0]
    first_size = struct.unpack_from("<I", ov, 4)[0]
    out["first_page_rva"] = hex(first_page)
    out["first_block_size"] = hex(first_size)
    if first_page % 0x1000 != 0 or not (8 <= first_size <= MAX_RELOC_BLOCK):
        out["reason"] = (f"first block is not IMAGE_BASE_RELOCATION shaped "
                         f"(page_rva={first_page:#x} not 0x1000-aligned or "
                         f"block_size={first_size} invalid)")
        return out

    pos, blocks = 0, 0
    while pos + 8 <= len(ov):
        page_rva = struct.unpack_from("<I", ov, pos)[0]
        block_size = struct.unpack_from("<I", ov, pos + 4)[0]
        if block_size == 0 or block_size > MAX_RELOC_BLOCK or pos + block_size > len(ov):
            break
        if page_rva % 0x1000 != 0:
            break
        blocks += 1
        pos += block_size

    out["is_reloc_table"] = blocks > 0
    out["reloc_blocks"] = blocks
    out["relocation_table_size"] = pos
    first_entries = []
    max_entries = min(5, (first_size - 8) // 2, (len(ov) - 8) // 2)
    for i in range(max(max_entries, 0)):
        entry = struct.unpack_from("<H", ov, 8 + i * 2)[0]
        first_entries.append({
            "type": RELOC_TYPE_NAMES.get(entry >> 12, entry >> 12),
            "offset": hex(entry & 0xFFF),
        })
    out["first_block_entries"] = first_entries

    remaining = ov[pos:]
    out["remaining_size"] = len(remaining)
    if remaining:
        sample = remaining[:65536]
        out["remainder_entropy"] = round(byte_entropy(sample), 4)
        variance = uniform_variance(sample)
        out["remainder_encrypted"] = variance < (len(sample) / 256) * 3
        out["remainder_signatures"] = signature_hits(remaining[:max_search])
        out["pclntab_valid"] = scan_valid_pclntab(remaining, max_search)
    return out


def _true_scan(ov: bytes, max_search: int) -> dict:
    sample = ov[:65536]
    n = len(sample)
    out = {
        "first_256_hex": " ".join(f"{b:02x}" for b in ov[:256]),
        "first_128_ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in ov[:128]),
        "first_dwords": [hex(struct.unpack_from("<I", ov, off)[0])
                         for off in (0, 4) if len(ov) >= off + 4],
        "entropy_64kb": round(byte_entropy(sample), 4),
    }
    if n:
        variance = uniform_variance(sample)
        out["uniform_variance"] = round(variance, 1)
        out["encrypted"] = variance < (n / 256) * 2
    else:
        out["encrypted"] = False
    out["signatures"] = signature_hits(ov[:max_search])
    out["pclntab_valid"] = scan_valid_pclntab(ov, max_search)
    cert_len = struct.unpack_from("<I", ov, 0)[0] if len(ov) >= 8 else 0
    cert_type = struct.unpack_from("<H", ov, 6)[0] if len(ov) >= 8 else 0
    out["cert_table"] = bool(0 < cert_len < 100000 and cert_type in (1, 2, 3))
    out["go_evidence"] = bool(
        out["pclntab_valid"]
        or out["signatures"].get("Go buildinf", 0) > 0
        or out["signatures"].get("go.buildid", 0) > 0
        or out["signatures"].get("Go pclntab v1.16+", 0) > 0
    )
    return out


def _mz_scan(ov: bytes, max_search: int) -> dict:
    out: dict = {"embedded_pe": []}
    if len(ov) >= 2 and ov[:2] == b"MZ":
        out["starts_with"] = "MZ"
    elif len(ov) >= 4 and ov[:4] == b"\x7fELF":
        out["starts_with"] = "ELF"
    elif len(ov) >= 4 and ov[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
        out["starts_with"] = "Mach-O"
    else:
        out["starts_with"] = "none"
    for off in find_all(ov[:max_search], b"MZ"):
        if off + 0x3C + 4 > len(ov):
            continue
        e_lfanew = struct.unpack_from("<I", ov, off + 0x3C)[0]
        pe_off = off + e_lfanew
        if 0 <= pe_off <= len(ov) - 4 and ov[pe_off:pe_off + 4] == b"PE\x00\x00":
            out["embedded_pe"].append({
                "overlay_offset": hex(off),
                "e_lfanew": hex(e_lfanew),
            })
    out["mz_total"] = len(find_all(ov[:max_search], b"MZ"))
    return out


MODES = {"reloc": _reloc_scan, "true": _true_scan, "mz": _mz_scan}


def _positive(mode: str, results: dict) -> bool:
    """Mode-specific 'primary question answered positively' predicate."""
    if mode == "reloc":
        return bool(results.get("is_reloc_table"))
    if mode == "mz":
        return bool(results.get("embedded_pe"))
    if mode == "true":
        return bool(results.get("go_evidence"))
    return True  # all


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="PE overlay analyzer (reloc characterization / true-overlay "
                    "check / MZ-in-overlay search) — issue #278 PR-1c")
    ap.add_argument("--binary", required=True, help="PE file to analyze")
    ap.add_argument("--mode", default="all", choices=sorted(MODES) + ["all"],
                    help="reloc | true | mz | all (default: all)")
    ap.add_argument("--max-search", type=int, default=MAX_PCLNTAB_SEARCH,
                    metavar="N", help="bytes of overlay to brute-search (default 10485760)")
    ap.add_argument("--json", action="store_true", help="emit JSON on stdout (default)")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value lines (kunglao L1 mechanical gate)")
    ap.add_argument("--out", metavar="FILE", help="write the JSON result to FILE")
    args = ap.parse_args(argv)

    data, pe = _load(args)
    start, ov = _overlay(data, pe)

    payload = {
        "tool": "overlay-scan",
        "binary": str(Path(args.binary)),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mode": args.mode,
        "overlay_start": hex(start),
        "overlay_size": len(ov),
    }

    if len(ov) == 0:
        payload["results"] = {"note": "no overlay: file size equals last section raw end"}
        if args.reproduce:
            for k, v in {"tool": "overlay-scan", "binary": str(Path(args.binary)),
                         "mode": args.mode, "overlay_start": hex(start),
                         "overlay_size": 0}.items():
                print(f"{k}={v}")
        else:
            _emit_json(payload, args)
        return 1  # negative finding: no overlay at all

    modes = list(MODES) if args.mode == "all" else [args.mode]
    results = {m: MODES[m](ov, args.max_search) for m in modes}
    payload["results"] = results

    if args.reproduce:
        rows = {
            "tool": "overlay-scan",
            "binary": str(Path(args.binary)),
            "mode": args.mode,
            "overlay_start": hex(start),
            "overlay_size": len(ov),
        }
        for m in modes:
            r = results[m]
            rows[f"{m}_positive"] = str(_positive(m, r)).lower()
            if m == "reloc":
                rows["reloc_blocks"] = r.get("reloc_blocks", 0)
                rows["remainder_encrypted"] = str(r.get("remainder_encrypted", False)).lower()
            if m == "mz":
                rows["mz_hits"] = len(r.get("embedded_pe", []))
                rows["mz_total"] = r.get("mz_total", 0)
            if m == "true":
                rows["go_evidence"] = str(r.get("go_evidence", False)).lower()
                rows["pclntab_valid"] = len(r.get("pclntab_valid", []))
                rows["encrypted"] = str(r.get("encrypted", False)).lower()
                rows["cert_table"] = str(r.get("cert_table", False)).lower()
        for k, v in rows.items():
            print(f"{k}={v}")
    else:
        _emit_json(payload, args)

    if args.mode == "all":
        return 0
    return 0 if _positive(args.mode, results[args.mode]) else 1


def _emit_json(payload: dict, args) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        try:
            Path(args.out).write_text(text, encoding="utf-8")
        except OSError as exc:
            _error(2, f"cannot write --out {args.out}: {exc}. "
                      f"Check the directory and re-run with a writable --out path.")
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
