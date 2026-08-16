# -*- coding: utf-8 -*-
"""tests/test_yara_tools.py — issue #313: yara-scan / yara-gen contract.

Covers: hits/no-hits exit codes, real CRC32-table hit from the bundled
rules, yara-gen round-trip self-consistency (generated rule + yara-scan on
a blob containing the pattern MUST hit), error paths.
"""
from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

# yara-python is the optional scan engine — the CLIs degrade gracefully
# (exit 2 + guidance) without it, so the whole module skips here (same
# guarded-import policy as z3-solver in tests/test_opaque_pred.py).
pytest.importorskip("yara", reason="yara-python not installed")

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "tools" / "static"
L1_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")


def run_cli(tool: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(STATIC / tool), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )


def parse_reproduce(stdout):
    return dict(m.groups() for line in stdout.splitlines()
                if (m := L1_LINE_RE.match(line)))


def crc32_table_bytes() -> bytes:
    """Standard reflected CRC32 table (poly 0xEDB88320)."""
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ (0xEDB88320 if c & 1 else 0)
        table.append(c)
    return b"".join(struct.pack("<I", v) for v in table)


def test_help_exit_zero():
    for tool in ("yara-scan.py", "yara-gen.py"):
        r = run_cli(tool, "--help")
        assert r.returncode == 0, r.stderr


def test_scan_missing_binary_exit_2():
    r = run_cli("yara-scan.py", "--binary", "does-not-exist.bin")
    assert r.returncode == 2
    assert json.loads(r.stderr)["error"]


def test_scan_bad_rule_path_exit_2(tmp_path):
    blob = tmp_path / "nope.bin"
    blob.write_bytes(b"\x00" * 16)
    r = run_cli("yara-scan.py", "--binary", str(blob), "--rules",
                "C:/definitely/not/here.yar")
    assert r.returncode == 2
    assert "rule path not found" in r.stderr


def test_scan_crc32_table_hit(tmp_path):
    table = crc32_table_bytes()
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"\x00" * 64 + table + b"\xff" * 64)
    r = run_cli("yara-scan.py", "--binary", str(blob), "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["hit_count"] >= 1
    crc_hits = [h for h in data["hits"] if "crc32" in h["rule"].lower()]
    assert crc_hits, {h["rule"] for h in data["hits"]}
    # byte-anchored: hits must land inside the table region [64, 64+1024)
    assert all(64 <= h["offset"] < 64 + len(table) for h in crc_hits)


def test_scan_no_hits_exit_1(tmp_path):
    blob = tmp_path / "zeros.bin"
    blob.write_bytes(b"\x00" * 512)
    r = run_cli("yara-scan.py", "--binary", str(blob), "--json")
    assert r.returncode == 1
    assert json.loads(r.stdout)["hit_count"] == 0


def test_scan_reproduce_fields(tmp_path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(crc32_table_bytes())
    r = run_cli("yara-scan.py", "--binary", str(blob), "--reproduce")
    assert r.returncode == 0, r.stderr
    fields = parse_reproduce(r.stdout)
    assert fields["tool"] == "yara-scan"
    assert int(fields["hit_count"]) >= 1
    assert len(fields["binary_sha256"]) == 64


def test_gen_hex_roundtrip(tmp_path):
    pattern = "deadbeefcafebabe"
    r = run_cli("yara-gen.py", "--hex", pattern, "--name", "test_marker",
                "--meta", "sha256=ab" * 16, "--meta", "source=C-011")
    assert r.returncode == 0, r.stderr
    assert "rule test_marker" in r.stdout
    rule_file = tmp_path / "test_marker.yar"
    rule_file.write_text(r.stdout, encoding="utf-8")
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"\x11" * 32 + bytes.fromhex(pattern) + b"\x22" * 32)
    scan = run_cli("yara-scan.py", "--binary", str(blob),
                   "--rules", str(rule_file), "--json")
    assert scan.returncode == 0, scan.stderr
    data = json.loads(scan.stdout)
    assert data["hit_count"] == 1
    assert data["hits"][0]["offset"] == 32
    assert data["hits"][0]["rule"] == "test_marker"


def test_gen_string_wide_roundtrip(tmp_path):
    marker = "kunglao_marker_2026"
    r = run_cli("yara-gen.py", "--string", marker, "--name", "str_marker",
                "--wide")
    assert r.returncode == 0, r.stderr
    rule_file = tmp_path / "str_marker.yar"
    rule_file.write_text(r.stdout, encoding="utf-8")
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"\x00" * 16 + marker.encode("utf-16-le") + b"\x00" * 16)
    scan = run_cli("yara-scan.py", "--binary", str(blob),
                   "--rules", str(rule_file), "--json")
    assert scan.returncode == 0, scan.stderr
    assert json.loads(scan.stdout)["hit_count"] >= 1


def test_gen_bad_name_exit_2():
    r = run_cli("yara-gen.py", "--string", "x", "--name", "1bad-name")
    assert r.returncode == 2
    assert "identifier" in json.loads(r.stderr)["error"]


def test_gen_bad_hex_exit_2():
    r = run_cli("yara-gen.py", "--hex", "zz!!", "--name", "ok_name")
    assert r.returncode == 2
    assert "non-hex" in json.loads(r.stderr)["error"]


def test_gen_bad_meta_exit_2():
    r = run_cli("yara-gen.py", "--string", "x", "--name", "ok_name",
                "--meta", "no-equals-sign")
    assert r.returncode == 2
    assert "K=V" in json.loads(r.stderr)["error"]


def test_gen_non_ascii_string_utf8_bytes(tmp_path):
    """r1-313-yara H1 regression: non-ASCII chars must be escaped as their
    full UTF-8 byte sequence (中文 → \xe4\xb8\xad), not truncated bytes —
    the generated rule must still hit."""
    marker = "中文标记"
    r = run_cli("yara-gen.py", "--string", marker, "--name", "utf8_marker")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("\\x") >= 9  # 3 chars x 3 UTF-8 bytes
    rule_file = tmp_path / "utf8_marker.yar"
    rule_file.write_text(r.stdout, encoding="utf-8")
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"\x00" * 8 + marker.encode("utf-8") + b"\x00" * 8)
    scan = run_cli("yara-scan.py", "--binary", str(blob),
                   "--rules", str(rule_file), "--json")
    assert scan.returncode == 0, scan.stderr
    assert json.loads(scan.stdout)["hit_count"] == 1


def test_gen_meta_key_identifier_only_exit_2():
    """r1-313-yara H2: meta keys with dots/hyphens are not valid YARA
    identifiers — must exit 2, not emit an uncompilable rule."""
    r = run_cli("yara-gen.py", "--string", "x", "--name", "ok_name",
                "--meta", "bad.key=1")
    assert r.returncode == 2
    assert "identifier" in json.loads(r.stderr)["error"]


def test_gen_meta_quote_escaped_and_compiles(tmp_path):
    """r1-313-yara H2: a quote in a meta value must be escaped so the rule
    compiles."""
    r = run_cli("yara-gen.py", "--string", "x", "--name", "ok_name",
                "--meta", 'note=a"b')
    assert r.returncode == 0, r.stderr
    rule_file = tmp_path / "ok_name.yar"
    rule_file.write_text(r.stdout, encoding="utf-8")
    blob = tmp_path / "b.bin"
    blob.write_bytes(b"\x00" * 16)
    scan = run_cli("yara-scan.py", "--binary", str(blob),
                   "--rules", str(rule_file))
    # rule compiles (scan reaches the no-hit path, exit 1, not a compile error)
    assert scan.returncode in (0, 1)
    assert "rule compilation failed" not in scan.stderr
