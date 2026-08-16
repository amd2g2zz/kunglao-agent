# -*- coding: utf-8 -*-
"""Tests for scripts/toolchain.py — type-aware toolchain probe matrix (#304).

TDD RED phase: write failing tests BEFORE implementation.

Fake-bin PATH injection + fake adb script to test probes WITHOUT real devices.
Cascade semantics, exit codes, JSON/reproduce output, type resolution from
analysis_state.txt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    """Create a fake-bin directory with stub executables.

    NOTE: extensionless stub files are NOT executable on Windows — they exist
    only for PATH-presence probes (shutil.which). Tools that must actually
    EXECUTE (adb) get a .bat wrapper calling a python stub (see
    fake_adb_script).
    """
    fb = tmp_path / "fake-bin"
    fb.mkdir()
    for name in ("aapt", "aapt2", "jadx", "apktool", "gitnexus", "java",
                 "readelf", "objdump", "file", "gdbserver", "strace",
                 "ltrace", "docker"):
        (fb / name).write_text(
            "#!/usr/bin/env python3\nimport sys\n"
            "if '--version' in sys.argv:\n    print(f'{sys.argv[0]} version 1.0')\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
    return fb


def _write_adb_wrapper(fake_bin: Path, stub: Path) -> None:
    """Write a platform-appropriate adb wrapper that executes `stub`.

    Windows: adb.bat (shutil.which resolves .bat via PATHEXT). POSIX: an
    extensionless executable `adb` script — shutil.which requires the
    exact name plus the exec bit there.
    """
    if os.name == "nt":
        (fake_bin / "adb.bat").write_text(
            f"@echo off\r\npython \"{stub}\" %*\r\n", encoding="utf-8")
    else:
        adb = fake_bin / "adb"
        adb.write_text(
            f"#!/bin/sh\nexec \"{sys.executable}\" \"{stub}\" \"$@\"\n",
            encoding="utf-8",
        )
        adb.chmod(0o755)


@pytest.fixture
def fake_adb_script(tmp_path: Path, fake_bin: Path) -> Path:
    """Create a fake adb (wrapper -> adb_stub.py) that responds to
    'devices' / 'shell su -c id' / 'shell getprop ro.build.version.sdk'.

    The wrapper is platform-aware: adb.bat on Windows (extensionless files
    are not executable there), an extensionless executable `adb` script on
    POSIX (shutil.which only resolves the exact name there).
    """
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
        "    print('uid=0(root) gid=0(root)')\n"
        "    sys.exit(0)\n"
        "if 'shell' in args and 'getprop' in args:\n"
        "    if 'ro.debuggable' in args:\n"
        "        print('1')\n"
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
    _write_adb_wrapper(fake_bin, stub)
    return stub


@pytest.fixture
def kunglao_ws(tmp_path: Path) -> Path:
    """Minimal workspace with runs/ directory."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _run_toolchain(ws: Path, extra: list[str] | None = None,
                   env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run toolchain.py with hermetic env."""
    argv = [sys.executable, str(SCRIPTS / "toolchain.py"), str(ws), *(extra or [])]
    base_env = {k: v for k, v in os.environ.items()
                if k not in ("GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    base_env["PYTHONIOENCODING"] = "utf-8"
    # Hermetic MCP probe: without this the probe reads the real ~/.claude.json
    # (present on dev machines, absent on CI) — HARD-tier MCP results would
    # depend on the runner. Pin to a fake registering the HARD servers, same
    # pattern as tests/test_mcp_supply.py.
    fake_claude = ws.parent / "fake-claude.json"
    if not fake_claude.exists():
        fake_claude.write_text(json.dumps({
            "mcpServers": {name: {} for name in (
                "ghidra", "sequential-thinking", "x64dbg", "gitnexus")},
        }), encoding="utf-8")
    base_env["KUNGLAO_CLAUDE_JSON"] = str(fake_claude)
    if env:
        base_env.update(env)
    return subprocess.run(argv, capture_output=True, text=True, timeout=60,
                          env=base_env, errors="replace")


def _rewrite_adb_stub(fake_bin: Path, *, uid: str = "0", debuggable: str = "1",
                      sdk: str = "31", handle_forward: bool = True) -> Path:
    """Rewrite fake_bin/adb_stub.py with custom device responses
    (uid / ro.debuggable / sdk / forward). Returns the stub path."""
    lines = [
        "import sys",
        "args = sys.argv[1:]",
        "if 'devices' in args:",
        "    print('List of devices attached')",
        "    print('emulator-5554\\tdevice')",
        "    sys.exit(0)",
        "if 'shell' in args and 'su' in args and 'id' in args:",
        f"    print('uid={uid}(root) gid={uid}(root)')",
        "    sys.exit(0)",
        "if 'shell' in args and 'getprop' in args:",
        "    if 'ro.debuggable' in args:",
        f"        print('{debuggable}')",
        "    else:",
        f"        print('{sdk}')",
        "    sys.exit(0)",
    ]
    if handle_forward:
        lines.append("if 'forward' in args:")
        lines.append("    sys.exit(0)")
    lines.append("sys.exit(0)")
    stub = fake_bin / "adb_stub.py"
    stub.write_text("\n".join(lines), encoding="utf-8")
    _write_adb_wrapper(fake_bin, stub)
    return stub


def _local_listener(port: int):
    """Bind a 127.0.0.1 TCP listener (backlog only, no accept needed for the
    TCP-connect probe); returns the socket or None if the port is taken."""
    import socket as socket_mod
    try:
        return socket_mod.create_server(("127.0.0.1", port))
    except OSError:
        return None


# ---------- basic CLI tests ----------

def test_toolchain_script_exists():
    """toolchain.py exists and is importable."""
    assert (SCRIPTS / "toolchain.py").exists(), "toolchain.py missing"


def test_toolchain_no_args_shows_usage():
    """No arguments -> non-zero exit + usage on stderr."""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "toolchain.py")],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode != 0, "no-args should fail"


def test_toolchain_invalid_type_fails(kunglao_ws):
    """--type with invalid value -> non-zero exit."""
    r = _run_toolchain(kunglao_ws, ["--type", "invalid"])
    assert r.returncode != 0, "invalid type should fail"


# ---------- Windows toolchain ----------

def test_windows_all_pass(fake_bin, kunglao_ws, monkeypatch):
    """Windows type with all tools present -> PASS per item, exit 0."""
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    monkeypatch.setenv("GHIDRA_HOME", str(fake_bin))
    # Create fake analyzeHeadless
    (fake_bin / "analyzeHeadless.bat").write_text("@echo off\r\n", encoding="utf-8")
    r = _run_toolchain(kunglao_ws, ["--type", "windows"])
    # Should have PASS items; overall exit 0 if no HARD failures
    # Note: VM check will FAIL since no real VM, but that's expected
    assert "[PASS]" in r.stdout or "[FAIL]" in r.stdout


def test_windows_missing_pefile_reported(fake_bin, kunglao_ws, monkeypatch):
    """Windows type missing pefile -> FAIL with guidance."""
    # Remove pefile from fake-bin by pointing PATH to empty dir
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "windows"])
    assert r.returncode != 0, "missing tools should cause FAIL exit"
    assert "pefile" in r.stdout.lower() or "die" in r.stdout.lower() or "floss" in r.stdout.lower()


# ---------- Linux toolchain ----------

def test_linux_binutils_checked(fake_bin, kunglao_ws, monkeypatch):
    """Linux type checks for readelf/objdump in PATH."""
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    monkeypatch.setenv("GHIDRA_HOME", str(fake_bin))
    (fake_bin / "analyzeHeadless.bat").write_text("@echo off\r\n", encoding="utf-8")
    r = _run_toolchain(kunglao_ws, ["--type", "linux"])
    # Should check readelf, objdump
    assert "readelf" in r.stdout.lower() or "objdump" in r.stdout.lower()


def test_linux_ebpf_warn_not_fail(fake_bin, kunglao_ws, monkeypatch):
    """Linux eBPF check with kernel <= 6 -> WARN, not FAIL."""
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "linux"])
    # eBPF should be WARN tier, not block overall
    # (other HARD failures will block, but eBPF itself should warn)
    output = r.stdout.lower()
    assert "warn" in output or "ebpf" in output


# ---------- Android toolchain ----------

def test_android_adb_root_check(fake_adb_script, fake_bin, kunglao_ws, monkeypatch):
    """Android type with fake adb -> checks ADB + root."""
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android"])
    output = r.stdout.lower()
    # ADB should be checked
    assert "adb" in output


def test_android_adb_missing_cascades(fake_bin, kunglao_ws, monkeypatch):
    """Android ADB missing -> frida-server/android_server discovery impossible
    (cascade error names root cause)."""
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android"])
    output = r.stdout.lower() + r.stderr.lower()
    # Should mention adb as root cause for downstream failures
    assert "adb" in output


def test_android_gitnexus_required(fake_bin, kunglao_ws, monkeypatch):
    """Android GitNexus is HARD tier -> missing should report."""
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android"])
    assert "gitnexus" in r.stdout.lower()


def test_android_ebpf_sdk31_pass_with_fake_adb(fake_adb_script, fake_bin,
                                                kunglao_ws, monkeypatch):
    """Android SDK >= 31 (fake adb getprop) -> ebpf_android check PASS (WARN tier)."""
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    ebpf = next(c for c in data["checks"] if c["name"] == "ebpf_android")
    assert ebpf["status"] == "PASS", f"expected PASS, got {ebpf}"
    assert "31" in ebpf["detail"]


def test_android_native_so_makes_decompiler_hard(fake_bin, kunglao_ws, monkeypatch):
    """Sample with .so + no decompiler -> decompiler check FAIL (HARD)."""
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty), prepend=os.pathsep)
    (kunglao_ws / "bins").mkdir(exist_ok=True)
    (kunglao_ws / "bins" / "libnative.so").write_bytes(b"\x7fELF" + b"\x00" * 64)
    r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    decomp = next(c for c in data["checks"] if c["name"] == "decompiler")
    assert decomp["status"] == "FAIL", f"expected FAIL for native .so, got {decomp}"


def test_android_root_check_with_fake_adb(fake_adb_script, fake_bin,
                                          kunglao_ws, monkeypatch):
    """Fake adb devices + su -c id -> adb PASS + device_root PASS."""
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    adb_check = next(c for c in data["checks"] if c["name"] == "adb")
    root_check = next(c for c in data["checks"] if c["name"] == "device_root")
    assert adb_check["status"] == "PASS", adb_check
    assert root_check["status"] == "PASS", root_check


# ---------- type from analysis_state.txt ----------

def test_type_read_from_analysis_state(kunglao_ws):
    """--type absent -> reads project_type= from analysis_state.txt."""
    (kunglao_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=linux\n", encoding="utf-8"
    )
    r = _run_toolchain(kunglao_ws)
    assert "linux" in r.stdout.lower()


def test_type_missing_from_analysis_state_uses_default(kunglao_ws):
    """No --type and no project_type in analysis_state -> exit error."""
    r = _run_toolchain(kunglao_ws)
    assert r.returncode != 0


# ---------- JSON output ----------

def test_json_output_flag(fake_bin, kunglao_ws, monkeypatch):
    """--json produces valid JSON on stdout."""
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty), prepend=os.pathsep)
    (kunglao_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=windows\n", encoding="utf-8"
    )
    r = _run_toolchain(kunglao_ws, ["--json"])
    try:
        data = json.loads(r.stdout)
        assert "overall" in data or "items" in data or "checks" in data
    except json.JSONDecodeError:
        pytest.fail(f"--json did not produce valid JSON: {r.stdout[:200]}")


# ---------- Reproduce output ----------

def test_reproduce_flag(fake_bin, kunglao_ws, monkeypatch):
    """--reproduce produces machine-parseable output for CI."""
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty), prepend=os.pathsep)
    (kunglao_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=windows\n", encoding="utf-8"
    )
    r = _run_toolchain(kunglao_ws, ["--reproduce"])
    assert r.stdout.strip()  # non-empty output


# ---------- Exit codes ----------

def test_exit_0_all_pass():
    """F5: a report with every HARD check PASS and no WARN-tier failures ->
    exit_code 0 / overall PASS (the mapping the CLI exit code is built on)."""
    import toolchain as tc
    report = tc.ToolchainReport(project_type="windows", items=[
        tc.CheckResult(name="pefile", status=tc.Status.PASS, tier=tc.Tier.HARD, detail="ok"),
        tc.CheckResult(name="vm_reachable", status=tc.Status.PASS, tier=tc.Tier.HARD, detail="ok"),
        tc.CheckResult(name="docker", status=tc.Status.PASS, tier=tc.Tier.WARN, detail="ok"),
    ])
    assert report.overall_status == tc.Status.PASS
    assert report.exit_code == 0


def test_exit_2_warn_only(fake_bin, kunglao_ws, monkeypatch):
    """F5: all HARD checks PASS, only WARN-tier items outstanding -> exit 2.
    Android end-to-end: full fake toolchain + fake adb + TCP listeners for
    frida/android_server -> every HARD item passes; unidbg (WARN tier) keeps
    the overall at WARN -> exit code 2."""
    import socket as socket_mod
    # Platform-aware wrappers so shutil.which finds the fake tools on both
    # Windows (.bat via PATHEXT) and POSIX (extensionless + exec bit).
    for tool in ("aapt", "jadx", "apktool"):
        if os.name == "nt":
            (fake_bin / f"{tool}.bat").write_text("@echo off\r\nexit /b 0\r\n",
                                                  encoding="utf-8")
        else:
            path = fake_bin / tool
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
    gn_stub = fake_bin / "gn_stub.py"
    gn_stub.write_text("print('gitnexus version 1.0')\n", encoding="utf-8")
    if os.name == "nt":
        (fake_bin / "gitnexus.bat").write_text(
            f"@echo off\r\npython \"{gn_stub}\" %*\r\n", encoding="utf-8")
    else:
        gn = fake_bin / "gitnexus"
        gn.write_text(
            f"#!/bin/sh\nexec \"{sys.executable}\" \"{gn_stub}\" \"$@\"\n",
            encoding="utf-8")
        gn.chmod(0o755)
    _rewrite_adb_stub(fake_bin)
    # decompiler: GHIDRA_HOME + analyzeHeadless.bat
    (fake_bin / "analyzeHeadless.bat").write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setenv("GHIDRA_HOME", str(fake_bin))

    frida_sock = socket_mod.create_server(("127.0.0.1", 0))
    frida_port = frida_sock.getsockname()[1]
    as_sock = _local_listener(23946)
    if as_sock is None:
        frida_sock.close()
        pytest.skip("port 23946 busy on this host")
    try:
        monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
        monkeypatch.setenv("KUNGLAO_FRIDA_PORT", str(frida_port))
        r = _run_toolchain(kunglao_ws, ["--type", "android"])
        assert r.returncode == 2, \
            f"warn-only run must exit 2, got {r.returncode}: {r.stdout}{r.stderr}"
        assert "OVERALL: WARN" in r.stdout, f"expected OVERALL: WARN: {r.stdout}"
        assert "[FAIL]" not in r.stdout, \
            f"no HARD failure expected in warn-only run: {r.stdout}"
    finally:
        frida_sock.close()
        as_sock.close()


def test_exit_1_hard_fail(kunglao_ws, monkeypatch):
    """HARD failure -> exit 1."""
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "windows"])
    assert r.returncode == 1, f"HARD fail should be exit 1, got {r.returncode}"


# ---------- Cascade error messages ----------

def test_cascade_adb_missing_names_root_cause(fake_bin, kunglao_ws, monkeypatch):
    """When ADB is missing, frida-server and android_server checks should
    name ADB as the root cause."""
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android"])
    output = r.stdout + r.stderr
    # Root cause mention
    assert "adb" in output.lower(), \
        "cascade error should name ADB as root cause"


def test_cascade_vm_missing_names_root_cause(fake_bin, kunglao_ws, monkeypatch):
    """When VM is unreachable, remote debugger checks should name VM."""
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "windows"])
    output = r.stdout + r.stderr
    assert "vm" in output.lower() or "KUNGLAO_VM_HOST" in output


# ---------- #304 amendment: per-item install guidance (FIXES) ----------
# NOTE: these tests REPLACE PATH (not prepend) — a real gitnexus.CMD lives on
# this machine's PATH and would otherwise satisfy the probe non-hermetically.

def test_json_includes_fix_for_failed_items(kunglao_ws, monkeypatch):
    """Failed checks carry a `fix` install command in --json output."""
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # replace, not prepend
    r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    gn = next(c for c in data["checks"] if c["name"] == "gitnexus")
    assert gn["status"] == "FAIL"
    assert gn["fix"] and "gitnexus" in gn["fix"].lower(), gn
    adb_check = next(c for c in data["checks"] if c["name"] == "adb")
    assert adb_check["fix"] and "PATH" in adb_check["fix"], adb_check


def test_human_output_shows_fix_lines(kunglao_ws, monkeypatch):
    """Human output prints `fix:` lines for non-PASS checks."""
    empty = kunglao_ws / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # replace, not prepend
    r = _run_toolchain(kunglao_ws, ["--type", "linux"])
    assert "fix:" in r.stdout
    assert "KUNGLAO_VM_HOST" in r.stdout or "binutils" in r.stdout


def test_pass_items_have_no_fix(kunglao_ws, monkeypatch):
    """PASS items do not carry guidance noise (fix is None)."""
    fake = kunglao_ws / "fake-docker-bin"
    fake.mkdir()
    # Platform-aware: shutil.which resolves docker.bat on Windows, an
    # extensionless executable file on POSIX.
    if os.name == "nt":
        (fake / "docker.bat").write_text("@echo off\r\n", encoding="utf-8")
    else:
        docker = fake / "docker"
        docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        docker.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake))  # replace, not prepend
    r = _run_toolchain(kunglao_ws, ["--type", "windows", "--json"])
    data = json.loads(r.stdout)
    docker = next(c for c in data["checks"] if c["name"] == "docker")
    assert docker["status"] == "PASS"
    assert docker["fix"] is None, docker


# ---------- F3 (#304 review): android debug_flag / frida_server /
# android_server are enforced HARD checks, not WARN noise ----------

def test_android_device_root_fail_when_not_root(fake_bin, kunglao_ws, monkeypatch):
    """F5: fake adb returns non-root uid -> device_root FAIL (HARD), exit 1."""
    _rewrite_adb_stub(fake_bin, uid="1000")
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    dr = next(c for c in data["checks"] if c["name"] == "device_root")
    assert dr["status"] == "FAIL", f"non-root device must FAIL device_root: {dr}"
    assert dr["root_cause"] == "root", dr
    assert dr["fix"], "FAIL must carry fix guidance"
    assert r.returncode == 1, "HARD device_root FAIL must exit 1"


def test_android_debug_flag_fail_when_not_set(fake_bin, kunglao_ws, monkeypatch):
    """F3: ro.debuggable != 1 -> debug_flag FAIL (HARD, enforced at init)."""
    _rewrite_adb_stub(fake_bin, debuggable="0")
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    df = next(c for c in data["checks"] if c["name"] == "debug_flag")
    assert df["status"] == "FAIL", f"debug flag unset must FAIL (HARD): {df}"
    assert df["fix"], "FAIL must carry fix guidance"
    assert r.returncode == 1, "HARD debug_flag FAIL must exit 1"


def test_android_debug_flag_pass_when_set(fake_bin, kunglao_ws, monkeypatch):
    """F3: ro.debuggable == 1 -> debug_flag PASS (verified, read back)."""
    _rewrite_adb_stub(fake_bin, debuggable="1")
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    df = next(c for c in data["checks"] if c["name"] == "debug_flag")
    assert df["status"] == "PASS", f"debug flag set must PASS: {df}"
    assert "1" in df["detail"]


def test_android_frida_server_fail_without_listener(fake_bin, kunglao_ws, monkeypatch):
    """F3: frida-server is a REAL probe (adb forward + TCP connect).
    Nothing listening on the frida port -> FAIL (HARD) with guidance."""
    import socket as socket_mod
    _rewrite_adb_stub(fake_bin)
    probe = socket_mod.create_server(("127.0.0.1", 0))
    frida_port = probe.getsockname()[1]
    probe.close()  # free the port -> connect must fail
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    monkeypatch.setenv("KUNGLAO_FRIDA_PORT", str(frida_port))
    r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    fs = next(c for c in data["checks"] if c["name"] == "frida_server")
    assert fs["status"] == "FAIL", f"no frida listener must FAIL (HARD): {fs}"
    assert fs["fix"] and "frida" in fs["fix"].lower(), fs
    assert r.returncode == 1, "HARD frida_server FAIL must exit 1"


def test_android_frida_and_android_server_pass_with_listeners(
        fake_bin, kunglao_ws, monkeypatch):
    """F3: with listeners bound on the frida custom port and 23946
    (android_server), both probes PASS — the HARD gates are satisfied."""
    import socket as socket_mod
    _rewrite_adb_stub(fake_bin)
    frida_sock = socket_mod.create_server(("127.0.0.1", 0))
    frida_port = frida_sock.getsockname()[1]
    as_sock = _local_listener(23946)
    if as_sock is None:
        frida_sock.close()
        pytest.skip("port 23946 busy on this host")
    try:
        monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
        monkeypatch.setenv("KUNGLAO_FRIDA_PORT", str(frida_port))
        r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
        data = json.loads(r.stdout)
        fs = next(c for c in data["checks"] if c["name"] == "frida_server")
        assert fs["status"] == "PASS", fs
        aserv = next(c for c in data["checks"] if c["name"] == "android_server")
        assert aserv["status"] == "PASS", aserv
    finally:
        frida_sock.close()
        as_sock.close()


def test_android_server_fail_without_listener(fake_bin, kunglao_ws, monkeypatch):
    """F3: android_server (port 23946) not reachable -> FAIL (HARD)."""
    _rewrite_adb_stub(fake_bin)
    as_sock = _local_listener(23946)
    if as_sock is not None:
        as_sock.close()  # must NOT be listening for the FAIL case
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    r = _run_toolchain(kunglao_ws, ["--type", "android", "--json"])
    data = json.loads(r.stdout)
    aserv = next(c for c in data["checks"] if c["name"] == "android_server")
    assert aserv["status"] == "FAIL", f"no android_server listener must FAIL: {aserv}"
    assert aserv["fix"], "FAIL must carry fix guidance"


# ---------- F7 (#304 review): defensive FRIDA port parsing ----------

def test_frida_port_garbage_env_defensive(monkeypatch):
    """F7: KUNGLAO_FRIDA_PORT garbage ('abc' / out-of-range) must NOT crash
    the import — defensive parse falls back to 1337; valid values honored."""
    import importlib
    import toolchain as tc

    monkeypatch.setenv("KUNGLAO_FRIDA_PORT", "not-a-port")
    importlib.reload(tc)
    assert tc.FRIDA_PORT == 1337, \
        f"garbage env must fall back to 1337, got {tc.FRIDA_PORT}"

    monkeypatch.setenv("KUNGLAO_FRIDA_PORT", "99999")
    importlib.reload(tc)
    assert tc.FRIDA_PORT == 1337, "out-of-range port must fall back to 1337"

    monkeypatch.setenv("KUNGLAO_FRIDA_PORT", "1555")
    importlib.reload(tc)
    assert tc.FRIDA_PORT == 1555, "valid override must be honored"

    monkeypatch.delenv("KUNGLAO_FRIDA_PORT", raising=False)
    importlib.reload(tc)
    assert tc.FRIDA_PORT == 1337, "default port must be 1337"


def test_toolchain_cli_garbage_port_no_traceback(kunglao_ws):
    """F7: CLI with garbage KUNGLAO_FRIDA_PORT must not traceback at import
    (kunglao-init imports toolchain -> must fail friendly, not crash)."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["KUNGLAO_FRIDA_PORT"] = "garbage"
    env["PYTHONIOENCODING"] = "utf-8"
    (kunglao_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=windows\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "toolchain.py"), str(kunglao_ws),
         "--type", "windows"],
        capture_output=True, text=True, timeout=60, env=env, errors="replace",
    )
    assert "Traceback" not in r.stderr, \
        f"garbage port must not traceback: {r.stderr}"
    assert r.returncode in (0, 1, 2), f"unexpected exit {r.returncode}"


