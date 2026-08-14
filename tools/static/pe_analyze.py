#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/pe_analyze.py — PE trunk static analyzer CLI (issue #278 PR-1c).

Absorbed from D:/works/samples/2026-06-10/scripts/pe_analysis_mmHjOx.py:
headers / sections / imports / exports / resources / overlay / pdb / tls /
signature, de-hardcoded (the source had PE_PATH as a string literal) and
exposed as subcommands over --binary.

#277 contract: fully parameterized (--binary), read-only and deterministic
(idempotent re-runs emit identical output), three-state exit codes, --json
(default: a single JSON object on stdout), --reproduce field=value lines
(kunglao L1 mechanical gate), errors carry guidance (structured JSON on
stderr with the next action).

Exit codes:
  0 = the requested subcommand ran and its table/data is present;
  1 = negative finding (table absent — e.g. no overlay, no TLS directory);
  2 = operational error (missing file, not a parseable PE, bad args).

Usage:
  python pe_analyze.py --binary sample.exe
  python pe_analyze.py --binary sample.exe imports
  python pe_analyze.py --binary sample.exe overlay --reproduce
  python pe_analyze.py --binary sample.exe --out report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import pefile

# Sibling static helpers (tools/static/common.py) — entropy for sections.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from common import byte_entropy  # noqa: E402

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

SUBSYSTEM_NAMES = {
    0: "UNKNOWN", 1: "NATIVE", 2: "WINDOWS_GUI", 3: "WINDOWS_CUI",
    5: "OS2_CUI", 7: "POSIX_CUI", 9: "WINDOWS_CE_GUI", 10: "EFI_APPLICATION",
    11: "EFI_BOOT_SERVICE_DRIVER", 12: "EFI_RUNTIME_DRIVER", 13: "EFI_ROM",
    14: "XBOX", 16: "WINDOWS_BOOT_APPLICATION",
}

RESOURCE_TYPES = {
    1: "CURSOR", 2: "BITMAP", 3: "ICON", 4: "MENU", 5: "DIALOG",
    6: "STRING", 7: "FONTDIR", 8: "FONT", 9: "ACCELERATOR", 10: "RCDATA",
    11: "MESSAGETABLE", 12: "GROUP_CURSOR", 14: "GROUP_ICON", 16: "VERSION",
    17: "DLGINCLUDE", 19: "PLUGPLAY", 20: "VXD", 21: "ANICURSOR",
    22: "ANIICON", 23: "HTML", 24: "MANIFEST",
}

CHARACTERISTICS_FLAGS = (
    (0x0002, "EXECUTABLE_IMAGE"), (0x0020, "LARGE_ADDRESS_AWARE"),
    (0x0100, "32BIT_MACHINE"), (0x0200, "DEBUG_STRIPPED"), (0x2000, "DLL"),
)

DLL_CHARACTERISTICS_FLAGS = (
    (0x0040, "DYNAMIC_BASE"), (0x0080, "FORCE_INTEGRITY"),
    (0x0100, "NX_COMPAT"), (0x0200, "NO_ISOLATION"), (0x0400, "NO_SEH"),
    (0x0800, "NO_BIND"), (0x2000, "WDM_DRIVER"), (0x8000, "TERMINAL_SERVER_AWARE"),
)

SECTION_FLAGS = (
    (0x20000000, "CODE"), (0x40000000, "INITIALIZED_DATA"),
    (0x80000000, "UNINITIALIZED_DATA"), (0x00000020, "MEM_EXECUTE"),
    (0x00000040, "MEM_READ"), (0x00000080, "MEM_WRITE"),
    (0x02000000, "MEM_DISCARDABLE"), (0x04000000, "MEM_NOT_CACHED"),
    (0x08000000, "MEM_NOT_PAGED"), (0x10000000, "MEM_SHARED"),
)

DEBUG_TYPE_NAMES = {
    0: "UNKNOWN", 1: "COFF", 2: "CODEVIEW", 3: "FPO", 4: "MISC",
    5: "EXCEPTION", 6: "FIXUP", 7: "OMAP_TO_SRC", 8: "OMAP_FROM_SRC",
    9: "BORLAND", 10: "RESERVED10", 11: "CLSID", 16: "REPRO",
}

