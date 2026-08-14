# -*- coding: utf-8 -*-
"""tools/static/_common.py — shared byte-scan helpers for the static CLIs.

Extracted from the D:/works/samples script accumulation (overlay_analysis.py,
true_overlay_check.py, disasm_stage3.py) so overlay_scan / disasm_dump /
shellcode_scan share one implementation of signature search, string
extraction, prolog scan, entropy and Go-pclntab validation (issue #278 PR-1c).

Contract (#277): pure side-effect-free functions, no hardcoded paths, no
imports of the sibling tools — this module is importable on its own.
"""
from __future__ import annotations

import math
import re
import struct
import sys
from collections import Counter

# r2-278-1c H1: decoded binary content can carry U+FFFD (decode(errors="replace"));
# a GBK console (Windows) cannot encode it and a bare UnicodeEncodeError traceback
# would break the "structured error, never a traceback" CLI contract. Unify stdout
# on UTF-8 (all characters encodable; Claude Code captures subprocess stdout as
# UTF-8) with errors="replace" as belt-and-braces for unpaired surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

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
