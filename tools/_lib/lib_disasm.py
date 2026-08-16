"""lib_disasm.py — shared PE/capstone disassembly helpers (issue #284).

Extracted from disasm_constant_check.py (now tools/static/, #340) so future disasm tools (e.g. the
PR-1c disasm-dump) can reuse the VA→file-offset mapping and capstone setup
without re-implementing them. Contract (#277): module functions are importable
and side-effect free; no hardcoded paths.

  load_pe(path)              -> pefile.PE
  va_to_offset(pe, va)       -> int | None   (VA → raw file offset; None unmapped)
  capstone_for(pe)           -> capstone.Cs
  disasm_at(pe, raw, va, n)  -> list[dict] | None

disasm_constant_check re-imports these (names preserved), so its exported
surface (`check_fact_disasm` / `check_report_listing` / the private helpers)
is unchanged for existing callers.
"""
from __future__ import annotations

from pathlib import Path

import capstone
import capstone.x86
import pefile


def load_pe(binary_path: Path) -> pefile.PE:
    """Load a PE with pefile fast_load=True."""
    return pefile.PE(str(binary_path), fast_load=True)


def va_to_offset(pe: pefile.PE, va: int) -> int | None:
    """VA → raw file offset via section mapping. None when the VA is not in any
    section or is mapped but not raw-resident."""
    rva = va - pe.OPTIONAL_HEADER.ImageBase
    for s in pe.sections:
        span = max(s.Misc_VirtualSize, s.SizeOfRawData)
        if s.VirtualAddress <= rva < s.VirtualAddress + span:
            off = rva - s.VirtualAddress + s.PointerToRawData
            if s.PointerToRawData <= off < s.PointerToRawData + s.SizeOfRawData:
                return off
            return None
    return None


def capstone_for(pe: pefile.PE) -> capstone.Cs:
    """Capstone disassembler for the PE's architecture (x86-64 vs x86-32)."""
    mode = capstone.CS_MODE_64 if pe.FILE_HEADER.Machine == 0x8664 else capstone.CS_MODE_32
    md = capstone.Cs(capstone.CS_ARCH_X86, mode)
    md.detail = True
    return md


def disasm_at(pe: pefile.PE, raw: bytes, va: int, count: int = 2) -> list[dict] | None:
    """Disassemble up to `count` instructions at VA. None when VA is unmapped.

    Each instruction dict: {addr, mnemonic, op_str, imm} where imm is the first
    immediate operand (None when the instruction has none).
    """
    off = va_to_offset(pe, va)
    if off is None or off >= len(raw):
        return None
    md = capstone_for(pe)
    out: list[dict] = []
    for ins in md.disasm(raw[off:off + 32], va):
        imm = None
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_IMM:
                imm = op.imm
                break
        out.append({"addr": ins.address, "mnemonic": ins.mnemonic,
                    "op_str": ins.op_str, "imm": imm})
        if len(out) >= count:
            break
    return out
