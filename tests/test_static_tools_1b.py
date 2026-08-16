# -*- coding: utf-8 -*-
"""tests/test_static_tools_1b.py — issue #278 PR-1b tools/static 6-CLI contract.

Covers per tool: --help renders, parameterized input via tmp files, three-state
exit codes (0 ok / 1 negative / 2 error), --reproduce field=value lines
(kunglao L1 mechanical-gate format), --json single-object output, and the
empty-input edge case.  lzma-raw is intentionally NOT covered here — the
capability already exists as tools/crypto/crypto-tool.py's lzma-raw subcommand.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "tools" / "static"

TOOLS = {
    "extract-syscalls": STATIC / "extract-syscalls.py",
    "stack-strings": STATIC / "stack-strings.py",
    "binary-sweep": STATIC / "binary-sweep.py",
    "strings-classify": STATIC / "strings-classify.py",
    "go-buildinfo-carve": STATIC / "go-buildinfo-carve.py",
    "call-site-args": STATIC / "call-site-args.py",
}

# Matches scripts/kunglao_verify.py _ACTUAL_ASSERTION_RE (L1 field=value parser).
L1_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")


def run_cli(tool, *args):
    return subprocess.run(
        [sys.executable, str(TOOLS[tool]), *args],
        # tools emit UTF-8 (#317 unified stdout); decode as UTF-8, not the
        # GBK locale default, or multi-byte chars crash the reader thread
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )


def parse_reproduce(stdout):
    return dict(L1_LINE_RE.match(line).groups() for line in stdout.splitlines()
                if L1_LINE_RE.match(line))


def write_tmp(tmp_path, name, content):
    p = tmp_path / name
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_bytes(content)
    return p


# ---------------------------------------------------------------------------
# Shared surface: --help, missing input (exit 2), empty input (exit 1)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_help_exit_zero(tool):
    r = run_cli(tool, "--help")
    assert r.returncode == 0, f"{tool}: exit {r.returncode}, stderr={r.stderr[:200]}"
    assert "usage" in r.stdout.lower()


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_missing_input_exit_2(tool):
    r = run_cli(tool)
    assert r.returncode == 2, f"{tool}: exit {r.returncode}, stdout={r.stdout[:200]}"
    err = json.loads(r.stderr)
    assert err["exit_code"] == 2
    assert "--in" in err["error"]


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_unreadable_input_exit_2(tool):
    r = run_cli(tool, "--in", "no-such-file.bin")
    assert r.returncode == 2, f"{tool}: exit {r.returncode}, stdout={r.stdout[:200]}"
    err = json.loads(r.stderr)
    assert err["exit_code"] == 2
    assert "check the path" in err["error"]


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_empty_input_exit_1_reproduce(tmp_path, tool):
    p = write_tmp(tmp_path, "empty.bin", b"")
    r = run_cli(tool, "--in", str(p), "--reproduce")
    assert r.returncode == 1, f"{tool}: exit {r.returncode}, stdout={r.stdout[:200]}"
    fields = parse_reproduce(r.stdout)
    assert fields["tool"] == tool
    assert fields["status"] == "NEGATIVE"


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_empty_input_exit_1_json(tmp_path, tool):
    p = write_tmp(tmp_path, "empty.bin", b"")
    r = run_cli(tool, "--in", str(p), "--json")
    assert r.returncode == 1, f"{tool}: exit {r.returncode}, stdout={r.stdout[:200]}"
    data = json.loads(r.stdout)
    assert data["tool"] == tool
    assert data["status"] == "NEGATIVE"


# ---------------------------------------------------------------------------
# extract-syscalls
# ---------------------------------------------------------------------------

SYSCALL_STUBS = (
    b"\xb8\x2c\x00\x00\x00\x0f\x05"              # mov eax, 0x2c; syscall
    b"\x4c\x8b\xd1\xb8\x0b\x00\x00\x00\x0f\x05"  # mov r10, rcx; mov eax, 0x0b; syscall
)


def test_extract_syscalls_bin(tmp_path):
    p = write_tmp(tmp_path, "stubs.bin", SYSCALL_STUBS)
    r = run_cli("extract-syscalls", "--in", str(p))
    assert r.returncode == 0, r.stderr
    assert "number=0x2c" in r.stdout and "name=NtCreateFile" in r.stdout
    assert "number=0xb" in r.stdout and "name=NtAllocateVirtualMemory" in r.stdout


def test_extract_syscalls_text(tmp_path):
    p = write_tmp(tmp_path, "disasm.txt",
                  "0x401000  mov eax, 0x2c\n0x401005  syscall\n")
    r = run_cli("extract-syscalls", "--in", str(p), "--mode", "text")
    assert r.returncode == 0, r.stderr
    assert "location=0x401000" in r.stdout
    assert "number=0x2c" in r.stdout and "name=NtCreateFile" in r.stdout


def test_extract_syscalls_reproduce(tmp_path):
    p = write_tmp(tmp_path, "stubs.bin", SYSCALL_STUBS)
    r = run_cli("extract-syscalls", "--in", str(p), "--reproduce")
    assert r.returncode == 0, r.stderr
    fields = parse_reproduce(r.stdout)
    assert fields["tool"] == "extract-syscalls"
    assert fields["total"] == "2"
    assert fields["unique"] == "2"
    assert fields["first"] == "0x0"
    assert re.fullmatch(r"[0-9a-f]{64}", fields["input_sha256"])


def test_extract_syscalls_json(tmp_path):
    p = write_tmp(tmp_path, "stubs.bin", SYSCALL_STUBS)
    r = run_cli("extract-syscalls", "--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["total"] == 2
    assert data["stubs"][0]["number"] == 0x2C
    assert data["stubs"][0]["name"] == "NtCreateFile"


# ---------------------------------------------------------------------------
# stack-strings
# ---------------------------------------------------------------------------

def test_stack_strings_byte_writes(tmp_path):
    data = (b"\xc6\x44\x24\x08\x4d"    # mov byte ptr [rsp+0x8], 'M'
            b"\xc6\x44\x24\x08\x5a"    # mov byte ptr [rsp+0x8], 'Z'
            b"\xc6\x44\x24\x08\x21")   # mov byte ptr [rsp+0x8], '!'
    p = write_tmp(tmp_path, "stack.bin", data)
    r = run_cli("stack-strings", "--in", str(p))
    assert r.returncode == 0, r.stderr
    assert "slot=0x8" in r.stdout
    assert "'MZ!'" in r.stdout
    assert "writes=3" in r.stdout


def test_stack_strings_dword(tmp_path):
    data = b"\xc7\x44\x24\x10\x50\x45\x00\x00"  # mov dword ptr [rsp+0x10], 0x4550
    p = write_tmp(tmp_path, "stack2.bin", data)
    r = run_cli("stack-strings", "--in", str(p), "--dword")
    assert r.returncode == 0, r.stderr
    assert "'PE..'" in r.stdout


def test_stack_strings_dword_off_negative(tmp_path):
    data = b"\xc7\x44\x24\x10\x50\x45\x00\x00"
    p = write_tmp(tmp_path, "stack3.bin", data)
    r = run_cli("stack-strings", "--in", str(p))
    assert r.returncode == 1
    assert "NEGATIVE" in r.stdout


def test_stack_strings_region_and_reproduce(tmp_path):
    data = b"\x90" * 16 + b"\xc6\x44\x24\x08\x41\xc6\x44\x24\x08\x42"
    p = write_tmp(tmp_path, "stack4.bin", data)
    r = run_cli("stack-strings", "--in", str(p), "--start", "0x10",
                "--reproduce")
    assert r.returncode == 0, r.stderr
    fields = parse_reproduce(r.stdout)
    assert fields["total"] == "1"
    assert fields["region_start"] == "0x10"
    assert fields["slots"] == "0x8"


def test_stack_strings_bad_region_exit_2(tmp_path):
    p = write_tmp(tmp_path, "stack5.bin", b"\x90" * 8)
    r = run_cli("stack-strings", "--in", str(p), "--start", "0x20")
    assert r.returncode == 2
    err = json.loads(r.stderr)
    assert err["exit_code"] == 2


# ---------------------------------------------------------------------------
# binary-sweep
# ---------------------------------------------------------------------------

def test_binary_sweep_kinds(tmp_path):
    data = b"see http://example.com/x and 192.168.1.1 and evil.example.org here"
    p = write_tmp(tmp_path, "blob.bin", data)
    r = run_cli("binary-sweep", "--in", str(p))
    assert r.returncode == 0, r.stderr
    assert "http://example.com/x" in r.stdout
    assert "192.168.1.1" in r.stdout
    assert "evil.example.org" in r.stdout
    assert re.search(r"url@0x[0-9a-f]+", r.stdout)
    assert re.search(r"ipv4@0x[0-9a-f]+", r.stdout)
    assert re.search(r"domain@0x[0-9a-f]+", r.stdout)


def test_binary_sweep_custom_pattern_every_occurrence(tmp_path):
    data = b"\x90\x90S3CR3T\x90\x90S3CR3T\x90"
    p = write_tmp(tmp_path, "blob2.bin", data)
    r = run_cli("binary-sweep", "--in", str(p), "--pattern", "S3CR3T")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("S3CR3T") == 2  # custom sweep reports every hit


def test_binary_sweep_reproduce(tmp_path):
    data = b"visit https://example.com/path?x=1 now"
    p = write_tmp(tmp_path, "blob3.bin", data)
    r = run_cli("binary-sweep", "--in", str(p), "--kind", "url", "--reproduce")
    assert r.returncode == 0, r.stderr
    fields = parse_reproduce(r.stdout)
    assert fields["tool"] == "binary-sweep"
    assert fields["total"] == "1"
    assert fields["count_url"] == "1"
    assert fields["first_value"] == "https://example.com/path?x=1"


def test_binary_sweep_json(tmp_path):
    data = b"x 10.0.0.1 y"
    p = write_tmp(tmp_path, "blob4.bin", data)
    r = run_cli("binary-sweep", "--in", str(p), "--kind", "ipv4", "--json")
    assert r.returncode == 0, r.stderr
    data_obj = json.loads(r.stdout)
    assert data_obj["counts"] == {"ipv4": 1}
    assert data_obj["matches"][0]["value"] == "10.0.0.1"
    assert data_obj["matches"][0]["offset"] == 2


# ---------------------------------------------------------------------------
# strings-classify
# ---------------------------------------------------------------------------

def _classify_fixture():
    return (b"\x00hello world string\x00"
            + b"A" * 40 + b"\x00"
            + b"deadbeefdeadbeefdeadbeefdeadbeef\x00")


def test_strings_classify(tmp_path):
    p = write_tmp(tmp_path, "strs.bin", _classify_fixture())
    r = run_cli("strings-classify", "--in", str(p))
    assert r.returncode == 0, r.stderr
    assert "hello world string" in r.stdout
    assert "b64=1" in r.stdout      # 'A'*40 matches the base64 candidate regex
    assert "hex=1" in r.stdout      # 32 hex chars match the hex candidate regex


def test_strings_classify_utf16le(tmp_path):
    data = b"\x00\x00" + "wide".encode("utf-16-le") + b"\x00\x00"
    p = write_tmp(tmp_path, "strs2.bin", data)
    r = run_cli("strings-classify", "--in", str(p), "--encoding", "utf16le")
    assert r.returncode == 0, r.stderr
    assert "'wide'" in r.stdout
    assert "enc=utf16le" in r.stdout


def test_strings_classify_reproduce(tmp_path):
    p = write_tmp(tmp_path, "strs3.bin", _classify_fixture())
    r = run_cli("strings-classify", "--in", str(p), "--reproduce")
    assert r.returncode == 0, r.stderr
    fields = parse_reproduce(r.stdout)
    assert fields["tool"] == "strings-classify"
    assert fields["total"] == "3"
    assert fields["unique"] == "3"
    assert fields["long_strings"] == "2"  # 40 and 32 chars >= 32


def test_strings_classify_json(tmp_path):
    p = write_tmp(tmp_path, "strs4.bin", _classify_fixture())
    r = run_cli("strings-classify", "--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    inv = data["inventory"]
    assert inv["total"] == 3
    assert inv["avg_entropy_bits_per_char"] > 0
    classes = {s["value"]: s for s in data["strings"]}
    assert classes["hello world string"]["printable_ratio"] == 1.0
    assert classes["A" * 40]["base64"] is True
    assert classes["deadbeefdeadbeefdeadbeefdeadbeef"]["hex"] is True


# ---------------------------------------------------------------------------
# go-buildinfo-carve
# ---------------------------------------------------------------------------

def _buildinfo_blob():
    return (b"\xff Go buildinf:\x08\x02"
            b"go1.23.2\x00"
            b"path\tgithub.com/acme/app\n"
            b"mod\tgithub.com/acme/app (devel)\n"
            b"dep\tgithub.com/dep1 v1.0.0 h1:aaaa\n"
            b"dep\tgithub.com/dep2 v2.0.0\n"
            + b"\x00" * 32)


def test_go_buildinfo_carve(tmp_path):
    p = write_tmp(tmp_path, "go.bin", b"\x00" * 16 + _buildinfo_blob())
    r = run_cli("go-buildinfo-carve", "--in", str(p))
    assert r.returncode == 0, r.stderr
    assert "go=1.23.2" in r.stdout
    assert "path=github.com/acme/app" in r.stdout
    assert "mods=1" in r.stdout
    assert "deps=2" in r.stdout


def test_go_buildinfo_carve_multiple_and_reproduce(tmp_path):
    p = write_tmp(tmp_path, "go2.bin", _buildinfo_blob() + _buildinfo_blob())
    r = run_cli("go-buildinfo-carve", "--in", str(p), "--reproduce")
    assert r.returncode == 0, r.stderr
    fields = parse_reproduce(r.stdout)
    assert fields["tool"] == "go-buildinfo-carve"
    assert fields["total"] == "2"
    assert fields["first_go"] == "1.23.2"
    assert fields["first_path"] == "github.com/acme/app"
    assert fields["first_deps"] == "2"


def test_go_buildinfo_carve_json(tmp_path):
    p = write_tmp(tmp_path, "go3.bin", b"\x00" * 16 + _buildinfo_blob())
    r = run_cli("go-buildinfo-carve", "--in", str(p), "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["total"] == 1
    blob = data["blobs"][0]
    assert blob["go_version"] == "1.23.2"
    assert blob["dep_count"] == 2
    assert blob["offset"] == 18  # 16 zero bytes + b'\xff ' before 'Go buildinf'


# ---------------------------------------------------------------------------
# call-site-args
# ---------------------------------------------------------------------------

def test_call_site_args_x64(tmp_path):
    text = ("0x401000  mov rcx, 0x22e044\n"
            "0x401005  mov edx, 4\n"
            "0x40100a  call 0x7ffa1234\n")
    p = write_tmp(tmp_path, "disasm.txt", text)
    r = run_cli("call-site-args", "--in", str(p))
    assert r.returncode == 0, r.stderr
    assert "addr=0x40100a" in r.stdout
    assert "target=0x7ffa1234" in r.stdout
    assert "rcx=0x22e044" in r.stdout
    assert "rdx=4" in r.stdout


def test_call_site_args_stack_slot(tmp_path):
    text = ("0x500000  mov dword ptr [rsp+0x20], 3\n"
            "0x500005  mov rcx, 1\n"
            "0x50000a  call qword ptr [rip+0x2607f]\n")
    p = write_tmp(tmp_path, "disasm2.txt", text)
    r = run_cli("call-site-args", "--in", str(p))
    assert r.returncode == 0, r.stderr
    assert "stack[0x20]=3" in r.stdout
    assert "rcx=1" in r.stdout


def test_call_site_args_x86_push_order(tmp_path):
    p = write_tmp(tmp_path, "disasm3.txt", "push 0x10\npush 0x20\ncall 0x1234\n")
    r = run_cli("call-site-args", "--in", str(p), "--abi", "x86")
    assert r.returncode == 0, r.stderr
    assert "push0=0x10" in r.stdout and "push1=0x20" in r.stdout


def test_call_site_args_reproduce_and_json(tmp_path):
    text = ("0x401000  mov rcx, 0x22e044\n"
            "0x401005  mov edx, 4\n"
            "0x40100a  call 0x7ffa1234\n")
    p = write_tmp(tmp_path, "disasm4.txt", text)
    r = run_cli("call-site-args", "--in", str(p), "--reproduce")
    assert r.returncode == 0, r.stderr
    fields = parse_reproduce(r.stdout)
    assert fields["tool"] == "call-site-args"
    assert fields["total_callsites"] == "1"
    assert fields["total_with_args"] == "1"
    assert fields["first_address"] == "0x40100a"
    assert fields["first_regs"] == "rcx=0x22e044,rdx=4"

    rj = run_cli("call-site-args", "--in", str(p), "--json")
    assert rj.returncode == 0, rj.stderr
    data = json.loads(rj.stdout)
    assert data["callsites"][0]["args"]["regs"]["rdx"] == "4"


def test_non_utf8_input_no_traceback(tmp_path):
    """r2-278-1b H1 regression: non-UTF8 binary input must NEVER crash with a
    bare UnicodeEncodeError traceback (GBK console cannot encode U+FFFD emitted
    by decode(errors="replace")). Every mode must stay structured."""
    blob = bytes(range(256)) * 40  # every byte value incl. invalid UTF-8
    p = write_tmp(tmp_path, "blob.bin", blob)
    for tool in ("go-buildinfo-carve", "call-site-args"):
        for mode in ((), ("--json",), ("--reproduce",)):
            r = run_cli(tool, "--in", str(p), *mode)
            assert "Traceback" not in r.stderr, f"{tool} {mode}: bare traceback"
            assert r.returncode in (0, 1, 2), f"{tool} {mode}: rc={r.returncode}"
