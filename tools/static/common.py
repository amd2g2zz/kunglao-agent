#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/common.py — the single shared module for the tools/static CLIs.

Merged in issue #340 from two modules (both absorbed by #278 PR-1b/1c):

  - CLI plumbing (ex-common.py): the #277 CLI-checklist mechanics every
    static CLI reuses (this is not a tool itself — not registered in
    tools/_INDEX.yaml):
      * structured error JSON on stderr with guidance, exit code 2
      * three-state exit codes: 0 = ok, 1 = negative finding (ran, no
        result), 2 = error (bad args / unreadable input) — mirrors
        tools/crypto/crypto-tool.py
      * default text output: one line per result
      * --json: a single JSON object on stdout
      * --reproduce: field=value lines for the kunglao L1 mechanical gate
        (keys must match `^[A-Za-z_][\\w.]*[:=]`, see scripts/kunglao_verify.py)
  - byte-scan helpers (ex-_common.py, from the D:/works/samples script
    accumulation: overlay_analysis.py / true_overlay_check.py /
    disasm_stage3.py) so overlay_scan / disasm_dump / shellcode_scan /
    pe_analyze share one implementation of signature search, string
    extraction, prolog scan, entropy and Go-pclntab validation.

Contracts (#277 / #340):
  - pure side-effect-free functions (the stdout reconfigure below excepted),
    no hardcoded paths, no imports of the sibling tools — importable alone.
  - one shared module per category (#340 R3): do not add a second helper
    module under tools/static/; extend this one instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter
from pathlib import Path

# r2-278-1b/1c H1: decoded binary content can carry U+FFFD
# (decode(errors="replace")); a GBK console (Windows) cannot encode it and a
# bare UnicodeEncodeError traceback would break the "structured error, never
# a traceback" CLI contract. UTF-8 stdout contract (#317): stdout is unified
# on UTF-8 (NOT an errors="replace" patch) with errors="replace" as
# belt-and-braces for unpaired surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

EXIT_OK = 0
EXIT_NEGATIVE = 1
EXIT_ERROR = 2

# kunglao L1 mechanical gate: field=value lines.
L1_FIELD_RE = re.compile(r"^[A-Za-z_][\w.]*[:=]")

# ---- CLI plumbing (ex-common.py) -------------------------------------------


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


def write_evidence(workspace: Path, name: str, data: dict) -> Path:
    """Write one tool-evidence JSON file under ``<workspace>/evidence/``.

    Single source for the Family J copies (#863): apk_mem_gate /
    baksmali_index / dexdc_scanner / scripts/apkid_scanner all used to carry
    this 7-line writer; dexdc's 3-arg signature (workspace, name, data) is
    the canonical shape — the fixed-filename copies pass their name at the
    call site. Contract: mkdir parents, utf-8 text,
    json.dumps(ensure_ascii=False, indent=2), returns the out path.
    """
    out_dir = workspace / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / name
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


# ---- byte-scan helpers (ex-_common.py) -------------------------------------

# Common overlay / blob signatures (name -> needle) used by overlay tools.
EXE_SIGNATURES: tuple[tuple[str, bytes], ...] = (
    ("PE/DOS (MZ)", b"MZ"),
    ("PE signature", b"PE\x00\x00"),
    ("ELF", b"\x7fELF"),
    ("Mach-O 64 LE", b"\xcf\xfa\xed\xfe"),
    ("Mach-O FAT", b"\xca\xfe\xba\xbe"),
    ("gzip", b"\x1f\x8b"),
    ("zlib", b"\x78\x9c"),
    ("Go buildinf", b"Go buildinf"),
    ("go.buildid", b"go.buildid"),
    ("Go pclntab v1.16+", b"\xfb\xff\xff\xff"),
    ("Go pclntab v1.2-1.15", b"\xfa\xff\xff\xff"),
    ("Go runtime funcs", b"runtime."),
)

# x86-64 function prolog byte patterns (name -> (needle, kind)).
# `sub rsp, imm8` is only a prolog when the imm8 is a small frame (< 0x80),
# matching the source disasm_stage3.py heuristic.
X64_PROLOG_PATTERNS: tuple[tuple[bytes, str], ...] = (
    (b"\x48\x89\x5c\x24", "mov [rsp+imm8], rbx"),
    (b"\x48\x83\xec", "sub rsp, imm8"),
    (b"\x55\x48\x89\xe5", "push rbp; mov rbp, rsp"),
)

# Canonical PEB-access instruction sequences (x64 GS:0x60 / x86 FS:0x30).
PEB_ACCESS_PATTERNS: tuple[tuple[bytes, str], ...] = (
    (b"\x64\x48\x8b\x04\x25\x60\x00\x00\x00", "x64 mov rax, gs:[0x60]"),
    (b"\x64\x4c\x8b\x1c\x25\x60\x00\x00\x00", "x64 mov r11, gs:[0x60]"),
    (b"\x64\xa1\x30\x00\x00\x00", "x86 mov eax, fs:[0x30]"),
)

GO_PCLNTAB_MAGICS = (0xFFFFFFFA, 0xFFFFFFFB)  # v1.2-1.15 / v1.16+
MAX_NFUNC = 500000


def find_all(data: bytes, pattern: bytes) -> list[int]:
    """All byte offsets where `pattern` occurs in `data` (source scripts' helper)."""
    offs: list[int] = []
    pos = 0
    while True:
        idx = data.find(pattern, pos)
        if idx == -1:
            break
        offs.append(idx)
        pos = idx + 1
    return offs


def signature_hits(data: bytes, signatures=None) -> dict[str, int]:
    """Count each signature needle's occurrences in `data`."""
    sigs = signatures if signatures is not None else EXE_SIGNATURES
    return {name: len(find_all(data, needle)) for name, needle in sigs}


def ascii_strings(data: bytes, min_len: int = 6, max_items: int = 100) -> dict:
    """Printable ASCII strings >= min_len: unique (case-insensitive), must
    contain at least one letter; returns {total, items:[{text, offset}]}."""
    found: dict[str, int] = {}
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % max(min_len, 1), data):
        text = m.group().decode("latin1")
        if not any(c.isalpha() for c in text):
            continue
        key = text.lower()
        if key not in found:
            found[key] = m.start()
    items = [{"text": t, "offset": off}
             for t, off in sorted(found.items(), key=lambda kv: kv[1])]
    return {"total": len(items), "items": items[:max_items]}


def x64_prolog_offsets(data: bytes) -> list[dict]:
    """All x86-64 function-prolog hits: {offset, pattern} sorted by offset."""
    out: list[dict] = []
    for needle, name in X64_PROLOG_PATTERNS:
        for off in find_all(data, needle):
            if needle == b"\x48\x83\xec":
                # 4th byte is the imm8; skip large frames (>= 0x80).
                if off + 4 > len(data) or data[off + 3] >= 0x80:
                    continue
            out.append({"offset": off, "pattern": name})
    return sorted(out, key=lambda d: d["offset"])


def byte_entropy(data: bytes) -> float:
    """Shannon entropy (bits/byte) of `data`."""
    if not data:
        return 0.0
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in Counter(data).values())


