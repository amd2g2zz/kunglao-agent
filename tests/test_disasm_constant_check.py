# -*- coding: utf-8 -*-
"""RED tests for disasm-constant-byte-exact-checker (issue #50, a2b5e25c problem 1).

TDD: these tests import tools/static/disasm_constant_check.py which does NOT exist
yet → RED. Implementation makes them GREEN.

Covers:
  RED1: report listing `frameRateNum=bitrate` vs fact expected `fps` → blocked
  RED2: listing matches disasm + fact (gopLength=0x1ffffffff, scaled pass) → ok
  RED2b: fact mode gopLength=0xFFFFFFFF @site vs disasm 0x1ffffffff → mismatch (F015 shape)
  RED3: VA outside all sections → error entry, no crash
  RED4: empty listing / no VA anchors → ok, no crash
  backtest: a2b5e25c 10-assignment report listing → blocked (frameRateNum /
           averageBitRate / gopLength named)
  integration: verify(binary_path=pe) mismatch → REJECTED + disasm key;
               verify() without binary → shape unchanged
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ("scripts", "hooks", "tools", "tools/static", "tools/_lib"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))


# =====================================================================
# Synthetic PE64 fixture (design D7)
# =====================================================================

def _build_pe(path: Path) -> Path:
    """Minimal PE64: image base 0x140000000, one .text section (RVA 0x1000,
    raw offset 0x200, FileAlignment 0x200) with crafted instructions."""
    code = bytearray(0x200)
    # RVA 0x1010: mov rax, 0x1ffffffff            (gopLength site)
    code[0x10:0x1A] = bytes.fromhex("48 b8 ff ff ff ff 01 00 00 00")
    # RVA 0x101A: mov eax, 0x3e8                  (1000 constant)
    code[0x1A:0x1F] = bytes.fromhex("b8 e8 03 00 00")
    # RVA 0x101F: imul eax, eax, 0x3e8            (scaled-rule site)
    code[0x1F:0x25] = bytes.fromhex("69 c0 e8 03 00 00")
    # RVA 0x1025: mov qword ptr [r12+0x1134], rbx     (frameRateNum store, no immediate)
    code[0x25:0x2D] = bytes.fromhex("49 89 9c 24 34 11 00 00")
    # RVA 0x102D: mov eax, 1                      (frameRateDen site)
    code[0x2D:0x32] = bytes.fromhex("b8 01 00 00 00")

    pe = bytearray(0x400)
    pe[0:2] = b"MZ"
    struct.pack_into("<I", pe, 0x3C, 0x80)
    pe[0x80:0x84] = b"PE\x00\x00"
    # COFF header at 0x84
    struct.pack_into("<HHIIIHH", pe, 0x84, 0x8664, 1, 0, 0, 0, 0xF0, 0x22)
    # Optional header PE32+ at 0x98
    o = 0x98
    struct.pack_into("<HBBIIIII", pe, o, 0x20B, 0, 0, 0x200, 0, 0, 0x1010, 0x1000)
    struct.pack_into("<QII", pe, o + 24, 0x140000000, 0x1000, 0x200)
    struct.pack_into("<HHHHHHII", pe, o + 40, 6, 0, 0, 0, 6, 0, 0, 0x2000)
    struct.pack_into("<IIHHQQQQII", pe, o + 60, 0x200, 0, 3, 0,
                     0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    # 16 data directories (all zero)
    struct.pack_into("<128s", pe, o + 112, b"\x00" * 128)
    # Section header '.text' at 0x188
    s = 0x188
    struct.pack_into("<8sIIIIIIHHI", pe, s, b".text\x00\x00\x00", 0x200, 0x1000,
                     0x200, 0x200, 0, 0, 0, 0, 0x60000020)
    pe[0x200:0x400] = code
    path.write_bytes(pe)
    return path


def _fact_text(expected: str, body_code: str = "") -> str:
    return (f"---\nid: F050\nclaim: C-1\nreproduce: ''\nexpected: {expected}\n"
            f"---\n\n{body_code}\n")


def _expects(*fields: tuple[str, str]) -> str:
    return "; ".join(f"{f}={v}" for f, v in fields)


# =====================================================================
# RED1: report listing vs fact expected — cross-layer catch
# =====================================================================

def test_red1_report_frameRateNum_bitrate_blocked(tmp_path):
    """Report claims frameRateNum=bitrate, fact expects fps → blocked."""
    from disasm_constant_check import check_report_listing
    pe = _build_pe(tmp_path / "sample.exe")
    fact = _fact_text(_expects(("frameRateNum", "fps"), ("gopLength", "0x1ffffffff")),
                      "```text\n0x140001025: frameRateNum=fps\n```\n")
    listing = "0x140001025: frameRateNum=bitrate\n"
    result = check_report_listing(listing, fact, pe)
    assert not result["ok"], "cross-layer mismatch must block the report"
    fields = {m["field"] for m in result["mismatches"]}
    assert "frameRateNum" in fields


# =====================================================================
# RED2: matching listing passes
# =====================================================================

def test_red2_listing_matches_fact_and_disasm(tmp_path):
    """gopLength constant + scaled averageBitRate both match fact AND disasm."""
    from disasm_constant_check import check_report_listing
    pe = _build_pe(tmp_path / "sample.exe")
    fact = _fact_text(_expects(
        ("frameRateNum", "fps"), ("frameRateDen", "1"),
        ("averageBitRate", "bitrate*1000"), ("maxBitRate", "bitrate"),
        ("gopLength", "0x1ffffffff")))
    listing = ("0x140001010: gopLength=0x1ffffffff\n"
               "0x14000101f: averageBitRate=bitrate*1000\n")
    result = check_report_listing(listing, fact, pe)
    assert result["ok"], f"matching listing must pass: {result}"
    assert result["mismatches"] == []


def test_red2b_fact_mode_f015_shape_mismatch(tmp_path):
    """Fact claims gopLength=0xFFFFFFFF, disasm is mov rax, 0x1ffffffff →
    byte-exact mismatch (the a2b5e25c F015 shape)."""
    from disasm_constant_check import check_fact_disasm
    pe = _build_pe(tmp_path / "sample.exe")
    fact = _fact_text(_expects(("gopLength", "0x1ffffffff")),
                      "```text\n0x140001010: gopLength=0xFFFFFFFF\n```\n")
    result = check_fact_disasm(fact, pe)
    assert not result["ok"], "byte-exact mismatch must be caught at fact layer"
    assert any("gopLength" in m["field"] for m in result["mismatches"])
    assert any("0x1ffffffff" in m["reason"] for m in result["mismatches"])


# =====================================================================
# RED3: VA outside all sections → error entry, no crash
# =====================================================================

def test_red3_va_outside_sections_error(tmp_path):
    """VA mapping to no PE section → error entry, no exception."""
    from disasm_constant_check import check_report_listing
    pe = _build_pe(tmp_path / "sample.exe")
    fact = _fact_text(_expects(("gopLength", "0x1ffffffff")))
    listing = "0x140005000: mysteryField=0x1\n"
    result = check_report_listing(listing, fact, pe)
    assert not result["ok"], "unmapped VA must produce an error"
    joined = " ".join(str(m) for m in result["mismatches"] + result.get("errors", []))
    assert "0x140005000" in joined


# =====================================================================
# RED4: empty / no-VA input → no crash
# =====================================================================

def test_red4_empty_listing_ok(tmp_path):
    from disasm_constant_check import check_report_listing
    pe = _build_pe(tmp_path / "sample.exe")
    fact = _fact_text(_expects(("frameRateNum", "fps")))
    result = check_report_listing("", fact, pe)
    assert result["ok"]
    assert result["mismatches"] == []


def test_red4_no_va_anchors_ok(tmp_path):
    """Assertions without VAs: cross-layer SKIP for unknown fields, no crash."""
    from disasm_constant_check import check_report_listing
    pe = _build_pe(tmp_path / "sample.exe")
    fact = _fact_text(_expects(("frameRateNum", "fps")))
    result = check_report_listing("mysteryField=0x1\n", fact, pe)
    assert result["ok"], f"unknown-field listing must pass: {result}"


def test_red4_empty_fact_mode_ok(tmp_path):
    from disasm_constant_check import check_fact_disasm
    pe = _build_pe(tmp_path / "sample.exe")
    result = check_fact_disasm("---\nid: F1\nclaim: C-1\n---\nno assertions\n", pe)
    assert result["ok"]
    assert result["mismatches"] == []


# =====================================================================
# a2b5e25c backtest: the 10-assignment report listing
# =====================================================================

def test_backtest_a2b5e25c_report_blocked(tmp_path):
    """Incident listing: frameRateNum=bitrate (fact fps), averageBitRate=
    bitrate*1000 (fact bitrate), gopLength=fps (fact constant) → blocked."""
    from disasm_constant_check import check_report_listing
    pe = _build_pe(tmp_path / "sample.exe")
    fact = _fact_text(_expects(
        ("frameRateNum", "fps"), ("frameRateDen", "1"),
        ("averageBitRate", "bitrate"), ("maxBitRate", "bitrate"),
        ("gopLength", "0x1ffffffff")))
    listing = ("0x140001025: frameRateNum=bitrate\n"
               "0x14000102d: frameRateDen=1\n"
               "0x14000101f: averageBitRate=bitrate*1000\n"
               "0x140001020: maxBitRate=bitrate\n"
               "0x140001010: gopLength=fps\n"
               "0x140001011: iframeInterval=0\n"
               "0x140001012: preset=medium\n"
               "0x140001013: profile=main\n"
               "0x140001014: level=0\n"
               "0x140001015: quality=high\n")
    result = check_report_listing(listing, fact, pe)
    assert not result["ok"], "a2b5e25c listing must be blocked"
    fields = {m["field"] for m in result["mismatches"]}
    assert {"frameRateNum", "averageBitRate", "gopLength"} <= fields


# =====================================================================
# Integration: verify() post-gate
# =====================================================================

def test_verify_disasm_gate_rejects(ws_factory, tmp_path):
    """verify(binary_path=pe) on a fact whose VA-anchored claim mismatches the
    binary → overall REJECTED with the disasm result recorded."""
    pe = _build_pe(tmp_path / "sample.exe")
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    (ws / "facts").mkdir(parents=True, exist_ok=True)
    (ws / "facts" / "F050.md").write_text(
        "---\nid: F050\nclaim: C-1\nreproduce: ''\nexpected: ''\n---\n\n"
        "```text\n0x140001010: gopLength=0xFFFFFFFF\n```\n", encoding="utf-8")
    from kunglao_verify import verify
    out = verify(ws, "F050", binary_path=pe)
    assert out["disasm"]["ok"] is False, f"disasm gate must catch the mismatch: {out}"
    assert out["overall"] == "REJECTED"


def test_verify_without_binary_shape_unchanged(ws_factory):
    """verify() without binary_path: no disasm key, output shape unchanged."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    (ws / "facts").mkdir(parents=True, exist_ok=True)
    (ws / "facts" / "F050.md").write_text(
        "---\nid: F050\nclaim: C-1\nreproduce: ''\nexpected: ''\n---\n\n"
        "```text\n0x140001010: gopLength=0xFFFFFFFF\n```\n", encoding="utf-8")
    from kunglao_verify import verify
    out = verify(ws, "F050")
    assert "disasm" not in out, "no binary → gate must not run"


# =====================================================================
# Fixture sanity (independent of the tool)
# =====================================================================

def test_fixture_pe_parses_and_disassembles(tmp_path):
    """The synthetic PE must parse with pefile and disassemble at the sites."""
    import capstone
    import pefile
    pe_path = _build_pe(tmp_path / "sample.exe")
    pe = pefile.PE(str(pe_path))
    assert pe.FILE_HEADER.Machine == 0x8664
    assert pe.OPTIONAL_HEADER.ImageBase == 0x140000000
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    code = pe_path.read_bytes()
    insn = next(md.disasm(code[0x210:0x210 + 32], 0x140001010))
    assert insn.mnemonic in ("mov", "movabs") and insn.op_str == "rax, 0x1ffffffff"
    insn2 = next(md.disasm(code[0x225:0x225 + 16], 0x140001025))
    assert insn2.mnemonic == "mov" and insn2.op_str.startswith("qword ptr [r12 + 0x1134]")