CERT_TYPE_NAMES = {0x0001: "X509", 0x0002: "PKCS_SIGNED_DATA", 0x0003: "PKCS1_SIGN"}


def _error(code: int, message: str) -> None:
    """Structured error on stderr (guidance included) and exit."""
    print(json.dumps({"error": message, "exit_code": code}), file=sys.stderr)
    sys.exit(code)


def _flags(value: int, table) -> list[str]:
    return [name for bit, name in table if value & bit]


def _decode(data, value) -> str:
    return value.decode("ascii", errors="replace") if isinstance(value, bytes) else str(value)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(binary: Path) -> tuple[bytes, pefile.PE]:
    try:
        data = binary.read_bytes()
    except OSError as exc:
        _error(2, f"cannot read --binary {binary}: {exc}. "
                  f"Check the path and re-run: python pe_analyze.py --binary {binary}")
    if data[:2] != b"MZ":
        _error(2, f"{binary} is not a PE (no MZ magic at offset 0). "
                  f"Pass a PE file: python pe_analyze.py --binary <path-to-pe>")
    try:
        pe = pefile.PE(str(binary))
    except Exception as exc:  # noqa: BLE001 - report any parse failure with guidance
        _error(2, f"pefile could not parse {binary}: {exc}. "
                  f"The file may be truncated, packed, or not a PE; try another sample.")
    return data, pe


# ---- subcommands (each returns (result dict, present bool)) ----

def cmd_headers(pe: pefile.PE, data: bytes):
    fh, oh = pe.FILE_HEADER, pe.OPTIONAL_HEADER
    return {
        "e_lfanew": hex(struct.unpack_from("<I", data, 0x3C)[0]),
        "machine": hex(fh.Machine),
        "machine_name": "x64" if fh.Machine == 0x8664 else "x86" if fh.Machine == 0x14C else "unknown",
        "num_sections": fh.NumberOfSections,
        "time_date_stamp": hex(fh.TimeDateStamp),
        "characteristics": hex(fh.Characteristics),
        "characteristics_flags": _flags(fh.Characteristics, CHARACTERISTICS_FLAGS),
        "magic": "PE32+" if oh.Magic == 0x20B else "PE32",
        "entry_point": hex(oh.AddressOfEntryPoint),
        "image_base": hex(oh.ImageBase),
        "section_alignment": hex(oh.SectionAlignment),
        "file_alignment": hex(oh.FileAlignment),
        "size_of_image": hex(oh.SizeOfImage),
        "subsystem": SUBSYSTEM_NAMES.get(oh.Subsystem, f"UNKNOWN({oh.Subsystem})"),
        "dll_characteristics": hex(oh.DllCharacteristics),
        "dll_characteristics_flags": _flags(oh.DllCharacteristics, DLL_CHARACTERISTICS_FLAGS),
        "is_dll": bool(fh.Characteristics & 0x2000),
    }, True


