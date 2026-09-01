#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/extract-syscalls.py — x64 syscall stub extraction (issue #278 PR-1b).

Absorbed from D:/works/samples/2026-06-10/scripts/extract_syscalls.py: the
`syscall` (0F 05) scan with `mov eax, imm32` (B8) and `mov r10, rcx` (4C 8B D1)
backtracking, plus the Windows NT syscall-number -> name map.  The
sample-specific dump-directory hardcoding is removed — input is a CLI argument.

Usage:
  extract-syscalls --in sample.bin                 # raw-byte scan (default)
  extract-syscalls --in disasm.txt --mode text     # disassembly-text scan
  extract-syscalls --in sample.bin --json          # single JSON object
  extract-syscalls --in sample.bin --reproduce     # L1 gate field=value lines

Exit codes: 0 = found >=1 syscall stub, 1 = negative finding (input scanned,
no stub), 2 = error (bad args / unreadable input).  Errors print a structured
JSON object to stderr: {"error": "...", "exit_code": 2}.
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402


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
    parse_line,
    read_bytes,
    read_text,
    report,
    sha256,
)

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.

# Windows NT syscall number -> name map (x64), per the source script.
SYSCALL_MAP = {
    0x08: "NtAdjustPrivilegesToken", 0x0B: "NtAllocateVirtualMemory",
    0x18: "NtCancelIoFile", 0x1C: "NtClearEvent", 0x1D: "NtClose",
    0x2C: "NtCreateFile", 0x2E: "NtCreateKey", 0x35: "NtCreateMutant",
    0x3F: "NtCreateProcessEx", 0x41: "NtCreateSection",
    0x47: "NtCreateThreadEx", 0x4E: "NtDelayExecution",
    0x50: "NtDeleteBootEntry", 0x53: "NtDeleteKey", 0x5C: "NtDuplicateObject",
    0x6D: "NtFlushBuffersFile", 0x76: "NtFreeVirtualMemory",
    0x7E: "NtGetContextThread", 0x81: "NtGetNextThread",
    0xA0: "NtMapViewOfSection", 0xB3: "NtOpenFile",
    0xB7: "NtOpenKey", 0xC2: "NtOpenProcess", 0xC4: "NtOpenProcessTokenEx",
    0xC8: "NtOpenSection", 0xD0: "NtOpenThreadToken",
    0xE3: "NtProtectVirtualMemory", 0xE7: "NtQueryAttributesFile",
    0xF2: "NtQueryDirectoryFile", 0xF9: "NtQueryEvent",
    0xFD: "NtQueryInformationFile", 0x100: "NtQueryInformationProcess",
    0x101: "NtQueryInformationThread", 0x102: "NtQueryInformationToken",
    0x109: "NtQueryKey", 0x113: "NtQuerySection",
    0x11A: "NtQuerySystemInformation", 0x120: "NtQueryTimer",
    0x123: "NtQueryValueKey", 0x124: "NtQueryVirtualMemory",
    0x125: "NtQueryVolumeInformationFile", 0x128: "NtQueueApcThread",
    0x12E: "NtReadFile", 0x133: "NtReadVirtualMemory",
    0x13E: "NtReleaseMutant", 0x13F: "NtReleaseSemaphore",
    0x157: "NtResumeThread", 0x173: "NtSetEvent",
    0x17B: "NtSetInformationFile", 0x17E: "NtSetInformationObject",
    0x17F: "NtSetInformationProcess", 0x180: "NtSetInformationThread",
    0x1A2: "NtSetValueKey", 0x1AB: "NtSuspendProcess",
    0x1AC: "NtSuspendThread", 0x1B1: "NtTerminateProcess",
    0x1B2: "NtTerminateThread", 0x1C8: "NtUnmapViewOfSection",
    0x1D2: "NtWaitForSingleObject", 0x1DA: "NtWriteFile",
    0x1DD: "NtWriteVirtualMemory",
}

SYSCALL_OP = b"\x0f\x05"        # syscall
MOV_R10_RCX = b"\x4c\x8b\xd1"   # mov r10, rcx
_MOV_EAX_RE = re.compile(r"^mov\s+eax\s*,\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]+h|\d+)$", re.I)
_SYSCALL_INS_RE = re.compile(r"^syscall\b", re.I)


