#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/call-site-args.py — call-site argument extraction from
disassembly text (issue #278 PR-1b).

Absorbed from:
- D:/works/samples/2026-06-10/scripts/analysis/build_xpsplog_payload_evidence.py
  — callsite address -> argument list structure (entrypoint_args /
  export_call_args);
- D:/works/samples/2026-06-10/scripts/analysis/qiling_npwzwmc64_realargs_native_probe.py
  — the x64 register argument model (rcx/rdx/r8/r9 + stack slots).
Sample-specific hardcoded callsites are removed; the disassembly listing is
now the CLI input and the argument window is a parameter.

Usage:
  call-site-args --in disasm.txt
  call-site-args --in disasm.txt --window 12 --abi x86
  call-site-args --in disasm.txt --json / --reproduce

For each `call` instruction the tool walks the preceding window and collects:
x64 = mov rcx/rdx/r8/r9 operand loads (closest wins) + [rsp+disp] stores (5th+
args); x86 = push instructions in argument order.  Lines look like
`0x401000  mov rcx, 0x22e044` (address optional, ':'/'|' separators allowed).
Exit codes: 0 = found >=1 call site, 1 = negative finding (no call), 2 = error
(bad args / unreadable input).  Errors print a structured JSON object to
stderr: {"error": "...", "exit_code": 2}.
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
    negative,
    parse_line,
    read_text,
    report,
    sha256,
)

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.

CALL_INS_RE = re.compile(r"^(?:call|bl)\b", re.I)
MOV_ARG_RE = re.compile(
    r"^mov\s+(rcx|rdx|r8|r9|ecx|edx|r8d|r9d)\s*,\s*(.+)$", re.I)
STACK_STORE_RE = re.compile(
    r"^mov\s+(?:dword|qword)\s+ptr\s+\[rsp\s*\+\s*0x([0-9a-fA-F]+)\]\s*,\s*(.+)$",
    re.I)
PUSH_RE = re.compile(r"^push\s+(.+)$", re.I)

_ARG_REG_NORM = {"ecx": "rcx", "edx": "rdx", "r8d": "r8", "r9d": "r9"}

# Canonical output order for x64 argument registers.
_ARG_REG_ORDER = ("rcx", "rdx", "r8", "r9")


def _ordered_regs(regs: dict[str, str]) -> list[tuple[str, str]]:
    return [(r, regs[r]) for r in _ARG_REG_ORDER if r in regs]


def extract_callsites(text: str, window: int, abi: str) -> list[dict]:
    """Parse disassembly listing lines; per `call`, walk back ``window``
    instructions collecting argument-loading state."""
    lines = [parse_line(line) for line in text.splitlines()]
    callsites = []
    for idx, (addr, insn) in enumerate(lines):
        if not insn or not CALL_INS_RE.match(insn):
            continue
        target = CALL_INS_RE.sub("", insn).strip() or "?"
        regs: dict[str, str] = {}
        stack: dict[str, str] = {}
        pushed: list[str] = []
        lo = max(0, idx - window)
        for j in range(idx - 1, lo - 1, -1):
            prev = lines[j][1] or ""
            if abi == "x64":
                m = MOV_ARG_RE.match(prev)
                if m:
                    name = _ARG_REG_NORM.get(m.group(1).lower(),
                                             m.group(1).lower())
                    regs.setdefault(name, m.group(2).strip())
                    continue
                m = STACK_STORE_RE.match(prev)
                if m:
                    stack.setdefault(m.group(1), m.group(2).strip())
                    continue
            else:
                m = PUSH_RE.match(prev)
                if m:
                    pushed.append(m.group(1).strip())
        callsites.append({
            "address": addr or "unknown",
            "target": target,
            "args": {
                "regs": regs,
                "stack": [{"disp": f"0x{d}", "value": v}
                          for d, v in stack.items()],
                "pushed": list(reversed(pushed)),
            },
        })
    return callsites


def _fmt(callsite: dict) -> str:
    parts = [f"addr={callsite['address']}", f"target={callsite['target']}"]
    for reg, val in _ordered_regs(callsite["args"]["regs"]):
        parts.append(f"{reg}={val}")
    for slot in callsite["args"]["stack"]:
        parts.append(f"stack[{slot['disp']}]={slot['value']}")
    for i, val in enumerate(callsite["args"]["pushed"]):
        parts.append(f"push{i}={val}")
    return " ".join(parts)


def _has_args(callsite: dict) -> bool:
    args = callsite["args"]
    return bool(args["regs"] or args["stack"] or args["pushed"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="call-site-args",
        description="call-site argument extraction from disassembly text "
                    "(issue #278 PR-1b)")
    add_common_flags(ap)
    ap.add_argument("--window", type=int, default=8, metavar="N",
                    help="max instructions scanned backwards per call "
                         "(default 8)")
    ap.add_argument("--abi", choices=("x64", "x86"), default="x64",
                    help="calling convention (default x64)")
    args = ap.parse_args(argv)

    text = read_text(args.in_path)
    input_sha = sha256(text.encode("utf-8", errors="replace"))
    callsites = extract_callsites(text, window=args.window, abi=args.abi)

    total = len(callsites)
    with_args = sum(1 for c in callsites if _has_args(c))
    if not callsites:
        return negative(args, "call-site-args", abi=args.abi, total=0)

    text_lines = [_fmt(c) for c in callsites]
    json_obj = {
        "tool": "call-site-args",
        "abi": args.abi,
        "input_sha256": input_sha,
        "total_callsites": total,
        "total_with_args": with_args,
        "callsites": callsites,
    }
    reproduce_rows = {
        "tool": "call-site-args",
        "abi": args.abi,
        "input_sha256": input_sha,
        "total_callsites": total,
        "total_with_args": with_args,
        "first_address": callsites[0]["address"],
        "first_target": callsites[0]["target"],
    }
    first_regs = ",".join(f"{r}={v}"
                          for r, v in _ordered_regs(callsites[0]["args"]["regs"]))
    if first_regs:
        reproduce_rows["first_regs"] = first_regs
    return report(args, text_lines, json_obj, reproduce_rows)


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
