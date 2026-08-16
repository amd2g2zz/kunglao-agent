# -*- coding: utf-8 -*-
"""tests/test_crypto_tool.py — issue #285 crypto-tool CLI contract.

Covers: per-subcommand --help, --reproduce field=value output (kunglao L1
mechanical-gate format), exit codes (0 success / 1 negative / 2 error),
structured error JSON on stderr, and idempotent repeated runs.
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
TOOL = ROOT / "tools" / "crypto" / "crypto-tool.py"

# Matches scripts/kunglao_verify.py _ACTUAL_ASSERTION_RE (L1 field=value parser).
L1_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")

RFC8439_A1_FIRST_BLOCK = (
    "76b8e0ada0f13d90405d6ae55386bd28"
    "bdd219b8a08ded1aa836efcc8b770dc7"
    "da41597c5157488d7724e03fb8d84a37"
    "6a43b8f41518a11cc387b669b2ee6586"
)


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        # tools emit UTF-8 (#317 unified stdout); decode as UTF-8, not the
        # GBK locale default, or multi-byte chars crash the reader thread
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )


def _parse_reproduce(stdout):
    return dict(L1_LINE_RE.match(line).groups() for line in stdout.splitlines()
                if L1_LINE_RE.match(line))


# ---------------------------------------------------------------------------
# Help / surface
# ---------------------------------------------------------------------------

def test_help_exit_zero():
    r = run_cli("--help")
    assert r.returncode == 0
    for sub in ("chacha", "xor-add", "rolling-xor", "lzss", "lzma-raw",
                "rsa-unpad", "go-byte-transform", "va-to-off"):
        rr = run_cli(sub, "--help")
        assert rr.returncode == 0, f"{sub} --help exit {rr.returncode}: {rr.stderr[:200]}"


def test_self_check_exit_zero():
    r = run_cli("--self-check", "--reproduce")
    assert r.returncode == 0, r.stderr
    rows = _parse_reproduce(r.stdout)
    assert rows["status"] == "PASS"


# ---------------------------------------------------------------------------
# --reproduce format (kunglao L1 mechanical gate)
# ---------------------------------------------------------------------------

def test_reproduce_lines_are_l1_parseable():
    r = run_cli("chacha", "--in-hex", "00",
                "--key", "00" * 32, "--nonce", "00" * 12,
                "--counter", "0", "--reproduce")
    assert r.returncode == 0
    lines = r.stdout.strip().splitlines()
    assert lines, "no reproduce output"
    for line in lines:
        assert L1_LINE_RE.match(line), f"line not L1-parseable: {line!r}"
    rows = _parse_reproduce(r.stdout)
    assert rows["algorithm"] == "chacha"
    assert len(rows["output_sha256"]) == 64
    assert "input_sha256" in rows


def test_chacha_rfc8439_a1_vector_through_cli():
    r = run_cli("chacha", "--in-hex", "00" * 64,
                "--key", "00" * 32, "--nonce", "00" * 12,
                "--counter", "0", "--reproduce")
    assert r.returncode == 0
    rows = _parse_reproduce(r.stdout)
    assert rows["output_hex"] == RFC8439_A1_FIRST_BLOCK


def test_xor_add_roundtrip_through_cli():
    plain = "000102030405"
    r1 = run_cli("xor-add", "--in-hex", plain, "--mode", "encrypt", "--reproduce")
    assert r1.returncode == 0
    enc_hex = _parse_reproduce(r1.stdout)["output_hex"]
    r2 = run_cli("xor-add", "--in-hex", enc_hex, "--mode", "decrypt", "--reproduce")
    assert r2.returncode == 0
    assert _parse_reproduce(r2.stdout)["output_hex"] == plain


def test_reproduce_is_idempotent():
    args = ("rolling-xor", "--in-hex", "00010203", "--seed", "0x963239fd", "--reproduce")
    r1 = run_cli(*args)
    r2 = run_cli(*args)
    assert r1.returncode == 0 and r2.returncode == 0
    assert r1.stdout == r2.stdout


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def test_json_report():
    r = run_cli("xor-add", "--in-hex", "00010203", "--mode", "decrypt", "--json")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["algorithm"] == "xor-add"
    assert len(data["output_sha256"]) == 64


def test_out_writes_file(tmp_path):
    out_path = tmp_path / "out.bin"
    r = run_cli("xor-add", "--in-hex", "41424344", "--mode", "decrypt", "--out", str(out_path))
    assert r.returncode == 0
    # The written bytes must equal the transform result (cross-check via --reproduce).
    r2 = run_cli("xor-add", "--in-hex", "41424344", "--mode", "decrypt", "--reproduce")
    expected = bytes.fromhex(_parse_reproduce(r2.stdout)["output_hex"])
    assert out_path.read_bytes() == expected
    assert expected != bytes.fromhex("41424344")  # decrypt is a real transform


# ---------------------------------------------------------------------------
# Exit codes: 0 success / 1 negative / 2 error
# ---------------------------------------------------------------------------

def test_invalid_subcommand_exit_2():
    r = run_cli("bogus")
    assert r.returncode == 2


def test_invalid_enum_choice_exit_2():
    r = run_cli("chacha", "--in-hex", "00", "--key", "00" * 32, "--nonce", "00" * 12,
                "--variant", "bogus")
    assert r.returncode == 2


def test_missing_input_exit_2_with_error_json():
    r = run_cli("xor-add", "--in", str(ROOT / "no-such-file.bin"))
    assert r.returncode == 2
    data = json.loads(r.stderr)
    assert data["exit_code"] == 2
    assert "error" in data


def test_chacha_bad_key_length_exit_2():
    r = run_cli("chacha", "--in-hex", "00", "--key", "0011", "--nonce", "00" * 12)
    assert r.returncode == 2
    data = json.loads(r.stderr)
    assert data["exit_code"] == 2


def test_rsa_unpad_negative_exit_1():
    # Tiny modulus, 2-byte ciphertext -> block < 11B -> padding check fails.
    r = run_cli("rsa-unpad", "--mode", "PKCS1v15", "--n", "0x28a3", "--e", "65537",
                "--in-hex", "0102", "--reproduce")
    assert r.returncode == 1
    rows = _parse_reproduce(r.stdout)
    assert rows["status"] == "NEGATIVE"
    assert rows["fail_at_block"] == "0"


def test_lzma_raw_negative_exit_1():
    r = run_cli("lzma-raw", "--in-hex", "01020304", "--reproduce")
    assert r.returncode == 1
    rows = _parse_reproduce(r.stdout)
    assert rows["status"] == "NEGATIVE"


def test_lzss_py_known_vector_through_cli():
    comp = "4182424142" + "00" * 8
    r = run_cli("lzss", "--in-hex", comp, "--size", "4", "--variant", "py", "--reproduce")
    assert r.returncode == 0
    assert _parse_reproduce(r.stdout)["output_hex"] == "41424142"


def test_lzss_dll_known_vector_through_cli():
    r = run_cli("lzss", "--in-hex", "4121", "--size", "2", "--variant", "dll", "--reproduce")
    assert r.returncode == 0
    assert _parse_reproduce(r.stdout)["output_hex"] == "4142"


# ---------------------------------------------------------------------------
# va-to-off
# ---------------------------------------------------------------------------

def _build_mini_pe():
    e_lfanew = 0x80
    pe = 0x80
    opt = pe + 24
    size_opt = 0xF0
    sec = opt + size_opt
    buf = bytearray(sec + 40)
    struct.pack_into("<I", buf, 0x3C, e_lfanew)
    buf[pe:pe + 4] = b"PE\x00\x00"
    struct.pack_into("<H", buf, pe + 4, 0x8664)
    struct.pack_into("<H", buf, pe + 6, 1)
    struct.pack_into("<H", buf, pe + 20, size_opt)
    struct.pack_into("<H", buf, opt, 0x20B)
    struct.pack_into("<Q", buf, opt + 24, 0x400000)
    struct.pack_into("<I", buf, sec + 8, 0x200)
    struct.pack_into("<I", buf, sec + 12, 0x1000)
    struct.pack_into("<I", buf, sec + 16, 0x200)
    struct.pack_into("<I", buf, sec + 20, 0x400)
    return bytes(buf)


def test_va_to_off_through_cli(tmp_path):
    pe = tmp_path / "mini-pe.bin"
    pe.write_bytes(_build_mini_pe())
    r = run_cli("va-to-off", "--in", str(pe), "--va", "0x401050", "--reproduce")
    assert r.returncode == 0
    rows = _parse_reproduce(r.stdout)
    assert rows["file_offset"] == "0x450"


def test_va_to_off_negative_exit_1(tmp_path):
    pe = tmp_path / "mini-pe.bin"
    pe.write_bytes(_build_mini_pe())
    r = run_cli("va-to-off", "--in", str(pe), "--va", "0x500000", "--reproduce")
    assert r.returncode == 1
    rows = _parse_reproduce(r.stdout)
    assert rows["status"] == "NEGATIVE"
