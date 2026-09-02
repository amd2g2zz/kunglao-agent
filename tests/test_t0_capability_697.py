# -*- coding: utf-8 -*-
"""#697: T0/T1/T2 which-probes upgrade PRESENCE to real-execution LIVENESS.

Issue #697 (kunglao-lab dogfooding): on a Linux analysis box, diec was
missing libQt5Script.so, floss was a 0-byte extraction leftover, and
frida had only the server binary — three distinct breakage modes, and
shutil.which PASSED all three. The probe reported "found at /usr/local/
bin/floss" while the tool could never run, so init (free time) let a
broken toolchain through and the failure surfaced at worker dispatch
(paid time) as `diec: not found`.

The fix is wiring, not data entry: ToolMeta.verify_cmd is already filled
for the whole family (FIXES registry, toolchain.py) but was only ever
PRINTED (installer output), never EXECUTED by the probe. _which_items
now runs the verify command (via the fail-open _run_cmd) when a meta
exists: rc==0 upgrades the result to ProbeTier.LIVENESS with the first
stdout line in the detail; rc!=0 or crash degrades to WARN (never FAIL
— #449 needs-first: a broken optional tool must not gate a static task)
with the first stderr line as the cause. Tools without a verify_cmd
keep the exact pre-#697 PRESENCE behavior.

#688 isolation: every fixture builds its own fake PATH under tmp_path —
the real host toolchain never leaks into expectations.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from toolchain import (  # noqa: E402
    FIXES, ProbeTier, Status, Tier, _which_items,
)


def _mk_bin(tmp_path: Path, name: str, body: str) -> Path:
    """A fake tool on a fake PATH: executable POSIX script."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    p = bindir / name
    p.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bindir


def test_healthy_tool_upgrades_to_liveness(tmp_path, monkeypatch):
    """rc==0 verify → PASS + ProbeTier.LIVENESS + first stdout line."""
    bindir = _mk_bin(tmp_path, "file", 'echo "file-5.41"; exit 0')
    monkeypatch.setenv("PATH", str(bindir))
    items = _which_items(("file",), Tier.HARD)
    assert len(items) == 1
    it = items[0]
    assert it.status == Status.PASS
    assert it.probe == ProbeTier.LIVENESS
    assert "file-5.41" in it.detail


def test_broken_tool_warns_with_real_cause(tmp_path, monkeypatch):
    """The #697 diec scenario: which hits, verify fails with the loader
    error → WARN (needs-first, NOT FAIL) + first stderr line in detail."""
    bindir = _mk_bin(
        tmp_path, "file",
        'echo "file: error while loading shared libraries: '
        'libQt5Script.so.5: cannot open shared object file" >&2; exit 1')
    monkeypatch.setenv("PATH", str(bindir))
    items = _which_items(("file",), Tier.HARD)
    assert len(items) == 1
    it = items[0]
    assert it.status == Status.WARN
    assert "libQt5Script.so.5" in it.detail


def test_zero_byte_tool_warns(tmp_path, monkeypatch):
    """The #697 floss scenario: 0-byte executable residue — verify fails
    (exec format/crash path) → WARN with a cause, never a silent PASS."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    p = bindir / "file"
    p.write_bytes(b"")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bindir))
    items = _which_items(("file",), Tier.HARD)
    it = items[0]
    assert it.status == Status.WARN


def test_tool_without_verify_cmd_keeps_presence(tmp_path, monkeypatch):
    """No FIXES entry (or verify_cmd=None) → exact pre-#697 shape:
    PASS + ProbeTier.PRESENCE, detail is the plain found template."""
    assert FIXES.get("docker") is None or FIXES["docker"].verify_cmd is None
    bindir = _mk_bin(tmp_path, "docker", "exit 0")
    monkeypatch.setenv("PATH", str(bindir))
    items = _which_items(("docker",), Tier.WARN,
                         missing_status=Status.WARN,
                         missing_detail="docker not found (optional)",
                         found_detail="docker at {path}")
    it = items[0]
    assert it.status == Status.PASS
    assert it.probe == ProbeTier.PRESENCE
    assert it.detail == f"docker at {bindir / 'docker'}"


def test_missing_tool_unchanged(tmp_path, monkeypatch):
    """which-miss → the missing branch is byte-identical to pre-#697."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    items = _which_items(("file",), Tier.HARD)
    it = items[0]
    assert it.status == Status.FAIL
    assert it.probe == ProbeTier.PRESENCE
    assert it.detail == "file not found in PATH"


def test_fixes_registry_has_the_697_family():
    """The data the fix wires already exists: the whole #697 family has a
    filled verify_cmd in FIXES (die/floss/objdump/jadx/apktool/gitnexus).
    If a name goes missing, _which_items silently stops verifying it —
    this pin keeps the wiring surface honest."""
    for name in ("die", "floss", "objdump", "readelf", "file", "jadx",
                 "apktool", "gitnexus"):
        meta = FIXES.get(name)
        assert meta is not None, f"FIXES lost {name}"
        assert meta.verify_cmd, f"FIXES[{name}].verify_cmd is empty"
