# -*- coding: utf-8 -*-
"""Issue #25 D1 — the debug_flag (ro.debuggable) gate is unreachable in real
environments.

Android 12+ user builds lock ro.debuggable (SELinux property_service: setprop
rejected, `adb root` refused on production builds, verity nondisablable) —
yet the android gate treats debug_flag as HARD-enforced (#304 F3), so ANY
android init without a physically rooted/debuggable device is blocked even
when the dynamic plan (frida / android_server via Magisk su) does not need
the flag at all. A gate that cannot pass in the most common environment is
the "design assumption silently fails" class the postmortem names.

Fix = WIRE the existing seam, not remove: `_check_android` already receives
the #449 Requirements (task_spec-derived) but ignored them. Now:
  * Requirements grows needs_debug_flag (conservative default True);
  * requirements_from_task_spec derives it — constraints.dynamic_re ==
    "forbidden" (static-only => no JDWP dynamics) or an explicit
    constraints.debug_flag: false (user-build opt-out) both demote;
  * the debug_flag check downgrades FAIL -> WARN citing the basis in the
    detail (reported, never silently skipped — the #449 VM-downgrade
    contract). Absent/garbage task_spec keeps HARD, byte-identical.

TDD RED phase: written BEFORE the implementation (2026-09-04).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import toolchain as tc  # pytest.ini pythonpath = . hooks scripts tools

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


# ---------- unit: requirements_from_task_spec derivation ----------

def test_requirements_debug_flag_explicit_optout():
    """constraints.debug_flag: false -> needs_debug_flag False, VM untouched."""
    reqs = tc.requirements_from_task_spec({"constraints": {"debug_flag": False}})
    assert reqs.needs_debug_flag is False, reqs
    assert reqs.needs_vm is True, "debug_flag opt-out alone must not touch VM"
    assert "debug_flag" in reqs.basis, reqs


def test_requirements_static_only_implies_no_debug_flag():
    """dynamic_re=forbidden (static-only) needs no VM channel AND no JDWP flag."""
    reqs = tc.requirements_from_task_spec(
        {"constraints": {"dynamic_re": "forbidden"}})
    assert reqs.needs_debug_flag is False, reqs
    assert reqs.needs_vm is False, reqs


def test_requirements_debug_flag_conservative_family():
    """Absent/garbage/non-boolean-false debug_flag keeps conservative HARD."""
    for spec in (None, {}, {"constraints": {}},
                 {"constraints": {"debug_flag": True}},
                 {"constraints": {"debug_flag": "false"}},  # string, not bool
                 {"constraints": {"debug_flag": None}}):
        reqs = tc.requirements_from_task_spec(spec)
        assert reqs.needs_debug_flag is True, \
            f"{spec!r} must stay conservative: {reqs}"


def test_requirements_combined_static_only_plus_optout():
    """Both signals present -> both channels relaxed in one Requirements."""
    reqs = tc.requirements_from_task_spec(
        {"constraints": {"dynamic_re": "forbidden", "debug_flag": False}})
    assert reqs.needs_debug_flag is False, reqs
    assert reqs.needs_vm is False, reqs


def test_requirements_debug_flag_immutable():
    reqs = tc.requirements_from_task_spec({"constraints": {"debug_flag": False}})
    with pytest.raises(Exception):
        reqs.needs_debug_flag = True  # type: ignore[misc]


# ---------- e2e: the android gate via the CLI ----------

@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    """Empty fake-bin dir; tests write the platform adb wrapper into it."""
    fb = tmp_path / "fake-bin"
    fb.mkdir()
    return fb


def _write_adb(fake_bin: Path, *, debuggable: str, uid: str = "0") -> None:
    """Minimal platform adb wrapper + stub (same shape as test_toolchain's):
    answers devices / su id / getprop ro.debuggable / getprop sdk / forward."""
    stub = fake_bin / "adb_stub.py"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if 'devices' in args:\n"
        "    print('List of devices attached')\n"
        "    print('emulator-5554\\tdevice')\n"
        "    sys.exit(0)\n"
        "if 'shell' in args and 'su' in args and 'id' in args:\n"
        f"    print('uid={uid}(root) gid=0(root)')\n"
        "    sys.exit(0)\n"
        "if 'shell' in args and 'getprop' in args:\n"
        "    if 'ro.debuggable' in args:\n"
        f"        print('{debuggable}')\n"
        "    else:\n"
        "        print('31')\n"
        "    sys.exit(0)\n"
        "if 'shell' in args and 'ls' in args:\n"
        "    for a in args:\n"
        "        if 'android_server' in a or 'frida' in a:\n"
        "            print(a)\n"
        "    sys.exit(0)\n"
        "if 'forward' in args:\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    adb = fake_bin / "adb"
    adb.write_text(
        f"#!/bin/sh\nexec \"{sys.executable}\" \"{stub}\" \"$@\"\n",
        encoding="utf-8",
    )
    adb.chmod(0o755)


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _pin_claude_json(ws: Path, monkeypatch) -> None:
    """Hermetic MCP probe: never read the developer's real ~/.claude.json."""
    fake = ws.parent / "fake-claude.json"
    if not fake.exists():
        fake.write_text(json.dumps({
            "mcpServers": {name: {} for name in (
                "ghidra", "sequential-thinking", "x64dbg", "gitnexus")},
        }), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(fake))


def _run_toolchain(ws: Path, extra: list[str]) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(SCRIPTS / "toolchain.py"), str(ws), *extra]
    env = {k: v for k, v in os.environ.items()
           if k not in ("GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(argv, capture_output=True, text=True, timeout=60,
                          env=env, errors="replace")


def _debug_flag_item(ws: Path) -> tuple[subprocess.CompletedProcess, dict]:
    r = _run_toolchain(ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    df = next(c for c in data["checks"] if c["name"] == "debug_flag")
    return r, df


def test_android_debug_flag_warn_with_task_spec_optout(
        tmp_path, fake_bin, monkeypatch):
    """#25 D1 core: user build (ro.debuggable=0) + constraints.debug_flag
    false -> the item is REPORTED (WARN) instead of blocking init (FAIL)."""
    _write_adb(fake_bin, debuggable="0")
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    ws = _mk_ws(tmp_path)
    _pin_claude_json(ws, monkeypatch)
    (ws / "task_spec.yaml").write_text(yaml.safe_dump(
        {"constraints": {"debug_flag": False}}, sort_keys=False),
        encoding="utf-8")
    r, df = _debug_flag_item(ws)
    assert df["status"] == "WARN", \
        f"opted-out debug_flag must WARN, not block init: {df}"
    assert df["tier"] == "WARN", df
    assert "debug_flag" in df["detail"], "basis must ride into the detail"
    assert "task_spec" in df["detail"], df


def test_android_debug_flag_pass_untouched_when_optout_and_set(
        tmp_path, fake_bin, monkeypatch):
    """Opt-out only lifts the enforcement floor; a set flag still PASSes."""
    _write_adb(fake_bin, debuggable="1")
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    ws = _mk_ws(tmp_path)
    _pin_claude_json(ws, monkeypatch)
    (ws / "task_spec.yaml").write_text(yaml.safe_dump(
        {"constraints": {"debug_flag": False}}, sort_keys=False),
        encoding="utf-8")
    r, df = _debug_flag_item(ws)
    assert df["status"] == "PASS", df


def test_android_debug_flag_stays_hard_without_task_spec(
        tmp_path, fake_bin, monkeypatch):
    """Conservative pin: absent task_spec keeps the pre-#25 HARD gate
    (byte-identical; test_toolchain F3 owns the long-form contract)."""
    _write_adb(fake_bin, debuggable="0")
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    ws = _mk_ws(tmp_path)
    _pin_claude_json(ws, monkeypatch)
    r, df = _debug_flag_item(ws)
    assert df["status"] == "FAIL", f"no task_spec must stay HARD: {df}"
    assert df["tier"] == "HARD", df
    assert r.returncode == 1, "HARD debug_flag FAIL must still exit 1"