def cmd_sections(pe: pefile.PE, data: bytes):
    out = []
    for s in pe.sections:
        raw = data[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        out.append({
            "name": s.Name.rstrip(b"\x00").decode("ascii", errors="replace"),
            "virtual_address": hex(s.VirtualAddress),
            "virtual_size": hex(s.Misc_VirtualSize),
            "raw_ptr": hex(s.PointerToRawData),
            "raw_size": hex(s.SizeOfRawData),
            "entropy": round(byte_entropy(raw), 4),
            "characteristics": hex(s.Characteristics),
            "characteristics_flags": _flags(s.Characteristics, SECTION_FLAGS),
        })
    return out, bool(out)


def cmd_imports(pe: pefile.PE, data: bytes):
    imp_dir = getattr(pe, "DIRECTORY_ENTRY_IMPORT", None)
    if not imp_dir:
        return {"note": "no import table (data directory 1 RVA = 0)"}, False
    out = []
    for dll in imp_dir:
        funcs = []
        for imp in dll.imports:
            if imp.name is None and imp.ordinal is not None:
                funcs.append({"ordinal": imp.ordinal, "iat_rva": hex(imp.address)})
            else:
                funcs.append({"name": _decode(data, imp.name),
                              "hint": imp.hint, "iat_rva": hex(imp.address)})
        out.append({"dll": _decode(data, dll.dll), "functions": funcs})
    return out, True


def cmd_exports(pe: pefile.PE, data: bytes):
    exp = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
    if not exp:
        return {"note": "no export table (data directory 0 RVA = 0)"}, False
    symbols = [{"name": _decode(data, s.name), "ordinal": s.ordinal,
                "rva": hex(s.address)} for s in exp.symbols]
    return {
        "dll_name": _decode(data, exp.name),
        "ordinal_base": exp.struct.Base,
        "number_of_functions": exp.struct.NumberOfFunctions,
        "number_of_names": exp.struct.NumberOfNames,
        "symbols": symbols,
    }, True


def _walk_resources(entries, out: list, level: int = 0,
                    type_name=None, rid=None, lang_id=None):
    for e in entries:
        name = None
        if e.name is not None:
            name = e.name.string.decode("utf-16-le", errors="replace")
        label = name or (RESOURCE_TYPES.get(e.id, f"Type_{e.id}") if level == 0 else f"ID_{e.id}")
        if getattr(e, "data", None) is not None:
            out.append({
                "type": type_name or label,
                "id": rid if rid is not None else e.id,
                "name": name,
                "lang_id": lang_id if level != 2 else e.id,
                "rva": hex(e.data.struct.OffsetToData),
                "size": e.data.struct.Size,
            })
        else:
            _walk_resources(e.directory.entries, out, level + 1,
                            type_name=type_name or (label if level == 0 else None),
                            rid=e.id if level == 1 else rid,
                            lang_id=e.id if level == 2 else lang_id)


def _version_info(pe: pefile.PE):
    info = getattr(pe, "FileInfo", None)
    if not info:
        return None
    out = {}
    for fi in info:
        for st in getattr(fi, "StringTable", []) or []:
            for k, v in getattr(st, "entries", {}).items():
                out[_decode(None, k)] = _decode(None, v)
    return out or None


def cmd_resources(pe: pefile.PE, data: bytes):
    rsrc = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
    if not rsrc:
        return {"note": "no resource directory (data directory 2 RVA = 0)"}, False
    entries: list = []
    _walk_resources(rsrc.entries, entries)
    manifest_preview = None
    for e in entries:
        if e["type"] == "MANIFEST" and e["size"]:
            try:
                off = pe.get_offset_from_rva(int(e["rva"], 16))
                blob = data[off:off + min(e["size"], 4096)]
                manifest_preview = blob.decode("utf-8", errors="replace")[:500] or None
            except Exception:  # noqa: BLE001 - preview is best-effort
                pass
    return {"entries": entries, "version_info": _version_info(pe),
            "manifest_preview": manifest_preview}, True


def cmd_overlay(pe: pefile.PE, data: bytes):
    last_raw_end = max((s.PointerToRawData + s.SizeOfRawData for s in pe.sections), default=0)
    if last_raw_end >= len(data):
        return {"note": f"no overlay: file size ({len(data)}) matches last "
                        f"section end (0x{last_raw_end:X})"}, False
    overlay = data[last_raw_end:]
    sigs = []
    if overlay[:2] == b"MZ":
        sigs.append("MZ (embedded PE)")
    if overlay[:4] == b"PK\x03\x04":
        sigs.append("ZIP")
    if overlay[:4] == b"\x7fELF":
        sigs.append("ELF")
    if overlay[:8] == b"\x89PNG\r\n\x1a\n":
        sigs.append("PNG")
    return {
        "offset": hex(last_raw_end),
        "size": len(overlay),
        "hex_preview": " ".join(f"{b:02x}" for b in overlay[:64]),
        "ascii_preview": "".join(chr(b) if 32 <= b < 127 else "." for b in overlay[:64]),
        "signatures": sigs,
    }, True


def cmd_pdb(pe: pefile.PE, data: bytes):
    dbg = getattr(pe, "DIRECTORY_ENTRY_DEBUG", None)
    if not dbg:
        return {"note": "no debug directory (data directory 6 RVA = 0)"}, False
    entries = []
    for e in dbg:
        type_id = e.struct.Type
        entry = {"type": DEBUG_TYPE_NAMES.get(type_id, f"TYPE_{type_id}"), "type_id": type_id,
                 "size_of_data": e.struct.SizeOfData,
                 "raw_data_ptr": hex(e.struct.PointerToRawData)}
        if type_id == 2 and e.struct.SizeOfData > 0 and e.struct.PointerToRawData > 0:
            ptr = e.struct.PointerToRawData
            cv = data[ptr:ptr + e.struct.SizeOfData]
            if cv[:4] == b"RSDS" and len(cv) >= 24:
                guid = cv[4:20]
                entry.update({
                    "signature": "RSDS",
                    "guid": "-".join([guid[0:4].hex(), guid[4:6].hex(), guid[6:8].hex(),
                                      guid[8:10].hex(), guid[10:16].hex()]),
                    "age": struct.unpack_from("<I", cv, 20)[0],
                    "pdb_path": cv[24:].split(b"\x00")[0].decode("ascii", errors="replace"),
                })
            elif cv[:4] == b"NB10" and len(cv) >= 16:
                entry.update({
                    "signature": "NB10",
                    "age": struct.unpack_from("<I", cv, 8)[0],
                    "pdb_path": cv[16:].split(b"\x00")[0].decode("ascii", errors="replace"),
                })
            else:
                entry["signature"] = cv[:4].hex()
        entries.append(entry)
    return {"entries": entries}, True


def cmd_tls(pe: pefile.PE, data: bytes):
    tls = getattr(pe, "DIRECTORY_ENTRY_TLS", None)
    if not tls:
        return {"note": "no TLS directory (data directory 9 RVA = 0)"}, False
    st = tls.struct
    callbacks = []
    if st.AddressOfCallBacks:
        cb_va = st.AddressOfCallBacks
        cb_rva = cb_va - pe.OPTIONAL_HEADER.ImageBase
        off = None
        for s in pe.sections:
            span = max(s.Misc_VirtualSize, s.SizeOfRawData)
            if s.VirtualAddress <= cb_rva < s.VirtualAddress + span:
                off = s.PointerToRawData + (cb_rva - s.VirtualAddress)
                break
        if off is not None:
            for i in range(32):
                if off + (i + 1) * 8 > len(data):
                    break
                va = struct.unpack_from("<Q", data, off + i * 8)[0]
                if va == 0:
                    break
                callbacks.append({"va": hex(va), "rva": hex(va - pe.OPTIONAL_HEADER.ImageBase)})
    return {
        "start_raw_va": hex(st.StartAddressOfRawData),
        "end_raw_va": hex(st.EndAddressOfRawData),
        "address_of_callbacks_va": hex(st.AddressOfCallBacks),
        "size_of_zero_fill": st.SizeOfZeroFill,
        "callbacks": callbacks,
    }, True


def cmd_signature(pe: pefile.PE, data: bytes):
    sec_idx = pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_SECURITY"]
    dirs = pe.OPTIONAL_HEADER.DATA_DIRECTORY
    # r2-278-1c: PEs with NumberOfRvaAndSizes < 5 lack the security directory
    # entry — indexing it directly raises IndexError (bare traceback, exit 1).
    if sec_idx >= len(dirs):
        return {"tail_cert_candidate": False,
                "note": "no security directory (NumberOfRvaAndSizes too small)"}, False
    sec = dirs[sec_idx]
    result = {"tail_cert_candidate": False}
    cert_off, cert_size = sec.VirtualAddress, sec.Size
    if cert_off == 0:
        last_raw_end = max((s.PointerToRawData + s.SizeOfRawData for s in pe.sections), default=0)
        if last_raw_end + 8 <= len(data) and data[last_raw_end:last_raw_end + 4] == b"\x00\x00\x02\x00":
            result["tail_cert_candidate"] = True
            cert_off, cert_size = last_raw_end, struct.unpack_from("<I", data, last_raw_end)[0]
        else:
            result["note"] = "no certificate directory (security directory offset = 0)"
            return result, False
    if cert_off + 8 > len(data):
        result["note"] = f"certificate offset 0x{cert_off:X} beyond file size ({len(data)})"
        return result, False
    dw_length, w_revision, w_cert_type = struct.unpack_from("<IHH", data, cert_off)
    result.update({
        "file_offset": hex(cert_off),
        "size": cert_size or dw_length,
        "dw_length": dw_length,
        "w_revision": w_revision,
        "cert_type_id": hex(w_cert_type),
        "cert_type_name": CERT_TYPE_NAMES.get(w_cert_type, f"UNKNOWN(0x{w_cert_type:04X})"),
    })
    return result, True


SUBCOMMANDS = {
    "headers": cmd_headers, "sections": cmd_sections, "imports": cmd_imports,
    "exports": cmd_exports, "resources": cmd_resources, "overlay": cmd_overlay,
    "pdb": cmd_pdb, "tls": cmd_tls, "signature": cmd_signature,
}


def _reproduce_rows(args, data: bytes, pe: pefile.PE, results: dict) -> dict:
    headers = results.get("headers", {})
    rows = {
        "tool": "pe-analyze",
        "binary": str(args.binary),
        "sha256": _sha256(data),
        "machine": headers.get("machine", hex(pe.FILE_HEADER.Machine)),
        "num_sections": headers.get("num_sections", pe.FILE_HEADER.NumberOfSections),
        "entry_point": headers.get("entry_point", hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint)),
        "image_base": headers.get("image_base", hex(pe.OPTIONAL_HEADER.ImageBase)),
        "subsystem": headers.get("subsystem",
                                 SUBSYSTEM_NAMES.get(pe.OPTIONAL_HEADER.Subsystem, "UNKNOWN")),
    }
    if "imports" in results:
        rows["imports_count"] = len(results["imports"]) if isinstance(results["imports"], list) else 0
    if "exports" in results:
        exp = results["exports"]
        rows["exports_count"] = len(exp.get("symbols", [])) if isinstance(exp, dict) else 0
    if "overlay" in results:
        ov = results["overlay"]
        rows["overlay_size"] = ov.get("size", 0) if isinstance(ov, dict) else 0
    if "pdb" in results:
        pdb = results["pdb"]
        paths = [e.get("pdb_path", "") for e in pdb.get("entries", [])] if isinstance(pdb, dict) else []
        rows["pdb_path"] = paths[0] if paths else "absent"
    if "tls" in results:
        tls = results["tls"]
        if isinstance(tls, dict) and "callbacks" in tls:
            rows["tls_callbacks"] = len(tls["callbacks"])
        else:
            rows["tls_callbacks"] = "absent"
    if "signature" in results:
        sig = results["signature"]
        rows["cert_type"] = sig.get("cert_type_name", "absent") if isinstance(sig, dict) else "absent"
    if "resources" in results:
        rsrc = results["resources"]
        rows["resource_count"] = len(rsrc.get("entries", [])) if isinstance(rsrc, dict) else 0
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="PE trunk static analyzer (headers/sections/imports/exports/"
                    "resources/overlay/pdb/tls/signature) — issue #278 PR-1c")
    ap.add_argument("--binary", required=True, help="PE file to analyze")
    ap.add_argument("subcommand", nargs="?", default="all",
                    choices=sorted(SUBCOMMANDS) + ["all"],
                    help="which table to analyze (default: all)")
    ap.add_argument("--json", action="store_true", help="emit JSON on stdout (default)")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value lines (kunglao L1 mechanical gate)")
    ap.add_argument("--out", metavar="FILE", help="write the JSON result to FILE")
    args = ap.parse_args(argv)

    data, pe = _load(Path(args.binary))

    subcmds = list(SUBCOMMANDS) if args.subcommand == "all" else [args.subcommand]
    results: dict = {}
    found: dict = {}
    for name in subcmds:
        result, present = SUBCOMMANDS[name](pe, data)
        results[name] = result
        found[name] = present

    payload = {
        "tool": "pe-analyze",
        "binary": str(Path(args.binary)),
        "sha256": _sha256(data),
        "results": results,
    }

    if args.reproduce:
        for k, v in _reproduce_rows(args, data, pe, results).items():
            print(f"{k}={v}")
    else:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.out:
            try:
                Path(args.out).write_text(text, encoding="utf-8")
            except OSError as exc:
                _error(2, f"cannot write --out {args.out}: {exc}. "
                          f"Check the directory and re-run with a writable --out path.")
        else:
            print(text)

    if args.subcommand == "all":
        return 0
    return 0 if found[args.subcommand] else 1


if __name__ == "__main__":
    sys.exit(main())
