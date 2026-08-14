# -*- coding: utf-8 -*-
"""tests/test_static_tools_1c.py — issue #278 PR-1c: 5 absorbed static CLIs.

Covers per tool: --help exit 0, tmp-file parameterized input, three-state exit
codes (0 ok / 1 negative finding / 2 error), --json single-object output,
--reproduce field=value lines (kunglao L1 mechanical-gate format), and edge
cases (missing file, non-PE, no overlay, unmapped RVA, empty blob).

pe-analyze / overlay-scan / disasm-dump run against a REAL tiny PE64 fixture
built byte-by-byte in-test (imports / exports / resources / debug-PDB /
reloc section / overlay with a fake relocation block + embedded MZ-PE), the
same technique as tests/test_disasm_constant_check.py; its parseability is
pinned by test_fixture_pe_parses_with_pefile.
"""
from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "tools" / "static"
TOOLS = ROOT / "tools"
for sub in ("scripts", "hooks", "tools", "tools/static", "tools/_lib"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

# Matches scripts/kunglao_verify.py _ACTUAL_ASSERTION_RE (L1 field=value parser).
L1_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")

MANIFEST = b'<?xml version="1.0"?><assembly xmlns="urn:schemas-microsoft-com:asm.v1"/>\x00'
PDB_PATH = b"C:\\proj\\synthetic.pdb\x00"


def _parse_reproduce(stdout: str) -> dict:
    return dict(L1_LINE_RE.match(line).groups() for line in stdout.splitlines()
                if L1_LINE_RE.match(line))


def _parse_json(stdout: str) -> dict:
    assert L1_LINE_RE.match(stdout.splitlines()[0]) is None, "expected JSON, got field=value"
    return json.loads(stdout)


# =====================================================================
# Real tiny PE64 fixture (design: parses with pefile, has real tables)
# =====================================================================

def _build_sample_pe(path: Path, *, overlay: bool = True, go_pclntab: bool = False) -> Path:
    """PE32+ x64, base 0x140000000: .text (code + prologs + PEB + string),
    .rdata (kernel32.dll import by name+ordinal, export ExportedFunc, MANIFEST
    resource, RSDS debug dir), .reloc, optional overlay."""
    code = bytearray(0x200)
    code[0x10:0x1A] = bytes.fromhex("48 b8 ff ff ff ff 01 00 00 00")  # mov rax, 0x1ffffffff
    code[0x1A:0x1F] = b"\x48\x89\x5c\x24\x08"                          # prolog (5 bytes)
    code[0x1F:0x23] = b"\x48\x83\xec\x30"                              # prolog
    code[0x23:0x28] = bytes.fromhex("b8 e8 03 00 00")                  # mov eax, 0x3e8
    code[0x28:0x31] = bytes.fromhex("64 48 8b 04 25 60 00 00 00")      # PEB access
    code[0x31:0x31 + 14] = b"HelloShellcode"

    rdata = bytearray(0x800)
    # import descriptor (kernel32.dll)
    struct.pack_into("<IIIII", rdata, 0x00, 0x2070, 0, 0, 0x2040, 0x2090)
    rdata[0x40:0x40 + 13] = b"kernel32.dll\x00"
    struct.pack_into("<QQQ", rdata, 0x70, 0x20B0, 0x8000000000000002, 0)      # ILT
    struct.pack_into("<QQQ", rdata, 0x90, 0x20B0, 0x8000000000000002, 0)      # IAT
    struct.pack_into("<H", rdata, 0xB0, 0x0023)                               # hint
    rdata[0xB2:0xB2 + 12] = b"ExitProcess\x00"
    # export directory
    struct.pack_into("<IIHHIIIIIII", rdata, 0x100, 0, 0x12345678, 0, 0,
                     0x2150, 1, 1, 1, 0x2140, 0x2144, 0x2148)
    struct.pack_into("<I", rdata, 0x140, 0x1010)                              # functions
    struct.pack_into("<I", rdata, 0x144, 0x2160)                              # names
    struct.pack_into("<H", rdata, 0x148, 0)                                   # ordinals
    rdata[0x150:0x150 + 14] = b"synthetic.dll\x00"
    rdata[0x160:0x160 + 13] = b"ExportedFunc\x00"
    # resource directory: type 24 (MANIFEST) -> id 1 -> lang 1033 -> data
    struct.pack_into("<IIHHHH", rdata, 0x200, 0, 0, 0, 0, 0, 1)
    struct.pack_into("<II", rdata, 0x210, 24, 0x80000020)
    struct.pack_into("<IIHHHH", rdata, 0x220, 0, 0, 0, 0, 0, 1)
    struct.pack_into("<II", rdata, 0x230, 1, 0x80000040)
    struct.pack_into("<IIHHHH", rdata, 0x240, 0, 0, 0, 0, 0, 1)
    struct.pack_into("<II", rdata, 0x250, 1033, 0x60)
    struct.pack_into("<IIII", rdata, 0x260, 0x2280, len(MANIFEST), 0, 0)
    rdata[0x280:0x280 + len(MANIFEST)] = MANIFEST
    # debug directory: one CODEVIEW (RSDS) entry -> CV record at raw 0x820
    cv = b"RSDS" + bytes(range(16)) + struct.pack("<I", 1) + PDB_PATH
    struct.pack_into("<IIHHIIII", rdata, 0x400, 0, 0, 0, 0, 2, len(cv), 0, 0x820)
    rdata[0x420:0x420 + len(cv)] = cv

    reloc = bytearray(0x200)
    struct.pack_into("<IIHH", reloc, 0, 0x3000, 0x0C, (3 << 12) | 0x10, (3 << 12) | 0x20)

    pe = bytearray(0xE00)
    pe[0:2] = b"MZ"
    struct.pack_into("<I", pe, 0x3C, 0x80)
    pe[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<HHIIIHH", pe, 0x84, 0x8664, 3, 0, 0, 0, 0xF0, 0x0022)
    o = 0x98
    struct.pack_into("<HBBIIIII", pe, o, 0x20B, 0, 0, 0x200, 0, 0, 0x1010, 0x1000)
    struct.pack_into("<QII", pe, o + 24, 0x140000000, 0x1000, 0x200)
    struct.pack_into("<HHHHHHII", pe, o + 40, 6, 0, 0, 0, 6, 0, 0, 0x4000)
    struct.pack_into("<IIHH", pe, o + 60, 0x200, 0, 2, 0x8140)
    struct.pack_into("<QQQQ", pe, o + 72, 0x100000, 0x1000, 0x100000, 0x1000)
    struct.pack_into("<II", pe, o + 104, 0, 16)
    dirs = [(0x2100, 0x28), (0x2000, 0x50), (0x2200, 0x120), (0, 0), (0, 0),
            (0, 0), (0x2400, 0x1C)] + [(0, 0)] * 9
    for i, (rva, size) in enumerate(dirs):
        struct.pack_into("<II", pe, o + 112 + i * 8, rva, size)
    s = 0x188
    struct.pack_into("<8sIIIIIIHHI", pe, s, b".text\x00\x00\x00", 0x200, 0x1000,
                     0x200, 0x200, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<8sIIIIIIHHI", pe, s + 40, b".rdata\x00\x00", 0x800, 0x2000,
                     0x800, 0x400, 0, 0, 0, 0, 0x40000040)
    struct.pack_into("<8sIIIIIIHHI", pe, s + 80, b".reloc\x00\x00", 0x200, 0x3000,
                     0x200, 0xC00, 0, 0, 0, 0, 0x42000040)
    pe[0x200:0x400] = code
    pe[0x400:0xC00] = rdata
    pe[0xC00:0xE00] = reloc

    if overlay:
        ov = bytearray()
        ov += struct.pack("<II", 0x4000, 0x10)                     # fake reloc block
        for i in range(4):
            ov += struct.pack("<H", (10 << 12) | i)
        ov += b"OVERLAYPAYLOAD\x00"
        if go_pclntab:
            ov += b"\x00" * ((4 - len(ov) % 4) % 4)
            ov += struct.pack("<IHBB", 0xFFFFFFFB, 0, 0, 8)        # valid pclntab header
            ov += struct.pack("<I", 42)
        mz = bytearray(0x44)
        mz[0:2] = b"MZ"
        struct.pack_into("<I", mz, 0x3C, 0x40)
        mz[0x40:0x44] = b"PE\x00\x00"
        ov += mz
        ov += bytes((i * 7 + 3) % 256 for i in range(256))
        pe += ov
    path.write_bytes(pe)
    return path


def _build_shellcode_blob(path: Path) -> Path:
    blob = bytearray(0x400)
    blob[0x00:0x0A] = bytes.fromhex("48 b8 ff ff ff ff 01 00 00 00")
    blob[0x10:0x15] = b"\x48\x89\x5c\x24\x08"
    blob[0x15:0x19] = b"\x48\x83\xec\x30"
    blob[0x19:0x1C] = b"\x55\x48\x89\xe5"
    blob[0x20:0x29] = bytes.fromhex("64 48 8b 04 25 60 00 00 00")
    blob[0x30:0x30 + 14] = b"HelloShellcode"
    for i in range(0x40, 0x400, 2):
        blob[i] = 0x90
        blob[i + 1] = 0xC3
    path.write_bytes(blob)
    return path


def run_cli(tool: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(STATIC / tool), *args],
        # tools emit UTF-8 (stdout unified on UTF-8); decode as UTF-8, not the
        # GBK locale default, or multi-byte chars crash the reader thread
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )


# =====================================================================
# Fixture sanity (independent of the tools)
# =====================================================================

def test_fixture_pe_parses_with_pefile(tmp_path):
    import pefile
    pe_path = _build_sample_pe(tmp_path / "sample.exe")
    pe = pefile.PE(str(pe_path))
    assert pe.FILE_HEADER.Machine == 0x8664
    assert pe.OPTIONAL_HEADER.ImageBase == 0x140000000
    names = [i.name.decode("ascii", errors="replace")
             for i in pe.DIRECTORY_ENTRY_IMPORT[0].imports if i.name is not None]
    assert names == ["ExitProcess"]
    assert pe.DIRECTORY_ENTRY_EXPORT.symbols[0].name == b"ExportedFunc"
    assert pe.DIRECTORY_ENTRY_RESOURCE.entries[0].id == 24
    assert pe.DIRECTORY_ENTRY_DEBUG[0].struct.Type == 2
    assert pe.get_overlay_data_start_offset() == 0xE00


# =====================================================================
# pe-analyze
# =====================================================================

class TestPeAnalyze:
    def test_help_exit_zero(self):
        r = run_cli("pe_analyze.py", "--help")
        assert r.returncode == 0
        for sub in ("imports", "exports", "overlay"):
            assert sub in r.stdout

    def test_all_exit_zero_json(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("pe_analyze.py", "--binary", str(pe))
        assert r.returncode == 0, r.stderr
        data = _parse_json(r.stdout)
        keys = set(data["results"])
        assert {"headers", "sections", "imports", "exports", "resources",
                "overlay", "pdb", "tls", "signature"} <= keys
        dlls = [d["dll"] for d in data["results"]["imports"]]
        assert dlls == ["kernel32.dll"]
        assert data["results"]["exports"]["symbols"][0]["name"] == "ExportedFunc"
        assert data["results"]["pdb"]["entries"][0]["pdb_path"] == "C:\\proj\\synthetic.pdb"
        assert data["results"]["overlay"]["size"] > 0
        assert data["results"]["headers"]["subsystem"] == "WINDOWS_GUI"

    def test_subcommand_scopes_output(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("pe_analyze.py", "--binary", str(pe), "imports")
        assert r.returncode == 0
        assert set(_parse_json(r.stdout)["results"]) == {"imports"}

    def test_absent_table_exit_1(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        for sub in ("tls", "signature"):
            r = run_cli("pe_analyze.py", "--binary", str(pe), sub)
            assert r.returncode == 1, f"{sub} must be a negative finding"
            data = _parse_json(r.stdout)
            assert "note" in data["results"][sub]

    def test_no_overlay_exit_1(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe", overlay=False)
        r = run_cli("pe_analyze.py", "--binary", str(pe), "overlay")
        assert r.returncode == 1
        assert "no overlay" in _parse_json(r.stdout)["results"]["overlay"]["note"]

    def test_missing_file_exit_2(self, tmp_path):
        r = run_cli("pe_analyze.py", "--binary", str(tmp_path / "nope.exe"))
        assert r.returncode == 2
        assert "cannot read" in r.stderr

    def test_not_a_pe_exit_2(self, tmp_path):
        txt = tmp_path / "note.txt"
        txt.write_text("hello world", encoding="utf-8")
        r = run_cli("pe_analyze.py", "--binary", str(txt))
        assert r.returncode == 2
        assert "not a PE" in r.stderr

    def test_reproduce_l1_parseable(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("pe_analyze.py", "--binary", str(pe), "--reproduce")
        assert r.returncode == 0
        rows = _parse_reproduce(r.stdout)
        assert rows["tool"] == "pe-analyze"
        assert rows["machine"] == "0x8664"
        assert rows["num_sections"] == "3"
        assert rows["pdb_path"] == "C:\\proj\\synthetic.pdb"
        assert rows["tls_callbacks"] == "absent"

    def test_idempotent_repeat_runs(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r1 = run_cli("pe_analyze.py", "--binary", str(pe))
        r2 = run_cli("pe_analyze.py", "--binary", str(pe))
        assert r1.stdout == r2.stdout


# =====================================================================
# overlay-scan
# =====================================================================

class TestOverlayScan:
    def test_help_exit_zero(self):
        r = run_cli("overlay_scan.py", "--help")
        assert r.returncode == 0
        assert "reloc" in r.stdout and "true" in r.stdout and "mz" in r.stdout

    def test_reloc_mode_positive(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("overlay_scan.py", "--binary", str(pe), "--mode", "reloc")
        assert r.returncode == 0, r.stderr
        data = _parse_json(r.stdout)
        assert data["overlay_size"] > 0
        res = data["results"]["reloc"]
        assert res["is_reloc_table"] is True
        assert res["reloc_blocks"] >= 1
        assert res["first_block_entries"][0]["type"] == "DIR64"

    def test_mz_mode_finds_embedded_pe(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("overlay_scan.py", "--binary", str(pe), "--mode", "mz")
        assert r.returncode == 0, r.stderr
        res = _parse_json(r.stdout)["results"]["mz"]
        assert len(res["embedded_pe"]) >= 1

    def test_true_mode_go_negative_then_positive(self, tmp_path):
        clean = _build_sample_pe(tmp_path / "clean.exe")
        r = run_cli("overlay_scan.py", "--binary", str(clean), "--mode", "true")
        assert r.returncode == 1  # no Go evidence -> negative finding
        assert _parse_json(r.stdout)["results"]["true"]["go_evidence"] is False

        go = _build_sample_pe(tmp_path / "go.exe", go_pclntab=True)
        r = run_cli("overlay_scan.py", "--binary", str(go), "--mode", "true")
        assert r.returncode == 0, r.stderr
        res = _parse_json(r.stdout)["results"]["true"]
        assert res["go_evidence"] is True
        assert len(res["pclntab_valid"]) >= 1

    def test_no_overlay_exit_1(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe", overlay=False)
        for mode in ("reloc", "true", "mz"):
            r = run_cli("overlay_scan.py", "--binary", str(pe), "--mode", mode)
            assert r.returncode == 1, f"{mode} with no overlay must be a negative finding"
            assert _parse_json(r.stdout)["overlay_size"] == 0

    def test_missing_file_exit_2(self, tmp_path):
        r = run_cli("overlay_scan.py", "--binary", str(tmp_path / "nope.exe"))
        assert r.returncode == 2
        assert "cannot read" in r.stderr

    def test_bad_mode_exit_2(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("overlay_scan.py", "--binary", str(pe), "--mode", "bogus")
        assert r.returncode == 2

    def test_reproduce_l1_parseable(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("overlay_scan.py", "--binary", str(pe), "--mode", "reloc", "--reproduce")
        assert r.returncode == 0
        rows = _parse_reproduce(r.stdout)
        assert rows["tool"] == "overlay-scan"
        assert rows["mode"] == "reloc"
        assert int(rows["overlay_size"], 0) > 0
        assert rows["reloc_positive"] == "true"

    def test_idempotent_repeat_runs(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r1 = run_cli("overlay_scan.py", "--binary", str(pe))
        r2 = run_cli("overlay_scan.py", "--binary", str(pe))
        assert r1.stdout == r2.stdout


# =====================================================================
# disasm-dump
# =====================================================================

class TestDisasmDump:
    def test_help_exit_zero(self):
        r = run_cli("disasm_dump.py", "--help")
        assert r.returncode == 0
        assert "--rvas" in r.stdout

    def test_rvas_disassemble_exit_zero(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("disasm_dump.py", "--binary", str(pe), "--rvas", "0x1010")
        assert r.returncode == 0, r.stderr
        data = _parse_json(r.stdout)
        site = data["sites"][0]
        assert site["va"] == "0x140001010"
        assert site["offset"] == "0x210"
        insns = site["instructions"]
        assert insns[0]["mnemonic"] in ("mov", "movabs")
        assert "0x1ffffffff" in insns[0]["op_str"]
        assert insns[0]["bytes"].startswith("48 b8")

    def test_unmapped_rva_exit_1(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("disasm_dump.py", "--binary", str(pe), "--rvas", "0x9000")
        assert r.returncode == 1
        assert "not mapped" in _parse_json(r.stdout)["sites"][0]["error"]

    def test_multiple_rvas(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("disasm_dump.py", "--binary", str(pe), "--rvas", "0x1010,0x101a")
        assert r.returncode == 0
        assert len(_parse_json(r.stdout)["sites"]) == 2

    def test_prologs_and_strings(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("disasm_dump.py", "--binary", str(pe), "--prologs", "--strings")
        assert r.returncode == 0, r.stderr
        data = _parse_json(r.stdout)
        assert len(data["prologs"]) >= 2
        assert any(s["text"].lower() == "helloshellcode" for s in data["strings"]["items"])

    def test_missing_file_exit_2(self, tmp_path):
        r = run_cli("disasm_dump.py", "--binary", str(tmp_path / "nope.exe"), "--rvas", "0x1000")
        assert r.returncode == 2
        assert "cannot read" in r.stderr

    def test_no_operation_exit_2(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("disasm_dump.py", "--binary", str(pe))
        assert r.returncode == 2
        assert "no operation" in r.stderr

    def test_reproduce_l1_parseable(self, tmp_path):
        pe = _build_sample_pe(tmp_path / "sample.exe")
        r = run_cli("disasm_dump.py", "--binary", str(pe), "--rvas", "0x1010", "--reproduce")
        assert r.returncode == 0
        rows = _parse_reproduce(r.stdout)
        assert rows["tool"] == "disasm-dump"
        assert rows["sites"] == "1"
        assert rows["site_0_va"] == "0x140001010"
        assert rows["site_0_first_bytes"].startswith("48 b8")


# =====================================================================
# shellcode-scan
# =====================================================================

class TestShellcodeScan:
    def test_help_exit_zero(self):
        r = run_cli("shellcode_scan.py", "--help")
        assert r.returncode == 0
        assert "--peb" in r.stdout and "--scan" in r.stdout

    def test_full_scan_exit_zero(self, tmp_path):
        blob = _build_shellcode_blob(tmp_path / "blob.bin")
        r = run_cli("shellcode_scan.py", "--binary", str(blob),
                    "--entry", "0", "--scan", "--prologs", "--peb", "--strings")
        assert r.returncode == 0, r.stderr
        data = _parse_json(r.stdout)
        assert data["entry"]["count"] > 0
        assert data["entry"]["instructions"][0]["mnemonic"] in ("mov", "movabs")
        assert len(data["regions"]) >= 1
        assert len(data["prologs"]) >= 3
        assert len(data["peb_hits"]) >= 1
        assert any(s["text"].lower() == "helloshellcode" for s in data["strings"]["items"])

    def test_empty_blob_negative_exit_1(self, tmp_path):
        blob = tmp_path / "empty.bin"
        blob.write_bytes(b"")
        r = run_cli("shellcode_scan.py", "--binary", str(blob), "--scan", "--strings")
        assert r.returncode == 1
        data = _parse_json(r.stdout)
        assert data["regions"] == [] and data["strings"]["total"] == 0

    def test_entry_out_of_range_exit_2(self, tmp_path):
        blob = _build_shellcode_blob(tmp_path / "blob.bin")
        r = run_cli("shellcode_scan.py", "--binary", str(blob), "--entry", "0xffffff")
        assert r.returncode == 2
        assert "outside the file" in r.stderr

    def test_missing_file_exit_2(self, tmp_path):
        r = run_cli("shellcode_scan.py", "--binary", str(tmp_path / "nope.bin"), "--scan")
        assert r.returncode == 2

    def test_no_operation_exit_2(self, tmp_path):
        blob = _build_shellcode_blob(tmp_path / "blob.bin")
        r = run_cli("shellcode_scan.py", "--binary", str(blob))
        assert r.returncode == 2
        assert "no operation" in r.stderr

    def test_reproduce_l1_parseable(self, tmp_path):
        blob = _build_shellcode_blob(tmp_path / "blob.bin")
        r = run_cli("shellcode_scan.py", "--binary", str(blob),
                    "--entry", "0", "--peb", "--reproduce")
        assert r.returncode == 0
        rows = _parse_reproduce(r.stdout)
        assert rows["tool"] == "shellcode-scan"
        assert int(rows["entry"]) > 0
        assert int(rows["peb"]) >= 1


# =====================================================================
# die-probe (in-process: monkeypatched subprocess)
# =====================================================================

import die_probe as dp  # noqa: E402


def _fake_die_run(ok: bool = True):
    def _run(cmd, capture_output=True, text=True, timeout=120):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        r = R()
        if not ok:
            r.returncode = 1
            r.stderr = "boom"
            return r
        if "-e" in cmd:
            r.stdout = json.dumps({
                "records": [
                    {"name": 'Section[".text"]', "offset": "00000200", "size": "00000200",
                     "entropy": 6.2, "status": "not packed"},
                    {"name": "Overlay", "entropy": 7.8, "status": "packed"},
                ],
                "status": "packed", "total": 7.1,
            })
        elif "-S" in cmd:
            if "Hash" in cmd:
                r.stdout = json.dumps({"data": {"Hash": {"MD5": "aa"}}})
            else:
                r.stdout = json.dumps({"data": {"Resource": {
                    "VERSION_INFO": {"CompanyName": "ACME"}, "MANIFEST": "<xml/>"}}})
        elif "-b" in cmd:
            r.stdout = json.dumps({"detects": [{"name": "x64", "type": "language", "values": [
                {"type": "language", "name": "C/C++", "version": "6.0"}]}]})
        else:
            r.stdout = json.dumps({"detects": [{"name": "PE64", "type": "PE", "values": [
                {"type": "compiler", "name": "MinGW", "version": "8.1"}]}]})
        return r

    return _run


class TestDieProbe:
    def test_help_exit_zero(self):
        r = run_cli("die_probe.py", "--help")
        assert r.returncode == 0
        assert "--die" in r.stdout

    def test_merge_exit_zero(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "sample.exe"
        _build_sample_pe(target)
        fake_die = tmp_path / "fake-diec.exe"
        fake_die.write_bytes(b"")
        monkeypatch.setattr(dp.subprocess, "run", _fake_die_run())
        code = dp.main(["--binary", str(target), "--die", str(fake_die)])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["_meta"]["source"] == "die"
        assert len(payload["_meta"]["flag_calls"]) == 5
        assert payload["derived"]["language"] == "C/C++"
        assert payload["derived"]["compiler_version"] == "8.1"
        assert payload["derived"]["high_entropy_sections"] == ["Overlay"]
        assert payload["version_info"]["CompanyName"] == "ACME"
        assert "queried_at" not in payload["_meta"]  # determinism contract

    def test_all_calls_fail_exit_1(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "sample.exe"
        _build_sample_pe(target)
        fake_die = tmp_path / "fake-diec.exe"
        fake_die.write_bytes(b"")
        monkeypatch.setattr(dp.subprocess, "run", _fake_die_run(ok=False))
        code = dp.main(["--binary", str(target), "--die", str(fake_die)])
        assert code == 1
        assert "all 5 DIE calls failed" in capsys.readouterr().err

    def test_die_missing_exit_2_with_guidance(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "sample.exe"
        _build_sample_pe(target)
        monkeypatch.setattr(dp, "resolve_die", lambda die_arg, env=None: None)
        with pytest.raises(SystemExit) as exc:
            dp.main(["--binary", str(target)])
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "Install Detect-It-Easy" in err and "--die" in err

    def test_die_path_missing_exit_2(self, tmp_path, capsys):
        target = tmp_path / "sample.exe"
        _build_sample_pe(target)
        with pytest.raises(SystemExit) as exc:
            dp.main(["--binary", str(target), "--die", str(tmp_path / "no-diec.exe")])
        assert exc.value.code == 2
        assert "does not exist" in capsys.readouterr().err

    def test_target_missing_exit_2(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            dp.main(["--binary", str(tmp_path / "nope.exe")])
        assert exc.value.code == 2
        assert "target missing" in capsys.readouterr().err

    def test_reproduce_l1_parseable(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "sample.exe"
        _build_sample_pe(target)
        fake_die = tmp_path / "fake-diec.exe"
        fake_die.write_bytes(b"")
        monkeypatch.setattr(dp.subprocess, "run", _fake_die_run())
        code = dp.main(["--binary", str(target), "--die", str(fake_die), "--reproduce"])
        assert code == 0
        rows = _parse_reproduce(capsys.readouterr().out)
        assert rows["tool"] == "die-probe"
        assert rows["die"] == str(fake_die)
        assert rows["language"] == "C/C++"
        assert rows["calls_ok"] == "5"

    def test_resolve_die_order(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KUNGLAO_DIE", raising=False)
        monkeypatch.setattr(dp.shutil, "which", lambda name: None)
        assert dp.resolve_die("X") == Path("X")
        assert dp.resolve_die(None, {"KUNGLAO_DIE": "Y"}) == Path("Y")
        assert dp.resolve_die(None) is None


# =====================================================================
# Registration: shipped _INDEX.yaml validates and lists the 5 tools
# =====================================================================

def test_shipped_index_registers_1c_tools():
    import yaml

    import validate_index as vi

    data = yaml.safe_load((TOOLS / "_INDEX.yaml").read_text(encoding="utf-8"))
    names = {t["name"] for t in data["tools"]}
    expected = {"pe-analyze", "overlay-scan", "disasm-dump", "shellcode-scan", "die-probe"}
    assert expected <= names, f"missing registrations: {expected - names}"
    assert vi.validate_index(data) == []


def test_utf8_stdout_no_traceback(tmp_path):
    """r2-278-1c H1 regression: non-UTF8 binary input must never crash with a
    bare UnicodeEncodeError traceback — stdout is unified on UTF-8."""
    blob = bytes(range(256)) * 40  # every byte value incl. invalid UTF-8
    p = tmp_path / "blob.bin"
    p.write_bytes(blob)
    for tool in ("pe_analyze.py", "overlay_scan.py", "disasm_dump.py", "shellcode_scan.py"):
        r = run_cli(tool, "--binary", str(p), "--json")
        assert "Traceback" not in r.stderr, f"{tool}: bare traceback"
        assert r.returncode in (0, 1, 2), f"{tool}: rc={r.returncode}"


def test_overlay_scan_truncated_overlay_no_crash(tmp_path):
    """r1/r2-278-1c H2 regression: a 3-byte overlay (first_dwords guard) and a
    16-byte reloc-shaped overlay (first_entries guard) must not raise
    struct.error — structured exit only."""
    pe = _build_sample_pe(tmp_path / "sample.exe")
    data = pe.read_bytes()
    ov_off = data.find(b"OVERLAY")
    assert ov_off > 0
    truncated = data[: ov_off + 3]  # 3-byte overlay
    p3 = tmp_path / "t3.bin"
    p3.write_bytes(truncated)
    for mode in ("true", "all"):
        r = run_cli("overlay_scan.py", "--binary", str(p3), "--mode", mode, "--json")
        assert "Traceback" not in r.stderr, f"mode={mode}: traceback"
        assert r.returncode in (0, 1, 2)

    # 16-byte reloc-shaped overlay: page_rva=0x1000, fake first_size=100,
    # then only 8 more bytes — first_entries must be length-guarded.
    reloc16 = struct.pack("<II", 0x1000, 100) + b"\x00" * 8
    p16 = tmp_path / "t16.bin"
    p16.write_bytes(pe.read_bytes() + reloc16)
    r = run_cli("overlay_scan.py", "--binary", str(p16), "--mode", "reloc", "--json")
    assert "Traceback" not in r.stderr
    assert r.returncode in (0, 1, 2)


def test_shellcode_scan_step_zero_exit_2(tmp_path):
    """r2-278-1c MEDIUM regression: --step 0 must be exit 2 with guidance,
    not a ValueError traceback."""
    p = tmp_path / "blob.bin"
    p.write_bytes(b"\x90" * 256)
    r = run_cli("shellcode_scan.py", "--binary", str(p), "--scan", "--step", "0")
    assert "Traceback" not in r.stderr
    assert r.returncode == 2
    assert "--step" in r.stderr


def test_die_probe_utf8_guard(tmp_path):
    """r2-278-1c H1 (die_probe gap) regression: die_probe does NOT import
    _common, so its own UTF-8 stdout guard must hold — non-ASCII filenames
    must never produce a bare traceback."""
    p = tmp_path / "样本.exe"  # non-ASCII filename
    p.write_bytes(b"\x90" * 64)
    r = run_cli("die_probe.py", "--binary", str(p))
    assert "Traceback" not in r.stderr
    assert r.returncode in (0, 1, 2)


def test_pe_analyze_signature_small_dirs(tmp_path):
    """r2-278-1c MEDIUM regression: PE with NumberOfRvaAndSizes < 5 must not
    raise IndexError in the signature subcommand."""
    import pefile
    src = _build_sample_pe(tmp_path / "sample.exe")
    pe = pefile.PE(str(src))
    pe.OPTIONAL_HEADER.NumberOfRvaAndSizes = 4
    patched = tmp_path / "small.exe"
    patched.write_bytes(pe.write())
    r = run_cli("pe_analyze.py", "--binary", str(patched), "signature", "--json")
    assert "Traceback" not in r.stderr
    assert r.returncode in (0, 1, 2)
