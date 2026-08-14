# -*- coding: utf-8 -*-
"""tests/test_feature_probe.py — issue #278 P4-a: scripts/feature_probe.py contract.

Deterministic sample-feature probe (stdlib-only, pure bytes parsing — no pefile):
  MZ/PE magic + machine, section table from the PE header, import-table name
  strings via simple ASCII-run scan, overlay detection (last section raw end <
  file size), Shannon entropy over a 256-bin histogram (0..8), string density
  (printable-ASCII run bytes >= 4 chars / sampled bytes).

Exit codes: 0 = ok, 2 = usage error, 3 = file missing or not a PE.

All fixtures are SYNTHETIC minimal PEs built byte-by-byte in a helper, so the
contract is tested against a known layout without any binary fixtures on disk.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "feature_probe.py"

# Layout constants for the synthetic PE (mirrors what feature_probe parses).
DOS_HEADER_SIZE = 0x80
PE_SIG_SIZE = 4
COFF_SIZE = 20
OPT_SIZE = 0xF0  # SizeOfOptionalHeader field — probe skips it, never parses
SECTION_HDR_SIZE = 40
TEXT_RAW = 0x200
RDATA_RAW = 0x100
RDATA_OFF = 0x400


def build_minimal_pe(machine: int = 0x8664, overlay_len: int = 0,
                     pattern: bool = True) -> bytes:
    """Build a minimal deterministic PE: MZ header + PE sig + COFF (2 sections)
    + optional-header placeholder + section table + .text/.rdata raw bytes.

    Planted import-table strings live at the start of .rdata:
    kernel32.dll / VirtualAlloc / CreateFileW.

    pattern=False zero-fills the raw section bytes (near-zero entropy fixture).
    """
    data = bytearray()
    # DOS header: MZ magic + e_lfanew -> PE header at 0x80
    dos = bytearray(DOS_HEADER_SIZE)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)
    data += dos
    # PE signature + COFF header: machine, 2 sections, SizeOfOptionalHeader=0xF0
    data += b"PE\x00\x00"
    data += struct.pack("<HHIIIHH", machine, 2, 0, 0, 0, OPT_SIZE, 0x2102)
    # optional-header placeholder (probe skips via SizeOfOptionalHeader)
    data += bytes(OPT_SIZE)
    # section table: name(8) vsize vaddr raw_size raw_ptr relocs linenums
    #                nreloc(H) nline(H) characteristics(I)
    data += b".text\x00\x00\x00" + struct.pack(
        "<IIIIIIHHI", 0x200, 0x1000, TEXT_RAW, 0x200, 0, 0, 0, 0, 0x60000020)
    data += b".rdata\x00\x00" + struct.pack(
        "<IIIIIIHHI", RDATA_RAW, 0x3000, RDATA_RAW, RDATA_OFF,
        0, 0, 0, 0, 0x40000040)
    # pad headers up to the first raw section offset
    data += bytes(0x200 - len(data))
    # .text raw bytes: deterministic pseudo-random pattern (no os.urandom —
    # determinism is part of the contract)
    if pattern:
        data += bytes((i * 31 + 7) & 0xFF for i in range(TEXT_RAW))
    else:
        data += bytes(TEXT_RAW)
    # .rdata raw bytes: planted import strings + pattern fill
    data += b"kernel32.dll\x00VirtualAlloc\x00CreateFileW\x00"
    fill = RDATA_RAW - (len(data) - RDATA_OFF)
    data += bytes((i * 13 + 3) & 0xFF for i in range(fill)) if pattern \
        else bytes(fill)
    # optional overlay bytes beyond the last section's raw end
    data += bytes(b"\xAA" * overlay_len)
    return bytes(data)


def build_truncated_pe(coff_bytes: int = 0) -> bytes:
    """Valid MZ + e_lfanew=0x40 + PE signature, truncated inside the COFF
    header. coff_bytes = number of COFF bytes present (0, 2, or 16 — the 0/2
    layouts come from the TEST-gate verdict on PR #302; 16 cuts exactly the
    SizeOfOptionalHeader field)."""
    data = bytearray(0x40)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x40)
    data += b"PE\x00\x00"
    data += bytes(coff_bytes)
    return bytes(data)


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, timeout=60,
    )


def write_sample(tmp_path: Path, data: bytes, name: str = "sample.exe") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# ---------------------------------------------------------------------------
# header + section parsing
# ---------------------------------------------------------------------------

def test_machine_and_sections_parsed(tmp_path):
    p = write_sample(tmp_path, build_minimal_pe())
    r = run_cli(str(p), "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["machine"] == "AMD64"
    assert out["sections"] == [
        {"name": ".text", "vaddr": 0x1000, "raw_size": TEXT_RAW},
        {"name": ".rdata", "vaddr": 0x3000, "raw_size": RDATA_RAW},
    ]


def test_machine_i386_mapped(tmp_path):
    p = write_sample(tmp_path, build_minimal_pe(machine=0x14C))
    r = run_cli(str(p), "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["machine"] == "I386"


# ---------------------------------------------------------------------------
# overlay detection
# ---------------------------------------------------------------------------

def test_overlay_false_when_sections_cover_file(tmp_path):
    p = write_sample(tmp_path, build_minimal_pe(overlay_len=0))
    r = run_cli(str(p), "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["overlay"] is False


def test_overlay_true_when_trailing_bytes_exist(tmp_path):
    p = write_sample(tmp_path, build_minimal_pe(overlay_len=0x40))
    r = run_cli(str(p), "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["overlay"] is True


# ---------------------------------------------------------------------------
# entropy + string density + import hints
# ---------------------------------------------------------------------------

def test_entropy_in_range(tmp_path):
    p = write_sample(tmp_path, build_minimal_pe())
    r = run_cli(str(p), "--json")
    out = json.loads(r.stdout)
    assert isinstance(out["entropy"], float)
    assert 0.0 <= out["entropy"] <= 8.0


def test_entropy_near_zero_for_zero_payload(tmp_path):
    # valid PE, zero-filled raw sections → entropy driven only by header noise
    p = write_sample(tmp_path, build_minimal_pe(pattern=False), name="zeros.exe")
    r = run_cli(str(p), "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["entropy"] < 1.0


def test_string_density_and_import_hints(tmp_path):
    p = write_sample(tmp_path, build_minimal_pe())
    r = run_cli(str(p), "--json")
    out = json.loads(r.stdout)
    assert isinstance(out["string_density"], float)
    assert 0.0 < out["string_density"] <= 1.0
    assert "kernel32.dll" in out["import_hints"]
    assert "VirtualAlloc" in out["import_hints"]


# ---------------------------------------------------------------------------
# not-PE / missing file → exit 3 with a clear message (not a crash)
# ---------------------------------------------------------------------------

def test_non_pe_file_exit_three(tmp_path):
    p = write_sample(tmp_path, b"this is not a PE file at all", name="note.bin")
    r = run_cli(str(p), "--json")
    assert r.returncode == 3
    assert "not" in r.stderr.lower()


def test_mz_without_pe_signature_exit_three(tmp_path):
    p = write_sample(tmp_path, b"MZ" + bytes(0x100), name="fake.exe")
    r = run_cli(str(p))
    assert r.returncode == 3


def test_truncated_pe_sig_at_eof_exit_three(tmp_path):
    # PE sig exactly at EOF (len 68): the COFF machine/section-count read
    # would run past the buffer — must exit 3 with a clear message, no crash.
    p = write_sample(tmp_path, build_truncated_pe(coff_bytes=0),
                     name="trunc-a.exe")
    r = run_cli(str(p))
    assert r.returncode == 3
    assert "truncated" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_truncated_pe_partial_coff_exit_three(tmp_path):
    # PE sig + 2 COFF bytes (len 70): the SizeOfOptionalHeader read would run
    # past the buffer — must exit 3 with a clear message, no crash.
    p = write_sample(tmp_path, build_truncated_pe(coff_bytes=2),
                     name="trunc-b.exe")
    r = run_cli(str(p))
    assert r.returncode == 3
    assert "truncated" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_truncated_pe_missing_sizeof_opt_exit_three(tmp_path):
    # COFF machine/section-count present, SizeOfOptionalHeader field cut
    # (len 84): the second bounds check must also land on exit 3, no crash.
    p = write_sample(tmp_path, build_truncated_pe(coff_bytes=16),
                     name="trunc-c.exe")
    r = run_cli(str(p))
    assert r.returncode == 3
    assert "truncated" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_missing_file_exit_three(tmp_path):
    r = run_cli(str(tmp_path / "nope.exe"))
    assert r.returncode == 3
    assert "nope.exe" in r.stderr


# ---------------------------------------------------------------------------
# usage error + text mode + determinism
# ---------------------------------------------------------------------------

def test_usage_error_exit_two(tmp_path):
    p = write_sample(tmp_path, build_minimal_pe())
    assert run_cli().returncode == 2          # no args
    assert run_cli(str(p), "--bogus").returncode == 2


def test_text_mode_reports_fields(tmp_path):
    p = write_sample(tmp_path, build_minimal_pe())
    r = run_cli(str(p))
    assert r.returncode == 0, r.stderr
    for field in ("machine", "overlay", "entropy", "string_density"):
        assert field in r.stdout


def test_determinism_two_runs_identical(tmp_path):
    p = write_sample(tmp_path, build_minimal_pe(overlay_len=0x20))
    r1 = run_cli(str(p), "--json")
    r2 = run_cli(str(p), "--json")
    assert r1.returncode == r2.returncode == 0
    assert r1.stdout == r2.stdout