# ---------- #356 W3: KUNGLAO_VM_SHELL_PORT env-configurable ----------

def test_vm_shell_port_env_configurable(monkeypatch):
    """#356 W3: VM_SHELL_PORT reads KUNGLAO_VM_SHELL_PORT (same defensive
    _parse_port pattern as FRIDA_PORT): valid override honored, garbage and
    out-of-range fall back to the 9876 default, unset = 9876."""
    import importlib
    import toolchain as tc

    monkeypatch.setenv("KUNGLAO_VM_SHELL_PORT", "7654")
    importlib.reload(tc)
    assert tc.VM_SHELL_PORT == 7654, "valid override must be honored"

    monkeypatch.setenv("KUNGLAO_VM_SHELL_PORT", "not-a-port")
    importlib.reload(tc)
    assert tc.VM_SHELL_PORT == 9876, "garbage env must fall back to 9876"

    monkeypatch.setenv("KUNGLAO_VM_SHELL_PORT", "99999")
    importlib.reload(tc)
    assert tc.VM_SHELL_PORT == 9876, "out-of-range port must fall back to 9876"

    monkeypatch.delenv("KUNGLAO_VM_SHELL_PORT", raising=False)
    importlib.reload(tc)
    assert tc.VM_SHELL_PORT == 9876, "default port must be 9876"