def uniform_variance(data: bytes) -> float:
    """Variance of the byte histogram around the uniform expectation
    (n/256 per byte value) — low variance => uniform => likely encrypted."""
    counts = Counter(data)
    n = len(data)
    expected = n / 256
    return sum((c - expected) ** 2 for c in counts.values()) / 256


def scan_valid_pclntab(data: bytes, max_search: int = 10 * 1024 * 1024) -> list[dict]:
    """Scan 4-byte aligned offsets for structurally valid Go pclntab headers
    (magic 0xfffffffa/fb, pad==0, ptrSize in (4, 8), 0 < nfunc < 500000).
    Returns [{offset, version, ptr_size, nfunc}]."""
    hits: list[dict] = []
    end = min(len(data), max_search) - 16
    for off in range(0, end, 4):
        val = struct.unpack_from("<I", data, off)[0]
        if val in GO_PCLNTAB_MAGICS:
            pad = struct.unpack_from("<H", data, off + 4)[0]
            ptr_size = data[off + 7]
            nfunc = struct.unpack_from("<I", data, off + 8)[0]
            if pad == 0 and ptr_size in (4, 8) and 0 < nfunc < MAX_NFUNC:
                hits.append({
                    "offset": off,
                    "version": "1.16+" if val == 0xFFFFFFFB else "1.2-1.15",
                    "ptr_size": ptr_size,
                    "nfunc": nfunc,
                })
    return hits
