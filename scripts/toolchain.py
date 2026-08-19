#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolchain.py — type-aware toolchain probe matrix (#304, #474 probe tiers).

Per-type manifests (windows/linux/android), tiers 0-3 (HARD/HARD/HARD/WARN).
Real probes (subprocess with timeouts, fail-open on probe crash but honest
reporting). Dependency-cascade error messages that name the ROOT CAUSE.
#474: every check carries a probe tier — PRESENCE (exists), LIVENESS
(side-effect-free handshake), CAPABILITY (trial run; opt-in only).
#449 needs-first: env = f(task_spec) — requirements_from_task_spec derives
the VM-channel requirement from a parsed task_spec (static-only:
constraints.dynamic_re=forbidden downgrades vm_reachable/remote_debugger
to WARN); absent/unreadable task_spec = conservative HARD, byte-identical
to the pre-#449 gate.

CLI: toolchain.py <workspace> [--type t] [--json] [--reproduce] [--capability]
     (consumes <workspace>/task_spec.yaml when present, #449)
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

# #409: platform-correct analyzeHeadless name (support/analyzeHeadless(.bat))
# + venv python location (Scripts/python.exe | bin/python) — single source.
import platform_paths  # noqa: E402  (same dir, sys.path injected above)

# #316: MCP supply probe (registry: ~/.claude.json + workspace .mcp.json).
# Single manifest source: scripts/mcp_probe.py MANIFEST — shared with the
# kunglao-init .mcp.json scaffold and the CLAUDE.md/README doc tables.
import mcp_probe  # noqa: E402  (same dir, sys.path injected above)

# #449 needs-first: task_spec loading for env = f(task_spec) — same YAML
# dependency kunglao-init already uses for the CLAUDE.md constraint block.
import yaml  # noqa: E402

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
# #356 W3: VM shell port env-configurable (was bare 9876 constant), same
# defensive parse as FRIDA_PORT — default unchanged.
VM_SHELL_PORT = _parse_port(os.environ.get("KUNGLAO_VM_SHELL_PORT"), 9876)
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
    "decompiler": "install a decompiler — follow the #408 installer (set GHIDRA_HOME=<Ghidra install root> with support/analyzeHeadless(.bat), or install IDA with idat64 on PATH, or register the ghidra/ida-pro-vm MCP via `claude mcp add`)",
    "ghidra": "set GHIDRA_HOME=<Ghidra install root> (support/analyzeHeadless must exist, platform-correct name #409)",
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
    "jdwp_debug": "optional capability (WARN): only needed when the task actually drives jdb. "
                  "To enable: ADB ok + ro.debuggable=1 + the target app running (`adb jdwp` lists "
                  "a pid); the probe forwards tcp:8700 -> jdwp:<pid> and exchanges the raw 14-byte "
                  "JDWP-Handshake (jdb stays the interactive driver; never jdb -attach — side effects)",
}

# #316: registration guidance for MCP supply checks — fix text rendered by the
# formatters like every other FIXES entry (keyed by report item name mcp:<name>).
FIXES.update({f"mcp:{i.name}": i.register for i in mcp_probe.MANIFEST})


class Tier(Enum):
    """Check severity: HARD blocks analysis, WARN is informational."""
    HARD = "HARD"
    WARN = "WARN"


# #474: probe capability tiers — HOW a check was verified, orthogonal to
# severity. A presence probe says the tool exists; liveness says a
# side-effect-free handshake succeeded; capability says a real trial run
# succeeded. The further down this ladder, the stronger the claim.
class ProbeTier(Enum):
    """How a check was verified (presence -> liveness -> capability)."""
    PRESENCE = "presence"      # file/registry lookup (~0ms)
    LIVENESS = "liveness"      # side-effect-free network handshake (seconds)
    CAPABILITY = "capability"  # real trial run of the tool (minutes)


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
    probe: ProbeTier = ProbeTier.PRESENCE  # #474: how it was verified


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
        except ConnectionResetError:
            # Peer sent RST during recv (e.g. stub listeners with backlog-only
            # sockets) — not a crash: report not reachable, don't kill the CLI.
            return False, f"connection reset on port {port} — service not reachable"
        if data == b"":
            return False, (
                f"connection closed by device on port {port} — "
                f"service not listening"
            )
        return True, f"listening on device port {port} (via adb forward)"


# ---------- #474: jdwp liveness handshake ----------

# The JDWP protocol opens with a raw 14-byte ASCII handshake: client sends
# "JDWP-Handshake", a live JDWP agent echoes the same 14 bytes back. This is
# side-effect-free (unlike `jdb -attach`, which resumes/holds the target VM)
# and proves a JDWP transport is actually answering — a bare TCP accept
# proves nothing (adb's forwarder accepts even for a dead device service).
JDWP_HANDSHAKE_BYTES = b"JDWP-Handshake"
# adb reserves 8700 for jdwp forwards by convention; the local side only
# needs to be a free port — 8700 keeps it recognizable in netstat output.
JDWP_LOCAL_PORT = 8700