def _stub(location: str, number: int, kind: str) -> dict:
    return {"location": location, "number": number,
            "name": SYSCALL_MAP.get(number), "kind": kind}


def scan_bytes(data: bytes) -> list[dict]:
    """Find `mov eax, imm32; syscall` stubs (optionally `mov r10, rcx` first).

    For every `syscall` (0F 05) walks back up to 12 bytes for the `mov eax,
    imm32` (B8) that loads the syscall number.
    """
    stubs = []
    n = len(data)
    i = 0
    while i < n - 1:
        if data[i : i + 2] == SYSCALL_OP:
            for back in range(2, 12):
                pos = i - back
                if pos < 0:
                    break
                if data[pos] == 0xB8 and pos + 5 <= n:
                    num = int.from_bytes(data[pos + 1 : pos + 5], "little")
                    stubs.append(_stub(f"0x{pos:x}", num, "mov-eax"))
                    break
                if (pos + 4 <= i and data[pos : pos + 3] == MOV_R10_RCX
                        and data[pos + 3] == 0xB8 and pos + 8 <= n):
                    num = int.from_bytes(data[pos + 4 : pos + 8], "little")
                    stubs.append(_stub(f"0x{pos:x}", num, "mov-r10-rcx"))
                    break
            i += 2
        else:
            i += 1
    return stubs


def _parse_imm(text: str) -> int:
    """mov eax operand -> int: 0x hex / trailing-h hex / decimal."""
    if text.lower().startswith("0x"):
        return int(text, 16)
    if text.lower().endswith("h"):
        return int(text[:-1], 16)
    return int(text, 10)


def scan_text(text: str, max_back: int = 3) -> list[dict]:
    """Parse disassembly listing lines for `mov eax, imm` before `syscall`."""
    lines = [parse_line(line) for line in text.splitlines()]
    stubs = []
    for idx, (addr, insn) in enumerate(lines):
        if not insn or not _SYSCALL_INS_RE.match(insn):
            continue
        for j in range(idx - 1, max(idx - 1 - max_back, -1), -1):
            prev_insn = lines[j][1] or ""
            m = _MOV_EAX_RE.match(prev_insn)
            if m:
                num = _parse_imm(m.group(1))
                stubs.append(_stub(lines[j][0] or "unknown", num, "mov-eax"))
                break
    return stubs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="extract-syscalls",
        description="x64 syscall stub extraction from raw bytes or "
                    "disassembly text (issue #278 PR-1b)")
    add_common_flags(ap)
    ap.add_argument("--mode", choices=("bin", "text"), default="bin",
                    help="bin = scan raw bytes (default); text = parse "
                         "disassembly listing lines")
    ap.add_argument("--no-names", action="store_true",
                    help="report syscall numbers only, skip the NT name lookup")
    ap.add_argument("--max-back", type=int, default=3, metavar="N",
                    help="text mode: max lines scanned back from a syscall "
                         "instruction (default 3)")
    args = ap.parse_args(argv)

    if args.mode == "bin":
        data = read_bytes(args.in_path)
        input_sha = sha256(data)
        stubs = scan_bytes(data)
    else:
        text = read_text(args.in_path)
        input_sha = sha256(text.encode("utf-8", errors="replace"))
        stubs = scan_text(text, max_back=args.max_back)

    if args.no_names:
        for stub in stubs:
            stub["name"] = None

    total = len(stubs)
    unique_count = len({s["number"] for s in stubs})
    if not stubs:
        return negative(args, "extract-syscalls", mode=args.mode,
                        total=0, unique=0)

    text_lines = [f"location={s['location']} number=0x{s['number']:x} "
                  f"name={s['name'] or '?'}" for s in stubs]
    json_obj = {
        "tool": "extract-syscalls",
        "mode": args.mode,
        "input_sha256": input_sha,
        "total": total,
        "unique": unique_count,
        "stubs": [{"location": s["location"], "number": s["number"],
                   "name": s["name"], "kind": s["kind"]} for s in stubs],
    }
    reproduce_rows = {
        "tool": "extract-syscalls",
        "mode": args.mode,
        "input_sha256": input_sha,
        "total": total,
        "unique": unique_count,
        "first": stubs[0]["location"],
        "last": stubs[-1]["location"],
    }
    return report(args, text_lines, json_obj, reproduce_rows)


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
