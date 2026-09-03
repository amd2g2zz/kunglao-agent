# -*- coding: utf-8 -*-
"""Tests for issue #756 — toolchain 判定 bug (C1/C2/C3).

RED-first TDD acceptance suite:
  C1  _probe_native_so must read the zip central directory (APKs), not the
      head 4KB (local lib/ headers can sit anywhere; the central directory
      sits at the TAIL). Plain .so suffix stays True; BadZipFile fails OPEN
      to the legacy head scan; never raises.
  C2  has_native_so chain fixation: android workspace + APK containing
      lib/**.so -> decompiler FAIL/HARD semantics (the live-run sample repro);
      pure-DEX APK -> WARN semantics.
  C3  decompiler FAIL copy treats Ghidra and IDA as equals ("Ghidra OR IDA —
      either satisfies this check"), MCP path listed unchanged, "#408"
      installer anchor retained.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import toolchain as tc  # pytest.ini pythonpath = scripts

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_ws(tmp_path: Path) -> Path:
    """Minimal workspace skeleton toolchain.py accepts (runs/ + bins/)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "bins").mkdir()
    return ws


def build_tail_offset_apk(path: Path, *, include_lib: bool = True) -> Path:
    """Minimal APK whose lib/**.so LOCAL header sits BEYOND the head-4KB
    window — reproduces #756: the central directory (tail) knows entries the
    head window cannot see.

    A ZIP_STORED classes.dex payload of exactly 8KB pushes every later local
    file header past byte 4096, so the legacy `head[:4096]` scan finds no
    b'lib/' / b'.so' even for a fully native APK.
    """
    assert zipfile.ZipInfo("classes.dex").compress_type == zipfile.ZIP_STORED, \
        "fixture depends on ZipInfo defaulting to STORED (offset math)"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("classes.dex"),
                    bytes(range(256)) * 32)
        zf.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00" + b"\x00" * 32)
        if include_lib:
            zf.writestr("lib/arm64-v8a/libnative.so",
                        b"\x7fELF" + b"\x00" * 64)
    head = path.read_bytes()[:4096]
    assert b"lib/" not in head and b".so" not in head, (
        "fixture drift: a lib entry is visible inside the first 4KB — "
        "the tail-offset repro condition is lost")
    return path


def _run_toolchain(ws: Path, *extra: str) -> dict:
    """Run scripts/toolchain.py hermetically (no host tools, no MCP supply).

    PATH is REPLACED with an empty dir (decompiler/idat64/GHIDRA_HOME probes
    must miss regardless of host installs) and KUNGLAO_CLAUDE_JSON pins an
    MCP registry WITHOUT ghidra / ida-pro-vm.
    """
    empty_bin = ws.parent / "empty-bin"
    empty_bin.mkdir(exist_ok=True)
    fake_claude = ws.parent / "fake-claude.json"
    fake_claude.write_text(
        json.dumps({"mcpServers": {"sequential-thinking": {}}}),
        encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in ("GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env.update({
        "PATH": str(empty_bin),
        "KUNGLAO_CLAUDE_JSON": str(fake_claude),
        "PYTHONIOENCODING": "utf-8",
    })
    argv = [sys.executable, str(SCRIPTS / "toolchain.py"), str(ws), *extra]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                       env=env, errors="replace")
    assert r.stdout.strip(), (
        f"no JSON on stdout: rc={r.returncode} err={r.stderr[-400:]}")
    return json.loads(r.stdout)


def _find_check(data: dict, name: str) -> dict:
    return next(c for c in data["checks"] if c["name"] == name)


# ---------------------------------------------------------------------------
# C1 — _probe_native_so unit matrix
# ---------------------------------------------------------------------------

def test_probe_native_so_apk_central_directory_true(tmp_path):
    """#756 C1: an APK whose only lib/**.so evidence lives in the central
    directory (tail) must probe True — the head-4KB scan misses it."""
    ws = _mk_ws(tmp_path)
    build_tail_offset_apk(ws / "bins" / "sample.apk", include_lib=True)
    assert tc._probe_native_so(ws) is True


def test_probe_native_so_apk_pure_dex_false(tmp_path):
    """#756 C1: a zip with NO lib/ entries probes False (pure DEX)."""
    ws = _mk_ws(tmp_path)
    build_tail_offset_apk(ws / "bins" / "sample.apk", include_lib=False)
    assert tc._probe_native_so(ws) is False