def _jdwp_handshake(host: str, port: int, timeout: int = 2) -> tuple[bool, str]:
    """Raw JDWP handshake probe (#474, liveness tier).

    Send the 14-byte ASCII handshake, require the same 14 bytes echoed.
    Returns (ok, detail). Fail-open on any socket error (honest detail,
    never a crash) — same policy as _tcp_connect.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(JDWP_HANDSHAKE_BYTES)
            echo = b""
            while len(echo) < len(JDWP_HANDSHAKE_BYTES):
                chunk = s.recv(len(JDWP_HANDSHAKE_BYTES) - len(echo))
                if not chunk:
                    return False, f"{port}: closed during handshake (no JDWP agent)"
                echo += chunk
    except socket.timeout:
        return False, f"{port}: handshake timed out — no JDWP agent answering"
    except OSError as exc:
        return False, f"{port}: {exc}"
    if echo == JDWP_HANDSHAKE_BYTES:
        return True, f"JDWP handshake echoed on {port}"
    return False, f"{port}: handshake echo mismatch (got {echo!r})"


def _adb_jdwp_probe(adb: str, timeout: int = 2) -> tuple[bool, str]:
    """Device-side JDWP probe (#474, liveness tier).

    `adb jdwp` lists debuggable pids; forward tcp:8700 -> jdwp:<first pid>
    then run the raw 14-byte handshake (never `jdb -attach` — attach has
    side effects on the target). Returns (ok, detail).
    """
    rc, out, err = _run_cmd([adb, "jdwp"], timeout=10)
    if rc != 0:
        return False, f"adb jdwp failed: {err or out[:80]}"
    pid = next((l.strip() for l in out.splitlines() if l.strip()), "")
    if not pid or not pid.isdigit():
        return False, (
            "no debuggable pid listed by `adb jdwp` — a debuggable app "
            "process must be running (ro.debuggable=1 + the target app "
            "started, or `am set-debug-app -w <pkg>`)"
        )
    rc, out, err = _run_cmd(
        [adb, "forward", f"tcp:{JDWP_LOCAL_PORT}", f"jdwp:{pid}"], timeout=10)
    if rc != 0:
        return False, f"adb forward tcp:{JDWP_LOCAL_PORT} jdwp:{pid} failed: {err or out[:80]}"
    # Real adb echoes "<serial> tcp:<port> ..."; a port-bearing reply pins
    # the actual local listener (test stubs report their own port).
    local_port = JDWP_LOCAL_PORT
    m = re.search(r"(?:tcp:|:)(\d+)\s*$", out.strip())
    if m:
        local_port = int(m.group(1))
    ok, detail = _jdwp_handshake("127.0.0.1", local_port, timeout=timeout)
    return ok, (f"pid {pid}: {detail}" if not ok
                else f"JDWP agent pid {pid} alive — handshake echoed")


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
            # #474: registry read is presence evidence (no handshake)
            probe=ProbeTier.PRESENCE,
        ))


# ---------- #407/#474: MCP-first decompiler check (deduplicated, one helper) ----------

# Registry keys checked by mcp_probe.registered_names (user ~/.claude.json +
# workspace .mcp.json). A registered MCP decompiler is the PRIMARY signal;
# CLI (GHIDRA_HOME/analyzeHeadless, idat64 on PATH) is only a fallback.
_DECOMPILER_MCP_NAMES = ("ghidra", "ida-pro-vm")

# #474: a Python probe cannot reach into the MCP session (analysis tools
# register only after connect_instance succeeds — agents/ghidra-light.md),
# so the honest ceiling for registry + port evidence is WARN. Same for a
# present-but-untrialled CLI binary. PASS requires a capability trial, and
# trials run ONLY under the caps opt-in (init-only contract, minutes-long).
_UNVERIFIED = "capability unverified"


def _capability_probe_ghidra(ah: Path, timeout: int = 300) -> tuple[bool, str]:
    """CAPABILITY trial: analyzeHeadless imports a minimal synthetic ELF.

    Minutes-long (30s-2min real) — #474 contract: init-only / on-demand,
    never on the periodic path. Runs in a throwaway temp project dir; the
    synthetic payload is a 64-byte minimal ELF header (never a sample).
    Fail-open on any crash with the honest error (never raises).
    """
    import tempfile
    with tempfile.TemporaryDirectory(prefix="kgl-cap-") as tmp:
        sample = Path(tmp) / "cap_probe.elf"
        # minimal ELF64 header magic — analyzeHeadless accepts and analyzes it
        sample.write_bytes(b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 56)
        rc, out, err = _run_cmd(
            [str(ah), tmp, "cap_probe", "-import", str(sample),
             "-deleteProject"],
            timeout=timeout,
        )
    if rc == 0:
        return True, "capability trial: analyzeHeadless imported a minimal ELF"
    return False, f"capability trial failed: {(err or out)[:120]}"


def _check_decompiler(report: ToolchainReport, ws: Path,
                      has_native_so: bool | None = None,
                      caps: bool = False) -> None:
    """Append the decompiler availability check (#407 MCP-first, #474 honest).

    Three states, strongest evidence wins:
      - capability-PASS (caps=True only): analyzeHeadless trial import
        succeeded (CAPABILITY tier) — the only honest PASS.
      - liveness/presence-WARN: MCP registered (+ bridge port reachable) or
        CLI binary present — status WARN "capability unverified" (a probe
        cannot reach into the MCP session; presence is not capability).
      - FAIL: nothing registered/present (android pure-DEX keeps WARN).

    `has_native_so` encodes the android tier nuance: None (windows/linux)
    and True (android with native .so) -> HARD tier; False (android
    pure-DEX) -> the FAIL/WARN wording nuance stays as before.
    """
    registered = mcp_probe.registered_names(mcp_probe.claude_json_path(), ws)

    ghidra_home = _env_get("GHIDRA_HOME")
    ah = (platform_paths.analyze_headless(ghidra_home)
          if ghidra_home else None)
    ida = _shutil_which("idat64")

    # capability trial — only when explicitly requested and a CLI binary
    # exists to trial (MCP capability is unprovable from a Python probe).
    if caps and _file_exists(ah):
        ok, detail = _capability_probe_ghidra(ah)
        if ok:
            report.items.append(CheckResult(
                name="ghidra", status=Status.PASS, tier=Tier.HARD,
                detail=f"analyzeHeadless at {ah} — {detail}",
                probe=ProbeTier.CAPABILITY,
            ))
            return
        # trial ran and failed: report the FAIL honestly, fall through to
        # the WARN evidence lines below (presence still true, capability not).

    for name in _DECOMPILER_MCP_NAMES:
        if name in registered:
            report.items.append(CheckResult(
                name="decompiler", status=Status.WARN, tier=Tier.HARD,
                detail=f"via MCP ({name}) — registered, {_UNVERIFIED} "
                       f"(registry read only; a probe cannot reach the MCP "
                       f"session — tools register after connect_instance)",
                probe=ProbeTier.LIVENESS,
            ))
            return

    if _file_exists(ah):
        report.items.append(CheckResult(
            name="ghidra", status=Status.WARN, tier=Tier.HARD,
            detail=f"analyzeHeadless at {ah} — presence only, {_UNVERIFIED} "
                   f"(run toolchain --capability for a trial import)",
            probe=ProbeTier.PRESENCE,
        ))
        return
    if ida:
        report.items.append(CheckResult(
            name="ida", status=Status.WARN, tier=Tier.HARD,
            detail=f"idat64 at {ida} — presence only, {_UNVERIFIED}",
            probe=ProbeTier.PRESENCE,
        ))
        return

    if has_native_so is False:
        report.items.append(CheckResult(
            name="decompiler", status=Status.WARN, tier=Tier.HARD,
            detail="No decompiler found (need Ghidra, IDA, or a ghidra/ida-pro-vm "
                   "MCP registration) — WARN for pure-DEX samples; HARD if sample "
                   "has .so (see the #408 installer)",
            probe=ProbeTier.PRESENCE,
        ))
    else:
        report.items.append(CheckResult(
            name="decompiler", status=Status.FAIL, tier=Tier.HARD,
            detail=("Sample has native .so — decompiler REQUIRED for native code"
                    if has_native_so
                    else "No decompiler found (need Ghidra, IDA, or a "
                         "ghidra/ida-pro-vm MCP registration — see the #408 "
                         "installer)"),
            root_cause="decompiler" if has_native_so else None,
            probe=ProbeTier.PRESENCE,
        ))


# ---------- #449: env = f(task_spec) — needs-first requirements ----------

# The environment contract derives from the TASK, not the type template: a
# static-only task_spec must not HARD-require the VM channel (#449 evidence
# 2: 2026-08-17 transcript — task_spec unanswered while the full VM chain
# was already brought up). Conservative rule: every field the task_spec does
# not explicitly answer keeps its current HARD tier — an absent/unreadable
# task_spec is byte-identical to the pre-#449 gate.
TASK_SPEC_FILENAME = "task_spec.yaml"


@dataclass(frozen=True)
class Requirements:
    """Which environment capabilities the TASK needs (env = f(task_spec)).

    needs_vm: the windows/linux VM channel (vmr-shell + frida-to-VM) is
        required. True is the conservative default — the pre-#449 status
        quo — whenever task_spec does not explicitly say otherwise.
    basis: why (task_spec field citation, or the conservative default) —
        rides into the downgraded check details so a WARN is never mystery
        noise.
    """

    needs_vm: bool = True
    basis: str = "task_spec absent/unreadable — conservative default (VM HARD)"


DEFAULT_REQUIREMENTS = Requirements()


def requirements_from_task_spec(task_spec: dict | None) -> Requirements:
    """Derive the environment requirement set from a parsed task_spec.

    Reads ONLY explicit task_spec fields: constraints.dynamic_re ("allowed"
    | "forbidden" — templates/state/task_spec.yaml, the master switch for
    emulation/Frida). "forbidden" = static-only → the VM channel is not
    needed. Anything else (absent, empty, non-mapping, garbage, "allowed")
    stays conservative: needs_vm=True, pre-#449 behavior.

    primary_questions carry no env-relevant explicit field today (their
    `need:` enum says how to answer, not which environment to bring up);
    when one lands (#450+), it extends HERE, never at the checkers.
    vm_detonation ALONE does not relax (openspec issue-449 design R1): it
    forbids vmr-shell detonation only — frida-on-VM may still be the plan;
    the per-port contract is #450 env-manifest scope.
    """
    if not isinstance(task_spec, dict):
        return DEFAULT_REQUIREMENTS
    constraints = task_spec.get("constraints")
    if not isinstance(constraints, dict):
        return DEFAULT_REQUIREMENTS
    dynamic_re = str(constraints.get("dynamic_re", "")).strip().lower()
    if dynamic_re == "forbidden":
        return Requirements(
            needs_vm=False,
            basis="task_spec constraints.dynamic_re=forbidden (static-only)",
        )
    return DEFAULT_REQUIREMENTS


def load_task_spec(ws: Path) -> dict | None:
    """Load <ws>/task_spec.yaml → parsed mapping; None when absent/empty.

    Single loading point (kunglao-init's gate + this CLI). Fail-closed
    ValueError on an unparseable, non-mapping, or UNREADABLE file (Windows
    share lock / permission — review M2): callers must NOT relax anything
    there — the unreadable-field rule is conservative HARD (kunglao-init's
    CLAUDE.md render fails closed on the same defect).
    """
    path = ws / TASK_SPEC_FILENAME
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"task_spec.yaml unparseable: {exc}") from exc
    except OSError as exc:
        # PermissionError/locked-file path shares the unparseable route:
        # every caller's `except ValueError` already warns + stays
        # conservative HARD — no bare traceback crash out of the gate.
        raise ValueError(f"task_spec.yaml unreadable: {exc}") from exc
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError(
            "task_spec.yaml must be a YAML mapping "
            "(primary_questions/scope/constraints/...)")
    return data


def _check_vm_channel(report: ToolchainReport,
                      reqs: Requirements = DEFAULT_REQUIREMENTS) -> None:
    """VM reachability + remote-debugger cascade (windows/linux manifests).

    #449 env = f(task_spec): a static-only task (constraints.dynamic_re=
    forbidden) downgrades both items to WARN with the task_spec basis in
    the detail — capability absence is REPORTED to the orchestrator, never
    silently skipped, it just stops blocking init (same informational
    posture as jdwp_debug). Any absent/unreadable task_spec keeps the HARD
    status quo byte-identical (regression-pinned by tests). The two copies
    this helper replaces (windows/linux) were byte-identical; #407's
    _check_decompiler is the dedup pattern.

    Android has NO VM channel by design (#455: dynamics go through ADB +
    device services; NEVER_CHECKS pins it) — windows/linux only.
    """
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
        detail = f"VM {vm_host} reachable on {VM_SHELL_PORT}+{FRIDA_PORT}"
        if not reqs.needs_vm:
            detail += f" — not required by task_spec ({reqs.basis})"
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.PASS,
            tier=Tier.HARD if reqs.needs_vm else Tier.WARN,
            detail=detail, probe=ProbeTier.LIVENESS,
        ))
    elif reqs.needs_vm:
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.FAIL, tier=Tier.HARD,
            detail=f"VM unreachable: {vm_err}",
            root_cause="VM", probe=ProbeTier.LIVENESS,
        ))
    else:
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.WARN, tier=Tier.WARN,
            detail=f"VM unreachable: {vm_err} — not required by task_spec "
                   f"({reqs.basis})",
            probe=ProbeTier.LIVENESS,
        ))

    # T2: remote debugger (x64dbg/ida_server/frida-server | gdbserver/
    # linux_server64/frida-server) — cascade from VM
    if reqs.needs_vm:
        if not vm_ok:
            report.items.append(CheckResult(
                name="remote_debugger", status=Status.FAIL, tier=Tier.HARD,
                detail="Remote debugger unreachable (VM not reachable)",
                root_cause="VM", probe=ProbeTier.LIVENESS,
            ))
        else:
            # Would need actual VM-side probing — mark as WARN if can't verify
            report.items.append(CheckResult(
                name="remote_debugger", status=Status.WARN, tier=Tier.HARD,
                detail="VM reachable; remote debugger presence not verified",
                probe=ProbeTier.LIVENESS,
            ))
    else:
        state = ("VM unreachable — remote debugger unprobed" if not vm_ok
                 else "VM reachable")
        report.items.append(CheckResult(
            name="remote_debugger", status=Status.WARN, tier=Tier.WARN,
            detail=f"{state}; not required by task_spec ({reqs.basis})",
            probe=ProbeTier.LIVENESS,
        ))


# ---------- Windows manifest ----------

def _check_windows(report: ToolchainReport, ws: Path,
                   caps: bool = False,
                   reqs: Requirements = DEFAULT_REQUIREMENTS) -> None:
    """Windows toolchain checks (PE32+ x86-64)."""
    # T0: venv + pefile / DIE / floss
    for tool in ("pefile", "die", "floss"):
        # Try import-based check for pefile (Python package)
        if tool == "pefile":
            r = _run_cmd([sys.executable, "-c", "import pefile"], timeout=10)
            if r[0] == 0:
                report.items.append(CheckResult(
                    name="pefile", status=Status.PASS, tier=Tier.HARD,
                    detail="pefile importable", probe=ProbeTier.CAPABILITY,
                ))
            else:
                report.items.append(CheckResult(
                    name="pefile", status=Status.FAIL, tier=Tier.HARD,
                    detail=f"pefile not importable: {r[2][:100]}",
                    probe=ProbeTier.CAPABILITY,
                ))
            continue
        path = _shutil_which(tool)
        if path:
            report.items.append(CheckResult(
                name=tool, status=Status.PASS, tier=Tier.HARD,
                detail=f"found at {path}", probe=ProbeTier.PRESENCE,
            ))
        else:
            report.items.append(CheckResult(
                name=tool, status=Status.FAIL, tier=Tier.HARD,
                detail=f"{tool} not found in PATH",
                probe=ProbeTier.PRESENCE,
            ))

    # T1: Ghidra or IDA (#407: MCP-first, CLI fallback — one shared helper;
    # #474: three-state honest, caps plumbs the capability trial)
    _check_decompiler(report, ws, caps=caps)

    # T2: VM channel (vmr-shell 9876 + frida 1337 + remote-debugger
    # cascade) — shared helper; #449 env = f(task_spec): static-only
    # task_spec downgrades the pair to WARN (basis in the detail).
    _check_vm_channel(report, reqs)

    # T2: Docker (WARN)
    docker = _shutil_which("docker")
    if docker:
        report.items.append(CheckResult(
            name="docker", status=Status.PASS, tier=Tier.WARN,
            detail=f"docker at {docker}", probe=ProbeTier.PRESENCE,
        ))
    else:
        report.items.append(CheckResult(
            name="docker", status=Status.WARN, tier=Tier.WARN,
            detail="docker not found (optional)", probe=ProbeTier.PRESENCE,
        ))

    # #316: MCP supply (registry: ~/.claude.json + workspace .mcp.json)
    _check_mcp(report, ws, "windows")


# ---------- Linux manifest ----------

def _check_linux(report: ToolchainReport, ws: Path,
                 caps: bool = False,
                 reqs: Requirements = DEFAULT_REQUIREMENTS) -> None:
    """Linux toolchain checks (ELF)."""
    # T0: venv + binutils (file/readelf/objdump)
    for tool in ("file", "readelf", "objdump"):
        path = _shutil_which(tool)
        if path:
            report.items.append(CheckResult(
                name=tool, status=Status.PASS, tier=Tier.HARD,
                detail=f"found at {path}", probe=ProbeTier.PRESENCE,
            ))
        else:
            report.items.append(CheckResult(
                name=tool, status=Status.FAIL, tier=Tier.HARD,
                detail=f"{tool} not found in PATH",
                probe=ProbeTier.PRESENCE,
            ))

    # T1: Ghidra or IDA (#407: MCP-first, CLI fallback — one shared helper;
    # #474: three-state honest, caps plumbs the capability trial)
    _check_decompiler(report, ws, caps=caps)

    # T2: VM channel (vmr-shell 9876 + frida 1337 + remote-debugger
    # cascade) — shared helper; #449 env = f(task_spec): static-only
    # task_spec downgrades the pair to WARN (basis in the detail).
    _check_vm_channel(report, reqs)

    # T2: Docker (WARN)
    docker = _shutil_which("docker")
    if docker:
        report.items.append(CheckResult(
            name="docker", status=Status.PASS, tier=Tier.WARN,
            detail=f"docker at {docker}", probe=ProbeTier.PRESENCE,
        ))
    else:
        report.items.append(CheckResult(
            name="docker", status=Status.WARN, tier=Tier.WARN,
            detail="docker not found (optional)", probe=ProbeTier.PRESENCE,
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
            probe=ProbeTier.PRESENCE,
        ))
    else:
        report.items.append(CheckResult(
            name="gdbserver", status=Status.WARN, tier=Tier.WARN,
            detail="gdbserver not on host PATH (VM-side binary verified via VM channel)",
            probe=ProbeTier.PRESENCE,
        ))

    # T2: eBPF (WARN — kernel > 6). The gate is the TARGET (VM) kernel, not
    # the analysis host — a Windows host cannot know the VM kernel version.
    if sys.platform == "win32":
        report.items.append(CheckResult(
            name="ebpf", status=Status.WARN, tier=Tier.WARN,
            detail="host is not Linux — target VM kernel not probeable from host "
                   "(eBPF unavailable is not blocking, WARN tier)",
            probe=ProbeTier.PRESENCE,
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
                probe=ProbeTier.CAPABILITY,
            ))
        else:
            report.items.append(CheckResult(
                name="ebpf", status=Status.WARN, tier=Tier.WARN,
                detail=f"kernel {kernel_ver or 'unknown'} < 6.0 — eBPF unavailable (not blocking)",
                probe=ProbeTier.CAPABILITY,
            ))

    # T3: strace/ltrace (WARN)
    for tool in ("strace", "ltrace"):
        path = _shutil_which(tool)
        report.items.append(CheckResult(
            name=tool, status=Status.PASS if path else Status.WARN,
            tier=Tier.WARN,
            detail=f"found at {path}" if path else f"{tool} not found (optional)",
            probe=ProbeTier.PRESENCE,
        ))


# ---------- Android manifest ----------

def _check_android(report: ToolchainReport, ws: Path,
                   caps: bool = False,
                   reqs: Requirements = DEFAULT_REQUIREMENTS) -> None:
    """Android toolchain checks (APK/DEX/SO).

    #449: `reqs` is accepted for checker-signature uniformity but does not
    relax anything — android's dynamic contract is the ADB channel
    (device-side services), not the VMware/VBox VM channel (#455;
    NEVER_CHECKS). Needs-first android relaxation is follow-up scope, not
    #449 evidence."""
    # T0: venv + aapt/aapt2 (or unzip substitute)
    aapt_found = None
    for tool in ("aapt", "aapt2"):
        path = _shutil_which(tool)
        if path:
            aapt_found = tool
            report.items.append(CheckResult(
                name=tool, status=Status.PASS, tier=Tier.HARD,
                detail=f"found at {path}", probe=ProbeTier.PRESENCE,
            ))
            break
    if aapt_found is None:
        unzip = _shutil_which("unzip")
        if unzip:
            report.items.append(CheckResult(
                name="aapt", status=Status.WARN, tier=Tier.HARD,
                detail=f"aapt/aapt2 not found — unzip at {unzip} may substitute for APK unpacking",
                probe=ProbeTier.PRESENCE,
            ))
        else:
            report.items.append(CheckResult(
                name="aapt", status=Status.FAIL, tier=Tier.HARD,
                detail="aapt/aapt2 not found and no unzip substitute — APK unpacking unavailable",
                probe=ProbeTier.PRESENCE,
            ))

    # T1: jadx + apktool
    for tool in ("jadx", "apktool"):
        path = _shutil_which(tool)
        if path:
            report.items.append(CheckResult(
                name=tool, status=Status.PASS, tier=Tier.HARD,
                detail=f"found at {path}", probe=ProbeTier.PRESENCE,
            ))
        else:
            report.items.append(CheckResult(
                name=tool, status=Status.FAIL, tier=Tier.HARD,
                detail=f"{tool} not found in PATH",
                probe=ProbeTier.PRESENCE,
            ))

    # T1: GitNexus (real probe: gitnexus --version)
    gn_path = _shutil_which("gitnexus")
    if gn_path:
        rc, out, err = _run_cmd([gn_path, "--version"], timeout=15)
        if rc == 0 and out:
            report.items.append(CheckResult(
                name="gitnexus", status=Status.PASS, tier=Tier.HARD,
                detail=f"gitnexus --version OK: {out[:80]}",
                probe=ProbeTier.CAPABILITY,
            ))
        else:
            report.items.append(CheckResult(
                name="gitnexus", status=Status.FAIL, tier=Tier.HARD,
                detail=f"gitnexus at {gn_path} but --version probe failed"
                       f" ({err or out[:60]}) — post-decompile graph building requires it",
                probe=ProbeTier.CAPABILITY,
            ))
    else:
        report.items.append(CheckResult(
            name="gitnexus", status=Status.FAIL, tier=Tier.HARD,
            detail="gitnexus not found — post-decompile graph building requires it",
            probe=ProbeTier.PRESENCE,
        ))

    # T1: Ghidra or IDA (native .so decompilation; #407 MCP-first helper)
    _check_decompiler(report, ws, has_native_so=_probe_native_so(ws),
                      caps=caps)

    # T2: ADB (root dependency)
    adb = _shutil_which("adb")
    adb_ok = False
    if adb:
        # Check adb devices (liveness: the daemon answers + a device shows)
        rc, out, err = _run_cmd([adb, "devices"], timeout=10)
        devices = [l.strip() for l in out.splitlines() if "\tdevice" in l]
        if devices:
            adb_ok = True
            report.items.append(CheckResult(
                name="adb", status=Status.PASS, tier=Tier.HARD,
                detail=f"adb found, devices: {', '.join(devices)}",
                probe=ProbeTier.CAPABILITY,
            ))
        else:
            report.items.append(CheckResult(
                name="adb", status=Status.FAIL, tier=Tier.HARD,
                detail="adb found but no devices attached",
                root_cause="ADB", probe=ProbeTier.CAPABILITY,
            ))
    else:
        report.items.append(CheckResult(
            name="adb", status=Status.FAIL, tier=Tier.HARD,
            detail="adb not found in PATH — Android device bridge unavailable",
            root_cause="ADB", probe=ProbeTier.PRESENCE,
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
                detail=f"device rooted: {out}", probe=ProbeTier.CAPABILITY,
            ))
        else:
            report.items.append(CheckResult(
                name="device_root", status=Status.FAIL, tier=Tier.HARD,
                detail=f"Device not rooted or su unavailable: {err or out[:100]}",
                root_cause="root", probe=ProbeTier.CAPABILITY,
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
                probe=ProbeTier.CAPABILITY,
            ))
        else:
            report.items.append(CheckResult(
                name="debug_flag", status=Status.FAIL, tier=Tier.HARD,
                detail=f"debug flag not set (ro.debuggable={debuggable or 'unreadable'}; "
                       f"{err or out[:60]}) — required for Android dynamic analysis",
                root_cause="debug_flag", probe=ProbeTier.CAPABILITY,
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
                probe=ProbeTier.LIVENESS,
            ))
        else:
            report.items.append(CheckResult(
                name="frida_server", status=Status.FAIL, tier=Tier.HARD,
                detail=f"frida-server NOT verified on custom port {FRIDA_PORT}: {detail} — "
                       f"must run a RENAMED binary on the custom port "
                       f"(default name/port 27042 is detected by samples)",
                root_cause="frida_server", probe=ProbeTier.LIVENESS,
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
                probe=ProbeTier.LIVENESS,
            ))
        else:
            report.items.append(CheckResult(
                name="android_server", status=Status.FAIL, tier=Tier.HARD,
                detail=f"android_server NOT verified on port {ANDROID_SERVER_PORT}: {detail} — "
                       f"adb push android_server to the device and run it",
                root_cause="android_server", probe=ProbeTier.LIVENESS,
            ))

    # T2: jdwp_debug (#474, #474-followup 2026-08-19) — JDWP raw-handshake
    # liveness probe: the android dynamic-debugging core previously had NO
    # probe. Discover a debuggable pid via `adb jdwp`, forward to jdwp:<pid>,
    # exchange the 14-byte handshake — side-effect-free, unlike `jdb
    # -attach` (attach holds/resumes the target VM).
    # TIER NOTE (user ruling 2026-08-19): JDWP is NOT a hard requirement —
    # static-only and frida-driven flows never touch jdb. The probe is
    # informational (WARN tier): a miss reports capability-absence to the
    # ORCHESTRATOR (which decides whether dynamic debugging is needed for
    # this task — ReAct/reflexion routing is orchestrator territory, not a
    # scaffold gate). Only a jdwp-dependent task treats the miss as blocking
    # (worker_budget check_env_fresh does that per-dispatch, not init).
    if not adb_ok:
        report.items.append(CheckResult(
            name="jdwp_debug", status=Status.WARN, tier=Tier.WARN,
            detail="JDWP unprobed — ADB unavailable (informational; only "
                   "jdwp-dependent tasks need this capability)",
            probe=ProbeTier.LIVENESS,
        ))
    else:
        assert adb  # noqa: S101 — adb is set when adb_ok is True
        ok, detail = _adb_jdwp_probe(adb)
        if ok:
            report.items.append(CheckResult(
                name="jdwp_debug", status=Status.PASS, tier=Tier.WARN,
                detail=detail, probe=ProbeTier.LIVENESS,
            ))
        else:
            report.items.append(CheckResult(
                name="jdwp_debug", status=Status.WARN, tier=Tier.WARN,
                detail=f"JDWP agent not verified: {detail} — dynamic "
                       f"debugging via jdb unavailable for this workspace; "
                       f"static/frida flows are unaffected (the raw "
                       f"handshake probe is used; never jdb -attach)",
                probe=ProbeTier.LIVENESS,
            ))

    # T2: eBPF (SDK >= 31) — WARN gate
    if not adb_ok:
        report.items.append(CheckResult(
            name="ebpf_android", status=Status.WARN, tier=Tier.WARN,
            detail="Cannot check Android SDK version — ADB unavailable",
            probe=ProbeTier.CAPABILITY,
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
                probe=ProbeTier.CAPABILITY,
            ))
        else:
            report.items.append(CheckResult(
                name="ebpf_android", status=Status.WARN, tier=Tier.WARN,
                detail=f"Android SDK {sdk if sdk else 'unknown (probe failed: ' + (err or out)[:60] + ')'} "
                       f"< 31 — eBPF unavailable (Android 12+ required; not blocking)",
                probe=ProbeTier.CAPABILITY,
            ))

    # T3: unidbg (WARN)
    java = _shutil_which("java")
    report.items.append(CheckResult(
        name="unidbg", status=Status.WARN, tier=Tier.WARN,
        detail=f"java {'found' if java else 'not found'} — unidbg is optional fallback",
        probe=ProbeTier.PRESENCE,
    ))

    # #316: MCP supply (registry: ~/.claude.json + workspace .mcp.json)
    _check_mcp(report, ws, "android")


# ---------- type resolution ----------
# F6 (#304 review): read_project_type imported from init_state.py above —
# single source of truth; no local duplicate.

# #455: the type IS the environment-contract selector — each type selects
# a completely different check set. Declared here (consumed by tests as the
# contract surface; the checkers dict in check() is the execution source):
#   * decompiler surfaces as one of decompiler | ghidra | ida (whichever
#     probe hits first — #407 MCP-first);
#   * aapt surfaces as aapt or aapt2 (aapt2 wins if found);
#   * mcp:<name> items are dynamic (mcp_probe.MANIFEST per type).
# ANDROID IS NOT A VM CHANNEL CONTRACT: the android set never contains
# vm_reachable / remote_debugger — the VMware/VBox ports (9876 vmr-shell /
# 1337 frida-to-VM) belong to the windows/linux VM contracts only. Android
# dynamics go through ADB + device-side services (adb forward + the
# frida/android_server device ports), which is a different contract by
# design (issue #455 evidence 2; deep manifest is #450).
CHECK_SETS: dict[str, frozenset[str]] = {
    "windows": frozenset({
        "pefile", "die", "floss", "decompiler", "ghidra", "ida",
        "vm_reachable", "remote_debugger", "docker",
    }),
    "linux": frozenset({
        "file", "readelf", "objdump", "decompiler", "ghidra", "ida",
        "vm_reachable", "remote_debugger", "docker", "gdbserver",
        "ebpf", "strace", "ltrace",
    }),
    "android": frozenset({
        "aapt", "aapt2", "jadx", "apktool", "gitnexus",
        "decompiler", "ghidra", "ida",
        "adb", "device_root", "debug_flag", "frida_server",
        "android_server", "jdwp_debug", "ebpf_android", "unidbg",
    }),
}

# The explicit negative declaration: items a type must NEVER produce.
# Regression-pinned by tests/test_target_alignment.py (#455 checkbox 4).
NEVER_CHECKS: dict[str, frozenset[str]] = {
    "android": frozenset({"vm_reachable", "remote_debugger"}),
}

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
                "probe": i.probe.value,  # #474: presence|liveness|capability
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

def check(ws: Path, project_type: str | None = None,
          caps: bool = False,
          task_spec: dict | None = None) -> ToolchainReport:
    """Run type-aware toolchain checks.

    #474: caps=True opts into CAPABILITY-tier trial probes (decompiler
    import trial, minutes-long). The default path runs presence+liveness
    only — capability trials are init-only/on-demand by contract.
    #449 needs-first: task_spec (a PARSED mapping — load_task_spec is the
    single loading point at the callers) derives the environment
    requirements via requirements_from_task_spec; None = conservative
    defaults, every unreadable field keeps its pre-#449 HARD tier. The
    type stays the manifest selector (template default); the task_spec
    only tightens/relaxes requirement tiers on top of it.
    """
    if project_type is None:
        project_type = read_project_type(ws)
    if project_type not in VALID_TYPES:
        raise ValueError(
            f"Invalid project type: {project_type!r}. "
            f"Must be one of: {', '.join(VALID_TYPES)}. "
            f"Set --type or add project_type=<type> to analysis_state.txt."
        )
    report = ToolchainReport(project_type=project_type)
    reqs = requirements_from_task_spec(task_spec)
    checkers = {
        "windows": _check_windows,
        "linux": _check_linux,
        "android": _check_android,
    }
    checkers[project_type](report, ws, caps=caps, reqs=reqs)
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
    parser.add_argument("--capability", action="store_true",
                        help="run CAPABILITY-tier trial probes (decompiler "
                             "import trial; minutes-long — init/on-demand "
                             "only, #474)")
    args = parser.parse_args(argv)

    ws = Path(args.workspace).resolve()
    # #449 needs-first: consume <ws>/task_spec.yaml when present; garbage
    # never relaxes anything — warn + conservative HARD (pre-#449 tiers).
    try:
        task_spec = load_task_spec(ws)
    except ValueError as exc:
        print(f"WARNING: {exc} — toolchain layers stay conservative HARD "
              f"(#449; fix task_spec.yaml at needs-first intake)",
              file=sys.stderr)
        task_spec = None
    try:
        report = check(ws, args.type, caps=args.capability,
                       task_spec=task_spec)
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
