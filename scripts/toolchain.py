#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolchain.py — type-aware toolchain probe matrix (#304).

Per-type manifests (windows/linux/android), tiers 0-3 (HARD/HARD/HARD/WARN).
Real probes (subprocess with timeouts, fail-open on probe crash but honest
reporting). Dependency-cascade error messages that name the ROOT CAUSE.

CLI: toolchain.py <workspace> [--type t] [--json] [--reproduce]
Exit codes: 0 = all PASS, 1 = any HARD FAIL, 2 = only WARN failures.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# UTF-8 stdout unification (same pattern as tools/static/common.py (ex-_common.py, merged #340))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

SKILL_DIR = _SCRIPT_DIR.parent

# #316: MCP supply probe (registry: ~/.claude.json + workspace .mcp.json).
# Single manifest source: scripts/mcp_probe.py MANIFEST — shared with the
# kunglao-init .mcp.json scaffold and the CLAUDE.md/README doc tables.
import mcp_probe  # noqa: E402  (same dir, sys.path injected above)

VALID_TYPES = ("windows", "linux", "android")

# F6 (#304 review): single source of truth for the init predicate component.
from init_state import read_project_type  # noqa: E402

# #304: frida custom port convention — config-driven, default 1337
# (frida-server renamed + non-default port to evade sample detection).
# F7: defensive parse — garbage / out-of-range env values fall back to the
# default instead of crashing the import (kunglao-init imports this module).
def _parse_port(raw: str | None, default: int) -> int:
    """Defensive port parse: int(raw) in [1, 65535], else default."""
    try:
        value = int((raw or "").strip() or str(default))
    except ValueError:
        return default
    return value if 1 <= value <= 65535 else default


FRIDA_PORT = _parse_port(os.environ.get("KUNGLAO_FRIDA_PORT"), 1337)
VM_SHELL_PORT = 9876
ANDROID_SERVER_PORT = 23946  # IDA android_server default listener port

# #304 amendment (comment 304-5289955958): per-item friendly install commands.
# kunglao-init prints these on HARD refusal so the HUMAN knows exactly what to
# install — init does NOT silently repair. Keyed by check item name.
FIXES: dict[str, str] = {
    "pefile": "pip install pefile",
    "die": "install DIE (Detect It Easy) and add it to PATH",
    "floss": "pip install flare-floss (or add floss to PATH)",
    "file": "install binutils (file) and add to PATH",
    "readelf": "install binutils (readelf) and add to PATH",
    "objdump": "install binutils (objdump) and add to PATH",
    "decompiler": "set GHIDRA_HOME=<Ghidra install root> (support/analyzeHeadless.bat must exist) or install IDA",
    "ghidra": "set GHIDRA_HOME=<Ghidra install root> (support/analyzeHeadless.bat must exist)",
    "ida": "install IDA and add idat64 to PATH",
    "vm_reachable": "set KUNGLAO_VM_HOST=<live VM lease IP> (vmr-shell discovery) and ensure ports are open",
    "remote_debugger": "fix the root cause first: make the VM reachable (set KUNGLAO_VM_HOST), then deploy the remote debugger on the VM",
    "aapt": "install Android SDK build-tools (aapt/aapt2) and add to PATH (or install unzip as a substitute)",
    "jadx": "install jadx and add it to PATH",
    "apktool": "install apktool and add it to PATH",
    "gitnexus": "npm i -g gitnexus (or install per GitNexus docs); verify `gitnexus --version`",
    "adb": "install Android SDK platform-tools and add adb to PATH; attach a device (`adb devices` must be non-empty)",
    "device_root": "root the device: `adb root` (emulator) or su via Magisk; verify `adb shell su -c id` returns uid=0",
    "debug_flag": "set the debug flag: `adb shell am set-debug-app -w <pkg>` or `adb shell setprop ro.debuggable 1`; verified at init via `adb shell getprop ro.debuggable` (must read back 1)",
    "frida_server": "fix the root cause first (ADB); then deploy a RENAMED frida-server binary on custom port "
                    f"{FRIDA_PORT} and verify at init via `adb forward tcp:{FRIDA_PORT} tcp:{FRIDA_PORT}` + TCP connect "
                    "(default name/port 27042 is detected by samples)",
    "android_server": "fix the root cause first (ADB); then adb push android_server to the device and run it; "
                      f"verified at init via `adb forward tcp:{ANDROID_SERVER_PORT} tcp:{ANDROID_SERVER_PORT}` + TCP connect",
}