def test_probe_native_so_plain_so_file_true(tmp_path):
    """Non-zip .so objects keep the suffix rule (unchanged behavior)."""
    ws = _mk_ws(tmp_path)
    (ws / "bins" / "libnative.so").write_bytes(b"\x7fELF" + b"\x00" * 64)
    assert tc._probe_native_so(ws) is True


def test_probe_native_so_bad_zip_fails_open_to_head_scan(tmp_path):
    """Corrupt zip whose head DOES reference lib/ — BadZipFile must fail open
    to the legacy head-4KB logic (True), never raise."""
    ws = _mk_ws(tmp_path)
    bad = ws / "bins" / "corrupt.apk"
    bad.write_bytes(b"PK\x03\x04" + b"\x00" * 20
                    + b"lib/arm64-v8a/truncated.so" + b"\x00" * 64)
    assert tc._probe_native_so(ws) is True


def test_probe_native_so_bad_zip_without_signal_false_no_crash(tmp_path):
    """Garbage that is neither zip nor .so-headed probes False without
    raising (BadZipFile path swallowed)."""
    ws = _mk_ws(tmp_path)
    (ws / "bins" / "garbage.apk").write_bytes(b"MZ" + b"\x00" * 512)
    assert tc._probe_native_so(ws) is False


# ---------------------------------------------------------------------------
# C2 — has_native_so chain fixation (android integration via CLI JSON)
# ---------------------------------------------------------------------------

def test_android_apk_with_native_so_decompiler_hard(tmp_path):
    """The live-run sample repro at mini scale: android workspace where bins/ holds an
    APK with lib/arm64-v8a/*.so (head-invisible) and no decompiler supply ->
    the decompiler check owes HARD semantics: status FAIL, tier HARD,
    root_cause 'decompiler'."""
    ws = _mk_ws(tmp_path)
    build_tail_offset_apk(ws / "bins" / "53f8094a.apk", include_lib=True)
    data = _run_toolchain(ws, "--type", "android", "--json")
    decomp = _find_check(data, "decompiler")
    assert decomp["status"] == "FAIL", decomp
    assert decomp["tier"] == "HARD", decomp
    assert decomp["root_cause"] == "decompiler", decomp


def test_android_pure_dex_apk_decompiler_warn(tmp_path):
    """Pure-DEX android workspace (zip has no lib/ entries) keeps WARN
    semantics — no HARD failure without native code."""
    ws = _mk_ws(tmp_path)
    build_tail_offset_apk(ws / "bins" / "pure_dex.apk", include_lib=False)
    data = _run_toolchain(ws, "--type", "android", "--json")
    decomp = _find_check(data, "decompiler")
    assert decomp["status"] == "WARN", decomp
    assert decomp["tier"] == "HARD", decomp
# ---------------------------------------------------------------------------
# C3 — copy equality (Ghidra OR IDA, either satisfies; MCP path unchanged;
#      "#408" installer anchor retained — pinned by init-gate/mcp-supply tests)
# ---------------------------------------------------------------------------

def test_decompiler_fail_copy_ida_ghidra_equal(tmp_path):
    """Native-.so FAIL copy must present Ghidra and IDA as peers in BOTH the
    detail and the resolved fix text."""
    ws = _mk_ws(tmp_path)
    build_tail_offset_apk(ws / "bins" / "53f8094a.apk", include_lib=True)
    data = _run_toolchain(ws, "--type", "android", "--json")
    decomp = _find_check(data, "decompiler")
    detail, fix = decomp["detail"], decomp["fix"]
    assert "IDA" in detail and "Ghidra" in detail, detail
    assert "Ghidra OR IDA" in detail, detail
    assert "either satisfies this check" in detail, detail
    # ToolMeta("decompiler").fix surfaced through format_json's fallback
    assert fix is not None, decomp
    assert "Ghidra OR IDA" in fix, fix
    assert "either satisfies this check" in fix, fix
    assert "#408" in fix, fix               # test_init_toolchain_gate pin
    assert "ghidra/ida-pro-vm" in fix, fix  # MCP path still listed
    assert "claude mcp add" in fix, fix


def test_decompiler_nosignal_fail_copy_ida_ghidra_equal(tmp_path):
    """The no-decompiler-signal FAIL branch (windows/linux unconditional
    HARD; reached here via linux) carries the same peer wording."""
    ws = _mk_ws(tmp_path)
    data = _run_toolchain(ws, "--type", "linux", "--json")
    decomp = _find_check(data, "decompiler")
    assert decomp["status"] == "FAIL", decomp
    detail = decomp["detail"]
    assert "IDA" in detail and "Ghidra" in detail, detail
    assert "Ghidra OR IDA" in detail, detail
    assert "either satisfies this check" in detail, detail