# #316: registration guidance for MCP supply checks — fix text rendered by the
# formatters like every other FIXES entry (keyed by report item name mcp:<name>).
FIXES.update({f"mcp:{i.name}": i.register for i in mcp_probe.MANIFEST})


class Tier(Enum):
    """Check severity: HARD blocks analysis, WARN is informational."""
    HARD = "HARD"
    WARN = "WARN"


class Status(Enum):
    """Check result status."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class CheckResult:
    """Single toolchain check result."""
    name: str
    status: Status
    tier: Tier
    detail: str
    root_cause: str | None = None


@dataclass
class ToolchainReport:
    """Full toolchain check report."""
    project_type: str
    items: list[CheckResult] = field(default_factory=list)

    @property
    def overall_status(self) -> Status:
        hard_fail = any(
            i.status == Status.FAIL and i.tier == Tier.HARD for i in self.items
        )
        any_warn = any(
            i.status in (Status.WARN, Status.FAIL) and i.tier == Tier.WARN
            for i in self.items
        )
        if hard_fail:
            return Status.FAIL
        if any_warn:
            return Status.WARN
        return Status.PASS

    @property
    def exit_code(self) -> int:
        s = self.overall_status
        if s == Status.FAIL:
            return 1
        if s == Status.WARN:
            return 2
        return 0


# ---------- probe helpers ----------

def _shutil_which(name: str) -> str | None:
    """PATH lookup for a command."""
    return shutil.which(name)


def _run_cmd(args: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run a command with timeout; returns (rc, stdout, stderr).
    Fail-open on crash: return (1, "", str(exc)).
    Windows: .bat/.cmd executables must go through cmd /c (CreateProcess
    cannot pass args to a batch file directly)."""
    run_args = args
    if os.name == "nt" and args and args[0].lower().endswith((".bat", ".cmd")):
        run_args = ["cmd", "/c", *args]
    try:
        r = subprocess.run(
            run_args, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as exc:
        return 1, "", str(exc)


def _tcp_connect(host: str, port: int, timeout: int = 2) -> tuple[bool, str]:
    """TCP connection probe; returns (ok, error_detail)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except OSError as exc:
        return False, f"{port}: {exc}"


def _env_get(name: str) -> str | None:
    return os.environ.get(name)


def _file_exists(path: Path | None) -> bool:
    return path is not None and path.exists()


def _probe_native_so(ws: Path) -> bool:
    """True if the sample under bins/ contains native .so code:
    a .so file, or a zip (APK) whose first 4KB references lib/ (native dir)."""
    bins = ws / "bins"
    if not bins.is_dir():
        return False
    for p in sorted(bins.iterdir()):
        if not p.is_file():
            continue
        if p.name.endswith(".so"):
            return True
        try:
            head = p.read_bytes()[:4096]
        except OSError:
            continue
        if b"lib/" in head or b".so" in head:
            return True
    return False


def _adb_forward_probe(adb: str, port: int, timeout: int = 2) -> tuple[bool, str]:
    """Device-side service probe via adb forward + host TCP connect (#304 F3).

    `adb forward tcp:<port> tcp:<port>` then TCP-connect localhost:<port>.
    adb's host listener accepts even when the device-side port is closed, so
    a bare connect would false-PASS — after connecting we recv(1):
      - connection closed immediately (b"") -> device-side service absent
      - data received or connection held open (timeout) -> service present
    Returns (ok, detail).
    """
    rc, out, err = _run_cmd([adb, "forward", f"tcp:{port}", f"tcp:{port}"],
                            timeout=10)
    if rc != 0:
        return False, f"adb forward failed: {err or out[:80]}"
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    except socket.timeout:
        # Connect-phase timeout: nothing accepted the SYN (sandboxed hosts may
        # drop instead of RST) -> not reachable.
        return False, f"port {port}: connect timed out — service not reachable"
    except OSError as exc:
        return False, f"port {port}: {exc}"
    with s:
        s.settimeout(timeout)
        try:
            data = s.recv(1)
        except socket.timeout:
            # Service accepted and held the connection open (no data yet) — present.
            return True, f"listening on device port {port} (via adb forward)"
        if data == b"":
            return False, (
                f"connection closed by device on port {port} — "
                f"service not listening"
            )
        return True, f"listening on device port {port} (via adb forward)"


# ---------- MCP supply (#316) ----------

def _check_mcp(report: ToolchainReport, ws: Path, project_type: str) -> None:
    """Append MCP supply checks (probe ~/.claude.json + workspace .mcp.json).

    Manifest + probe live in mcp_probe.py — single source of truth shared
    with the kunglao-init .mcp.json scaffold and the doc tables.
    """
    for mc in mcp_probe.check_mcp(ws, project_type):
        report.items.append(CheckResult(
            name=f"mcp:{mc.name}",
            status={"PASS": Status.PASS, "FAIL": Status.FAIL,
                    "WARN": Status.WARN}[mc.status],
            tier=Tier.HARD if mc.tier == "HARD" else Tier.WARN,
            detail=mc.detail,
        ))


# ---------- Windows manifest ----------

def _check_windows(report: ToolchainReport, ws: Path) -> None:
    """Windows toolchain checks (PE32+ x86-64)."""
    # T0: venv + pefile / DIE / floss
    for tool in ("pefile", "die", "floss"):
        # Try import-based check for pefile (Python package)
        if tool == "pefile":
            r = _run_cmd([sys.executable, "-c", "import pefile"], timeout=10)
            if r[0] == 0:
                report.items.append(CheckResult(
                    name="pefile", status=Status.PASS, tier=Tier.HARD,
                    detail="pefile importable"
                ))
            else:
                report.items.append(CheckResult(
                    name="pefile", status=Status.FAIL, tier=Tier.HARD,
                    detail=f"pefile not importable: {r[2][:100]}",
                ))
            continue
        path = _shutil_which(tool)
        if path:
            report.items.append(CheckResult(
                name=tool, status=Status.PASS, tier=Tier.HARD,
                detail=f"found at {path}",
            ))
        else:
            report.items.append(CheckResult(
                name=tool, status=Status.FAIL, tier=Tier.HARD,
                detail=f"{tool} not found in PATH",
            ))

    # T1: Ghidra or IDA
    ghidra_home = _env_get("GHIDRA_HOME")
    ah = Path(ghidra_home) / "support" / "analyzeHeadless.bat" if ghidra_home else None
    ida = _shutil_which("idat64")
    if _file_exists(ah):
        report.items.append(CheckResult(
            name="ghidra", status=Status.PASS, tier=Tier.HARD,
            detail=f"analyzeHeadless at {ah}",
        ))
    elif ida:
        report.items.append(CheckResult(
            name="ida", status=Status.PASS, tier=Tier.HARD,
            detail=f"idat64 at {ida}",
        ))
    else:
        report.items.append(CheckResult(
            name="decompiler", status=Status.FAIL, tier=Tier.HARD,
            detail="No decompiler found (need Ghidra or IDA)",
        ))

    # T2: VM reachability (vmr-shell 9876 + frida custom port, default 1337)
    vm_host = _env_get("KUNGLAO_VM_HOST")
    if not vm_host:
        vm_ok, vm_err = False, "KUNGLAO_VM_HOST unset"
    else:
        vm_ok_9876, err_9876 = _tcp_connect(vm_host, VM_SHELL_PORT)
        vm_ok_frida, err_frida = _tcp_connect(vm_host, FRIDA_PORT)
        vm_ok = vm_ok_9876 and vm_ok_frida
        vm_err = "; ".join(e for e in (err_9876, err_frida) if e)
    if vm_ok:
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.PASS, tier=Tier.HARD,
            detail=f"VM {vm_host} reachable on {VM_SHELL_PORT}+{FRIDA_PORT}",
        ))
    else:
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.FAIL, tier=Tier.HARD,
            detail=f"VM unreachable: {vm_err}",
            root_cause="VM",
        ))

    # T2: Remote debugger (x64dbg/ida_server/frida-server) — cascade from VM
    if not vm_ok:
        report.items.append(CheckResult(
            name="remote_debugger", status=Status.FAIL, tier=Tier.HARD,
            detail="Remote debugger unreachable (VM not reachable)",
            root_cause="VM",
        ))
    else:
        # Would need actual VM-side probing — mark as WARN if can't verify
        report.items.append(CheckResult(
            name="remote_debugger", status=Status.WARN, tier=Tier.HARD,
            detail="VM reachable; remote debugger presence not verified",
        ))

    # T2: Docker (WARN)
    docker = _shutil_which("docker")
    if docker:
        report.items.append(CheckResult(
            name="docker", status=Status.PASS, tier=Tier.WARN,
            detail=f"docker at {docker}",
        ))
    else:
        report.items.append(CheckResult(
            name="docker", status=Status.WARN, tier=Tier.WARN,
            detail="docker not found (optional)",
        ))

    # #316: MCP supply (registry: ~/.claude.json + workspace .mcp.json)
    _check_mcp(report, ws, "windows")


# ---------- Linux manifest ----------

def _check_linux(report: ToolchainReport, ws: Path) -> None:
    """Linux toolchain checks (ELF)."""
    # T0: venv + binutils (file/readelf/objdump)
    for tool in ("file", "readelf", "objdump"):
        path = _shutil_which(tool)
        if path:
            report.items.append(CheckResult(
                name=tool, status=Status.PASS, tier=Tier.HARD,
                detail=f"found at {path}",
            ))
        else:
            report.items.append(CheckResult(
                name=tool, status=Status.FAIL, tier=Tier.HARD,
                detail=f"{tool} not found in PATH",
            ))

    # T1: Ghidra or IDA
    ghidra_home = _env_get("GHIDRA_HOME")
    ah = Path(ghidra_home) / "support" / "analyzeHeadless.bat" if ghidra_home else None
    ida = _shutil_which("idat64")
    if _file_exists(ah):
        report.items.append(CheckResult(
            name="ghidra", status=Status.PASS, tier=Tier.HARD,
            detail=f"analyzeHeadless at {ah}",
        ))
    elif ida:
        report.items.append(CheckResult(
            name="ida", status=Status.PASS, tier=Tier.HARD,
            detail=f"idat64 at {ida}",
        ))
    else:
        report.items.append(CheckResult(
            name="decompiler", status=Status.FAIL, tier=Tier.HARD,
            detail="No decompiler found (need Ghidra or IDA)",
        ))

    # T2: VM reachability (vmr-shell 9876 + frida custom port, default 1337)
    vm_host = _env_get("KUNGLAO_VM_HOST")
    if not vm_host:
        vm_ok, vm_err = False, "KUNGLAO_VM_HOST unset"
    else:
        vm_ok_9876, err_9876 = _tcp_connect(vm_host, VM_SHELL_PORT)
        vm_ok_frida, err_frida = _tcp_connect(vm_host, FRIDA_PORT)
        vm_ok = vm_ok_9876 and vm_ok_frida
        vm_err = "; ".join(e for e in (err_9876, err_frida) if e)
    if vm_ok:
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.PASS, tier=Tier.HARD,
            detail=f"VM {vm_host} reachable on {VM_SHELL_PORT}+{FRIDA_PORT}",
        ))
    else:
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.FAIL, tier=Tier.HARD,
            detail=f"VM unreachable: {vm_err}",
            root_cause="VM",
        ))

    # T2: debugger (gdbserver/linux_server64/frida-server) — cascade from VM
    if not vm_ok:
        report.items.append(CheckResult(
            name="remote_debugger", status=Status.FAIL, tier=Tier.HARD,
            detail="Remote debugger unreachable (VM not reachable)",
            root_cause="VM",
        ))
    else:
        report.items.append(CheckResult(
            name="remote_debugger", status=Status.WARN, tier=Tier.HARD,
            detail="VM reachable; remote debugger presence not verified",
        ))

    # T2: Docker (WARN)
    docker = _shutil_which("docker")
    if docker:
        report.items.append(CheckResult(
            name="docker", status=Status.PASS, tier=Tier.WARN,
            detail=f"docker at {docker}",
        ))
    else:
        report.items.append(CheckResult(
            name="docker", status=Status.WARN, tier=Tier.WARN,
            detail="docker not found (optional)",
        ))

    # #316: MCP supply (registry: ~/.claude.json + workspace .mcp.json)
    _check_mcp(report, ws, "linux")

    # T2: remote debugger gdbserver (host-side PATH lookup; the VM-side
    # binary is beyond host reach — verified via the VM channel)
    gdbserver = _shutil_which("gdbserver")
    if gdbserver:
        report.items.append(CheckResult(
            name="gdbserver", status=Status.PASS, tier=Tier.WARN,
            detail=f"gdbserver on host PATH at {gdbserver}",
        ))
    else:
        report.items.append(CheckResult(
            name="gdbserver", status=Status.WARN, tier=Tier.WARN,
            detail="gdbserver not on host PATH (VM-side binary verified via VM channel)",
        ))

    # T2: eBPF (WARN — kernel > 6). The gate is the TARGET (VM) kernel, not
    # the analysis host — a Windows host cannot know the VM kernel version.
    if sys.platform == "win32":
        report.items.append(CheckResult(
            name="ebpf", status=Status.WARN, tier=Tier.WARN,
            detail="host is not Linux — target VM kernel not probeable from host "
                   "(eBPF unavailable is not blocking, WARN tier)",
        ))
    else:
        uname_r = _run_cmd(["uname", "-r"], timeout=5)
        kernel_ver = uname_r[1].strip() if uname_r[0] == 0 else ""
        major = 0
        m = re.match(r"(\d+)\.", kernel_ver)
        if m:
            major = int(m.group(1))
        if major >= 6:
            report.items.append(CheckResult(
                name="ebpf", status=Status.PASS, tier=Tier.WARN,
                detail=f"kernel {kernel_ver} >= 6.0 — eBPF available",
            ))
        else:
            report.items.append(CheckResult(
                name="ebpf", status=Status.WARN, tier=Tier.WARN,
                detail=f"kernel {kernel_ver or 'unknown'} < 6.0 — eBPF unavailable (not blocking)",
            ))

    # T3: strace/ltrace (WARN)
    for tool in ("strace", "ltrace"):
        path = _shutil_which(tool)
        report.items.append(CheckResult(
            name=tool, status=Status.PASS if path else Status.WARN,
            tier=Tier.WARN,
            detail=f"found at {path}" if path else f"{tool} not found (optional)",
        ))


# ---------- Android manifest ----------

def _check_android(report: ToolchainReport, ws: Path) -> None:
    """Android toolchain checks (APK/DEX/SO)."""
    # T0: venv + aapt/aapt2 (or unzip substitute)
    aapt_found = None
    for tool in ("aapt", "aapt2"):
        path = _shutil_which(tool)
        if path:
            aapt_found = tool
            report.items.append(CheckResult(
                name=tool, status=Status.PASS, tier=Tier.HARD,
                detail=f"found at {path}",
            ))
            break
    if aapt_found is None:
        unzip = _shutil_which("unzip")
        if unzip:
            report.items.append(CheckResult(
                name="aapt", status=Status.WARN, tier=Tier.HARD,
                detail=f"aapt/aapt2 not found — unzip at {unzip} may substitute for APK unpacking",
            ))
        else:
            report.items.append(CheckResult(
                name="aapt", status=Status.FAIL, tier=Tier.HARD,
                detail="aapt/aapt2 not found and no unzip substitute — APK unpacking unavailable",
            ))

    # T1: jadx + apktool
    for tool in ("jadx", "apktool"):
        path = _shutil_which(tool)
        if path:
            report.items.append(CheckResult(
                name=tool, status=Status.PASS, tier=Tier.HARD,
                detail=f"found at {path}",
            ))
        else:
            report.items.append(CheckResult(
                name=tool, status=Status.FAIL, tier=Tier.HARD,
                detail=f"{tool} not found in PATH",
            ))

    # T1: GitNexus (real probe: gitnexus --version)
    gn_path = _shutil_which("gitnexus")
    if gn_path:
        rc, out, err = _run_cmd([gn_path, "--version"], timeout=15)
        if rc == 0 and out:
            report.items.append(CheckResult(
                name="gitnexus", status=Status.PASS, tier=Tier.HARD,
                detail=f"gitnexus --version OK: {out[:80]}",
            ))
        else:
            report.items.append(CheckResult(
                name="gitnexus", status=Status.FAIL, tier=Tier.HARD,
                detail=f"gitnexus at {gn_path} but --version probe failed"
                       f" ({err or out[:60]}) — post-decompile graph building requires it",
            ))
    else:
        report.items.append(CheckResult(
            name="gitnexus", status=Status.FAIL, tier=Tier.HARD,
            detail="gitnexus not found — post-decompile graph building requires it",
        ))

    # T1: Ghidra or IDA (native .so decompilation; tier depends on sample)
    ghidra_home = _env_get("GHIDRA_HOME")
    ah = Path(ghidra_home) / "support" / "analyzeHeadless.bat" if ghidra_home else None
    ida = _shutil_which("idat64")
    has_native = _probe_native_so(ws)
    if _file_exists(ah):
        report.items.append(CheckResult(
            name="ghidra", status=Status.PASS, tier=Tier.HARD,
            detail=f"analyzeHeadless at {ah}",
        ))
    elif ida:
        report.items.append(CheckResult(
            name="ida", status=Status.PASS, tier=Tier.HARD,
            detail=f"idat64 at {ida}",
        ))
    elif has_native:
        report.items.append(CheckResult(
            name="decompiler", status=Status.FAIL, tier=Tier.HARD,
            detail="Sample has native .so — decompiler (Ghidra or IDA) REQUIRED for native code",
        ))
    else:
        report.items.append(CheckResult(
            name="decompiler", status=Status.WARN, tier=Tier.HARD,
            detail="No decompiler found — WARN for pure-DEX samples; HARD if sample has .so",
        ))

    # T2: ADB (root dependency)
    adb = _shutil_which("adb")
    adb_ok = False
    if adb:
        # Check adb devices
        rc, out, err = _run_cmd([adb, "devices"], timeout=10)
        devices = [l.strip() for l in out.splitlines() if "\tdevice" in l]
        if devices:
            adb_ok = True
            report.items.append(CheckResult(
                name="adb", status=Status.PASS, tier=Tier.HARD,
                detail=f"adb found, devices: {', '.join(devices)}",
            ))
        else:
            report.items.append(CheckResult(
                name="adb", status=Status.FAIL, tier=Tier.HARD,
                detail="adb found but no devices attached",
                root_cause="ADB",
            ))
    else:
        report.items.append(CheckResult(
            name="adb", status=Status.FAIL, tier=Tier.HARD,
            detail="adb not found in PATH — Android device bridge unavailable",
            root_cause="ADB",
        ))

    # T2: device root (cascades from ADB)
    if not adb_ok:
        report.items.append(CheckResult(
            name="device_root", status=Status.FAIL, tier=Tier.HARD,
            detail="Cannot check root — ADB unavailable",
            root_cause="ADB",
        ))
    else:
        # Try adb shell su -c id
        assert adb  # noqa: S101 — adb is set when adb_ok is True
        rc, out, err = _run_cmd([adb, "shell", "su", "-c", "id"], timeout=10)
        if rc == 0 and "uid=0" in out:
            report.items.append(CheckResult(
                name="device_root", status=Status.PASS, tier=Tier.HARD,
                detail=f"device rooted: {out}",
            ))
        else:
            report.items.append(CheckResult(
                name="device_root", status=Status.FAIL, tier=Tier.HARD,
                detail=f"Device not rooted or su unavailable: {err or out[:100]}",
                root_cause="root",
            ))

    # T2: debug flag (HARD, enforced — #304 F3): verified by reading back
    # ro.debuggable == 1. "Must be set" is a user design requirement, so an
    # unset flag FAILs init instead of silently warning.
    if not adb_ok:
        report.items.append(CheckResult(
            name="debug_flag", status=Status.FAIL, tier=Tier.HARD,
            detail="Cannot check debug flag — ADB unavailable",
            root_cause="ADB",
        ))
    else:
        assert adb  # noqa: S101 — adb is set when adb_ok is True
        rc, out, err = _run_cmd([adb, "shell", "getprop", "ro.debuggable"],
                                timeout=10)
        debuggable = out.strip() if rc == 0 else ""
        if debuggable == "1":
            report.items.append(CheckResult(
                name="debug_flag", status=Status.PASS, tier=Tier.HARD,
                detail="ro.debuggable=1 — debug flag set (read back verified)",
            ))
        else:
            report.items.append(CheckResult(
                name="debug_flag", status=Status.FAIL, tier=Tier.HARD,
                detail=f"debug flag not set (ro.debuggable={debuggable or 'unreadable'}; "
                       f"{err or out[:60]}) — required for Android dynamic analysis",
                root_cause="debug_flag",
            ))

    # T2: frida-server (renamed + custom port, convention 1337) — HARD, enforced
    # (#304 F3): real probe via adb forward + TCP connect; a renamed binary is
    # verified by PORT reachability (name irrelevant to the sample).
    if not adb_ok:
        report.items.append(CheckResult(
            name="frida_server", status=Status.FAIL, tier=Tier.HARD,
            detail="Cannot verify frida-server — ADB unavailable",
            root_cause="ADB",
        ))
    else:
        assert adb  # noqa: S101 — adb is set when adb_ok is True
        ok, detail = _adb_forward_probe(adb, FRIDA_PORT)
        if ok:
            report.items.append(CheckResult(
                name="frida_server", status=Status.PASS, tier=Tier.HARD,
                detail=f"frida-server reachable on custom port {FRIDA_PORT} "
                       f"(renamed binary verified by port)",
            ))
        else:
            report.items.append(CheckResult(
                name="frida_server", status=Status.FAIL, tier=Tier.HARD,
                detail=f"frida-server NOT verified on custom port {FRIDA_PORT}: {detail} — "
                       f"must run a RENAMED binary on the custom port "
                       f"(default name/port 27042 is detected by samples)",
                root_cause="frida_server",
            ))

    # T2: android_server — HARD, enforced (#304 F3): real probe via adb forward
    # + TCP connect on the IDA android_server listener port.
    if not adb_ok:
        report.items.append(CheckResult(
            name="android_server", status=Status.FAIL, tier=Tier.HARD,
            detail="Cannot verify android_server — ADB unavailable",
            root_cause="ADB",
        ))
    else:
        assert adb  # noqa: S101 — adb is set when adb_ok is True
        ok, detail = _adb_forward_probe(adb, ANDROID_SERVER_PORT)
        if ok:
            report.items.append(CheckResult(
                name="android_server", status=Status.PASS, tier=Tier.HARD,
                detail=f"android_server listening on device port {ANDROID_SERVER_PORT} "
                       f"(via adb forward)",
            ))
        else:
            report.items.append(CheckResult(
                name="android_server", status=Status.FAIL, tier=Tier.HARD,
                detail=f"android_server NOT verified on port {ANDROID_SERVER_PORT}: {detail} — "
                       f"adb push android_server to the device and run it",
                root_cause="android_server",
            ))

    # T2: eBPF (SDK >= 31) — WARN gate
    if not adb_ok:
        report.items.append(CheckResult(
            name="ebpf_android", status=Status.WARN, tier=Tier.WARN,
            detail="Cannot check Android SDK version — ADB unavailable",
        ))
    else:
        rc, out, err = _run_cmd([adb, "shell", "getprop", "ro.build.version.sdk"],
                                timeout=10)
        sdk = 0
        m = re.match(r"\s*(\d+)", out)
        if rc == 0 and m:
            sdk = int(m.group(1))
        if sdk >= 31:
            report.items.append(CheckResult(
                name="ebpf_android", status=Status.PASS, tier=Tier.WARN,
                detail=f"Android SDK {sdk} >= 31 — eBPF available",
            ))
        else:
            report.items.append(CheckResult(
                name="ebpf_android", status=Status.WARN, tier=Tier.WARN,
                detail=f"Android SDK {sdk if sdk else 'unknown (probe failed: ' + (err or out)[:60] + ')'} "
                       f"< 31 — eBPF unavailable (Android 12+ required; not blocking)",
            ))

    # T3: unidbg (WARN)
    java = _shutil_which("java")
    report.items.append(CheckResult(
        name="unidbg", status=Status.WARN, tier=Tier.WARN,
        detail=f"java {'found' if java else 'not found'} — unidbg is optional fallback",
    ))

    # #316: MCP supply (registry: ~/.claude.json + workspace .mcp.json)
    _check_mcp(report, ws, "android")


# ---------- type resolution ----------
# F6 (#304 review): read_project_type imported from init_state.py above —
# single source of truth; no local duplicate.

# ---------- report formatting ----------

def format_human(report: ToolchainReport) -> str:
    """Format report as human-readable text."""
    lines = [f"toolchain check: type={report.project_type}"]
    for item in report.items:
        status_tag = item.status.value
        tier_tag = f"[{item.tier.value}]"
        line = f"  [{status_tag}] {tier_tag} {item.name}: {item.detail}"
        if item.root_cause:
            line += f" (root cause: {item.root_cause})"
        lines.append(line)
        if item.status != Status.PASS and item.name in FIXES:
            lines.append(f"      fix: {FIXES[item.name]}")
    lines.append(f"OVERALL: {report.overall_status.value}")
    return "\n".join(lines)


def format_json(report: ToolchainReport) -> str:
    """Format report as JSON."""
    data = {
        "project_type": report.project_type,
        "overall": report.overall_status.value,
        "checks": [
            {
                "name": i.name,
                "status": i.status.value,
                "tier": i.tier.value,
                "detail": i.detail,
                "root_cause": i.root_cause,
                "fix": FIXES.get(i.name) if i.status != Status.PASS else None,
            }
            for i in report.items
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def format_reproduce(report: ToolchainReport) -> str:
    """Format report for CI reproducibility."""
    parts = [f"type={report.project_type}", f"overall={report.overall_status.value}"]
    for i in report.items:
        parts.append(f"{i.name}={i.status.value}")
    return " ".join(parts)


# ---------- main ----------

def check(ws: Path, project_type: str | None = None) -> ToolchainReport:
    """Run type-aware toolchain checks."""
    if project_type is None:
        project_type = read_project_type(ws)
    if project_type not in VALID_TYPES:
        raise ValueError(
            f"Invalid project type: {project_type!r}. "
            f"Must be one of: {', '.join(VALID_TYPES)}. "
            f"Set --type or add project_type=<type> to analysis_state.txt."
        )
    report = ToolchainReport(project_type=project_type)
    checkers = {
        "windows": _check_windows,
        "linux": _check_linux,
        "android": _check_android,
    }
    checkers[project_type](report, ws)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="toolchain",
        description="Type-aware toolchain probe matrix (#304)",
    )
    parser.add_argument("workspace", help="workspace root path")
    parser.add_argument("--type", choices=VALID_TYPES, default=None,
                        help="project type (default: read from analysis_state.txt)")
    parser.add_argument("--json", action="store_true",
                        help="output as JSON")
    parser.add_argument("--reproduce", action="store_true",
                        help="machine-parseable output for CI")
    args = parser.parse_args(argv)

    ws = Path(args.workspace).resolve()
    try:
        report = check(ws, args.type)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(format_json(report))
    elif args.reproduce:
        print(format_reproduce(report))
    else:
        print(format_human(report))

    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
