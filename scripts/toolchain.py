#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolchain.py — type-aware toolchain probe matrix (#304, #474 probe tiers).

Per-type manifests (windows/linux/android/web), tiers 0-3
(HARD/HARD/HARD/WARN). #728: web is labs — WARN-only face, no HARD items.
Real probes (subprocess with timeouts, fail-open on probe crash but honest
reporting). Dependency-cascade error messages that name the ROOT CAUSE.
#474: every check carries a probe tier — PRESENCE (exists), LIVENESS
(side-effect-free handshake), CAPABILITY (trial run; opt-in only).
#449 needs-first: env = f(task_spec) — requirements_from_task_spec derives
the VM-channel requirement from a parsed task_spec (static-only:
constraints.dynamic_re=forbidden downgrades vm_reachable/remote_debugger
to WARN); absent/unreadable task_spec = conservative HARD, byte-identical
to the pre-#449 gate.
#451: every FAIL carries a machine-parseable next_action (NextAction:
closed verb set + exact command + enumerated options) — human output
appends `action:`/`command:`/`option N:` key-value lines after the fix
line, --json adds a next_action object; vm_reachable FAIL embeds a
read-only discovered-VM inventory (vmrun + VBoxManage + snapshots) and
the fix names the exact next step (the OPERATOR picks, never init).

CLI: toolchain.py <workspace> [--type t] [--json] [--reproduce] [--capability]
     (consumes <workspace>/task_spec.yaml when present, #449)
Exit codes: 0 = all PASS, 1 = any HARD FAIL, 2 = only WARN failures,
8 = sole blocker is a PendingDecision CHOICE (issue 202 decompiler lane — the
pending-decision exit; the report has no other HARD FAIL).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shlex
import socket
import shutil
import subprocess
import sys
import time
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# UTF-8 stdout unification (same pattern as tools/static/common.py (ex-_common.py, merged #340))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# single source in _boot (the stdio-insurance boot module);
# alias binds the SHARED function so the module-level call below keeps its
# exact position in module-init order (stdout first, then stderr).
from _boot import ensure_utf8_stderr as _ensure_utf8_stderr  # noqa: E402


_ensure_utf8_stderr(sys.stderr)

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

# the exit-8 CHOICE rides the shared pending-decision schema
# (same channel as the negotiation menu and kunglao-init intake).
import decision_pending  # noqa: E402  (same dir, sys.path injected above)

# #449 needs-first: task_spec loading for env = f(task_spec) — same YAML
# dependency kunglao-init already uses for the CLAUDE.md constraint block.
import yaml  # noqa: E402

# #728: web mirrors init_state.VALID_TYPES (deliberate layer copy —
# comment block at the original definition site).
# #760: "macos" joins the labs pair (WARN-only face, no VM channel —
# openspec/changes/issue-760-dispatch-tools D4).
VALID_TYPES = ("windows", "linux", "android", "web", "macos")

# F6 (#304 review): single source of truth for the init predicate component.
from init_state import read_project_type  # noqa: E402
from report_render import (  # noqa: E402  (render face — one definition)
    ANDROID_SERVER_PORT,
    FRIDA_PORT,
    FIXES,
    NEXT_ACTION_VERBS,  # noqa: F401  (re-exported render face: init/negotiation/tests)
    NextAction,
    ToolMeta,  # noqa: F401  (re-exported render face: init/negotiation/tests)
    fix_text,
    parse_port as _parse_port,
)

VM_SHELL_PORT = _parse_port(os.environ.get("KUNGLAO_VM_SHELL_PORT"), 9876)

# #698 dynamic channel: KUNGLAO_CHANNEL picks the agent's execution control
# plane for dynamic debugging (five first-class, environment-equivalent
# backends; default vmr keeps the pre-#698 behavior byte-identical).
SSH_CONNECT_TIMEOUT = 5    # seconds, BatchMode connect timeout
CHANNEL_CMD_TIMEOUT = 15   # seconds, channel capability probes (ssh/docker/adb)

# Static per-item next actions (mirrors the FIXES name surface; vm_reachable
# and remote_debugger are DYNAMIC — derived from the live VM inventory in
# _vm_fail_fixes — and mcp:<name> is derived from the manifest register text).
_STATIC_NEXT_ACTIONS: dict[str, NextAction] = {
    "unidbg": NextAction(
        "install", "bash scripts/install_unidbg.sh (or scripts/install_unidbg.py)"),
    "pefile": NextAction("install", "pip install pefile"),
    "uv": NextAction(
        "install", "curl -LsSf https://astral.sh/uv/install.sh | sh"),
    "die": NextAction("install"),  # platform matrix: FIXES text / #408 installer
    "floss": NextAction("install", "pip install flare-floss"),
    "file": NextAction("install"),
    "readelf": NextAction("install"),
    "objdump": NextAction("install"),
    "decompiler": NextAction(
        "install",
        "choco install ghidra -y (win32) | brew install --cask ghidra (darwin) "
        "| apt-get install -y ghidra (linux)"),
    "ghidra": NextAction("set-env",
                         "set GHIDRA_HOME=<Ghidra install root>"),
    "ida": NextAction("register-mcp",
                      "claude mcp add --transport http ida-pro-vm <ida-mcp-url>"),
    "aapt": NextAction("install",
                       "install Android SDK build-tools (aapt/aapt2)"),
    "jadx": NextAction("install"),
    "apktool": NextAction("install"),
    "gitnexus": NextAction("install", "npm i -g gitnexus"),
    "dexdc": NextAction("install",
                        "cd dex-decompiler-py && maturin build --release && pip install target/wheels/dex_decompiler-*.whl"),
    "apkid": NextAction("install", "pip install apkid"),
    "baksmali": NextAction("install",
                           "download from https://github.com/baksmali/smali/releases (or apt install baksmali)"),
    "adb": NextAction("install",
                      "install Android SDK platform-tools and add adb to PATH"),
    "device_root": NextAction(
        "human-configure", "adb shell su -c id (rooting is a human decision)"),
    "debug_flag": NextAction(
        "human-configure",
        "adb shell setprop ro.debuggable 1 (or am set-debug-app -w <pkg>)"),
    "frida_server": NextAction(
        "human-deploy",
        "adb push a RENAMED frida-server to the device and run it on the "
        "custom port"),
    "android_server": NextAction(
        "human-deploy", "adb push android_server to the device and run it"),
    "jdwp_debug": NextAction("human-configure"),
    # #728 web (labs): direct-npx JS recovery tools — agent-invoked, so the
    # command mirrors the FIXES text (first npx run installs).
    "wakaru": NextAction("install", "npx -y wakaru --version"),
    "webcrack": NextAction("install", "npx -y webcrack --version"),
}


def next_action_for(item: "CheckResult") -> NextAction | None:
    """Derive the machine-parseable next action for a report item (#451).

    Priority: item-level dynamic (the VM inventory path) > static table >
    mcp:<name> derived from the manifest register command > root-cause-VM
    fallback (fix the VM channel first) > None."""
    if item.next_action is not None:
        return item.next_action
    if item.name.startswith("mcp:"):
        meta = FIXES.get(item.name)  # ToolMeta (#680); command = the fix face
        return (NextAction("register-mcp", meta.fix)
                if meta is not None and meta.fix else None)
    static = _STATIC_NEXT_ACTIONS.get(item.name)
    if static is not None:
        return static
    if item.root_cause == "VM":
        return NextAction("vm-enumerate", "vmrun list")
    return None


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


# Ownership tiers — WHO owns the remediation of a check. The blanket
# "HARD toolchain missing = human-install event" doctrine is REPLACED by
# these tiers: the agent attempts AGENT-DO items immediately (registering
# MCPs via `claude mcp add`, configuring the connected rooted device over
# adb, running registered installers), escalates ONLY genuine HUMAN-ONLY
# failures (license purchase, physical device actions, credentials), and
# the decompiler face branches on the task's declared lane
# (LANE-CONDITIONAL).
class OwnerTier(Enum):
    """Remediation ownership of one check (issue 202)."""
    AGENT_DO = "agent_do"                  # agent attempts immediately
    HUMAN_ONLY = "human_only"              # license / physical / credentials
    LANE_CONDITIONAL = "lane_conditional"  # decompiler face branches on lane


# Owner map: agent-do is the DEFAULT (kunglao runtime agents never defer
# tooling work to the user); the explicit exceptions are the HUMAN-ONLY
# decisions and the LANE-CONDITIONAL decompiler face.
_OWNER_BY_NAME: dict[str, OwnerTier] = {
    "device_root": OwnerTier.HUMAN_ONLY,   # rooting = physical device decision
    "vm_reachable": OwnerTier.HUMAN_ONLY,  # operator picks the VM (#451)
    "remote_debugger": OwnerTier.HUMAN_ONLY,
    "decompiler": OwnerTier.LANE_CONDITIONAL,
    "ghidra": OwnerTier.LANE_CONDITIONAL,
    "ida": OwnerTier.LANE_CONDITIONAL,
}
_OWNER_DEFAULT = OwnerTier.AGENT_DO


def owner_for(name: str) -> OwnerTier:
    """Owner class for a check item name (issue 202)."""
    if name in _OWNER_BY_NAME:
        return _OWNER_BY_NAME[name]
    if name.startswith("mcp:"):
        return OwnerTier.AGENT_DO
    return _OWNER_DEFAULT


@dataclass
class CheckResult:
    """Single toolchain check result."""
    name: str
    status: Status
    tier: Tier
    detail: str
    root_cause: str | None = None
    probe: ProbeTier = ProbeTier.PRESENCE  # #474: how it was verified
    fix: str | None = None  # #451: item-level dynamic fix; overrides FIXES static text
    next_action: NextAction | None = None  # #451: machine-parseable remediation
    owner: OwnerTier = OwnerTier.AGENT_DO  # remediation ownership (issue 202)
    attempts: tuple[str, ...] = ()  # recorded AGENT-DO attempt commands
    pending_decision: decision_pending.PendingDecision | None = None  # issue 202


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


def _which_items(tools, tier: "Tier", missing_status: "Status | None" = None,
                 missing_detail: str = "{tool} not found in PATH",
                 found_detail: str = "found at {path}") -> list["CheckResult"]:
    """#863 Family D: which→CheckResult 单源。

    tools = 命令名序列；每个命令 which 命中 → PASS(found at path)，
    未命中 → missing_status（默认 tier==WARN→WARN 否则 FAIL）+ missing_detail。

    #697: which 命中且 FIXES[name].verify_cmd 存在时真执行该命令（经
    fail-open 的 _run_cmd，10s 超时）——rc==0 升级为 ProbeTier.LIVENESS
    （detail 附首个 stdout 行）；rc!=0/崩溃 → WARN（#449 needs-first，
    坏工具降级不阻塞静态任务）+ 首个 stderr 行作为真因。无 verify_cmd
    的工具保持 PRESENCE 行为不变（缺 shared library / 0 字节残留 / 死
    链不再漏放 —— issue #697 三种坏法全部过检的根因是只验存在）。
    """
    out = []
    for name in tools:
        path = _shutil_which(name)
        if path:
            meta = FIXES.get(name)
            verify = meta.verify_cmd if meta is not None else None
            if not verify:
                out.append(CheckResult(
                    name=name, status=Status.PASS, tier=tier,
                    detail=found_detail.format(tool=name, path=path),
                    probe=ProbeTier.PRESENCE,
                ))
                continue
            rc, v_out, v_err = _run_cmd(verify.split(), timeout=10)
            if rc == 0:
                first_line = v_out.splitlines()[0] if v_out else ""
                out.append(CheckResult(
                    name=name, status=Status.PASS, tier=tier,
                    detail=(found_detail.format(tool=name, path=path)
                            + (f" — {first_line}" if first_line else "")),
                    probe=ProbeTier.LIVENESS,
                ))
            else:
                first_err = (v_err.splitlines()[0] if v_err else
                             (v_out.splitlines()[0] if v_out else
                              f"verify rc={rc}"))
                out.append(CheckResult(
                    name=name, status=Status.WARN, tier=tier,
                    detail=(found_detail.format(tool=name, path=path)
                            + f" but verify failed: {first_err}"),
                    probe=ProbeTier.LIVENESS,
                ))
        else:
            out.append(CheckResult(
                name=name, status=(missing_status or
                                   (Status.WARN if tier == Status.WARN
                                    else Status.FAIL)),
                tier=tier,
                detail=missing_detail.format(tool=name),
                probe=ProbeTier.PRESENCE,
            ))
    return out


def _run_cmd(args: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run a command with timeout; returns (rc, stdout, stderr).
    Fail-open on crash: return (1, "", str(exc)).
    Windows: .bat/.cmd executables must go through cmd /c (CreateProcess
    cannot pass args to a batch file directly)."""
    run_args = args
    if os.name == "nt" and args and args[0].lower().endswith((".bat", ".cmd")):
        run_args = ["cmd", "/c", *args]
    # Test harnesses that run this script under heavy parallelism (xdist on
    # a loaded machine) may raise a floor via env so a starved-but-healthy
    # probe is not misread as unavailable. Default floor 0: production
    # budgets are exactly the per-call constants.
    floor = int(os.environ.get("KUNGLAO_PROBE_TIMEOUT_FLOOR", "0") or 0)
    if floor > timeout:
        timeout = floor
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


# ---------- #451: VM inventory (read-only discovery) ----------
# Issue #451 evidence 1 (toolchain.py:84 pre-patch): a bare "set
# KUNGLAO_VM_HOST" fix pushes the discovery work back onto the human. The
# check itself enumerates what exists (vmrun + VirtualBox, snapshots, power
# state, read-only + fail-open) and the fix names the exact next step.
# Inventory evidence is presence-tier (#474) — it never changes the
# vm_reachable LIVENESS claim, it enriches the FAILURE surface only.

_VMRUN_STOCK_PATHS = (
    r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
    r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
)


def _vmrun_exe() -> str | None:
    """Locate vmrun: KUNGLAO_VMRUN_PATH override > PATH > stock Workstation
    install paths. Tests close this seam (monkeypatch -> None)."""
    override = _env_get("KUNGLAO_VMRUN_PATH")
    if override:
        return override if os.path.isfile(override) else None
    found = _shutil_which("vmrun")
    if found:
        return found
    for p in _VMRUN_STOCK_PATHS:
        if os.path.isfile(p):
            return p
    return None


def _vbox_exe() -> str | None:
    """Locate VBoxManage: KUNGLAO_VBOXMANAGE_PATH override > PATH."""
    override = _env_get("KUNGLAO_VBOXMANAGE_PATH")
    if override:
        return override if os.path.isfile(override) else None
    return _shutil_which("VBoxManage")


@dataclass(frozen=True)
class VMInventoryEntry:
    """One discovered VM (name, config path, power state, snapshots)."""

    name: str
    vmx: str
    running: bool
    snapshots: tuple[str, ...] = ()


def _vmrun_inventory(vmrun: str) -> list[VMInventoryEntry]:
    """Registered (inventory.vmls) + running (vmrun list) VMware VMs with
    snapshot names. Read-only; any probe failure degrades to fewer entries."""
    rc, out, _err = _run_cmd([vmrun, "-T", "ws", "list"], timeout=15)
    running: set[str] = set()
    if rc == 0:
        for line in out.splitlines()[1:]:  # skip "Total running VMs: N"
            vmx = line.strip()
            if vmx.lower().endswith(".vmx"):
                running.add(vmx)
    entries: dict[str, VMInventoryEntry] = {}
    for vmx in running:
        entries[vmx] = VMInventoryEntry(name=Path(vmx).stem, vmx=vmx,
                                        running=True)
    inv = Path(os.environ.get("APPDATA", "")) / "VMware" / "inventory.vmls"
    if inv.is_file():
        try:
            text = inv.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        cur_cfg: str | None = None
        for m in re.finditer(
                r'config\s*=\s*"([^"]+\.vmx)"|DisplayName\s*=\s*"([^"]*)"',
                text):
            cfg, disp = m.group(1), m.group(2)
            if cfg:
                cur_cfg = cfg
            elif cur_cfg:
                name = disp or Path(cur_cfg).stem
                old = entries.get(cur_cfg)
                entries[cur_cfg] = VMInventoryEntry(
                    name=name, vmx=cur_cfg, running=bool(old and old.running))
                cur_cfg = None
    for vmx, entry in list(entries.items()):
        rc, out, _err = _run_cmd(
            [vmrun, "-T", "ws", "listSnapshots", vmx], timeout=10)
        if rc == 0:
            snaps = tuple(l.strip() for l in out.splitlines()[1:] if l.strip())
            entries[vmx] = VMInventoryEntry(name=entry.name, vmx=vmx,
                                            running=entry.running,
                                            snapshots=snaps)
    return list(entries.values())


def _vbox_inventory(vbox: str) -> list[VMInventoryEntry]:
    """VirtualBox VMs (read-only; probe failure -> [])."""
    rc_r, out_r, _ = _run_cmd([vbox, "list", "runningvms"], timeout=15)
    run_names = {l.split('"')[1] for l in (out_r or "").splitlines()
                 if l.startswith('"')} if rc_r == 0 else set()
    rc_a, out_a, _ = _run_cmd([vbox, "list", "vms"], timeout=15)
    result: list[VMInventoryEntry] = []
    if rc_a == 0:
        for line in out_a.splitlines():
            if line.startswith('"'):
                name = line.split('"')[1]
                result.append(VMInventoryEntry(name=name, vmx=line,
                                               running=name in run_names))
    return result


def _vm_inventory() -> tuple[list[VMInventoryEntry], bool, bool]:
    """(entries, has_vmrun, has_vbox) — the single seam tests replace."""
    entries: list[VMInventoryEntry] = []
    vmrun = _vmrun_exe()
    if vmrun:
        entries.extend(_vmrun_inventory(vmrun))
    vbox = _vbox_exe()
    if vbox:
        entries.extend(_vbox_inventory(vbox))
    return entries, vmrun is not None, vbox is not None


def _vm_inventory_detail(entries: list[VMInventoryEntry]) -> str:
    """Numbered candidate list (the issue's real-output format)."""
    if not entries:
        return "  (none)"
    lines: list[str] = []
    for i, e in enumerate(entries, 1):
        state = "RUNNING" if e.running else "off"
        snap = f"snapshots: {len(e.snapshots)}"
        if e.snapshots:
            snap += f" (latest: {e.snapshots[-1]})"
        lines.append(f"  {i}. {e.name} [{state}] {snap}")
        lines.append(f"     {e.vmx}")
    return "\n".join(lines)


def _vm_fail_fixes(vm_host: str | None,
                   vm_err: str) -> tuple[str, str, NextAction]:
    """(detail, fix, next_action) for a FAILED VM check, derived from the
    live read-only inventory (#451 evidence 1: the check enumerates, the
    OPERATOR decides — init never auto-selects among candidates)."""
    entries, has_vmrun, has_vbox = _vm_inventory()
    detail = (f"VM unreachable: {vm_err}\n"
              f"discovered VMs (vmrun={has_vmrun}, vbox={has_vbox}):\n"
              + _vm_inventory_detail(entries))
    ports = f"vmr_server {VM_SHELL_PORT} + frida-server {FRIDA_PORT}"
    names = tuple(e.name for e in entries)
    if vm_host:
        running = [e for e in entries if e.running]
        detail += ("\nnote: KUNGLAO_VM_HOST is set but ports closed; if the "
                   "VM just rebooted its DHCP lease changed - re-resolve the "
                   "IP, never reuse a cached one")
        if running:
            fix = (f"running VM(s): {', '.join(e.name for e in running)}. "
                   f"Re-resolve the live IP (vmrun getGuestIPAddress "
                   f'"{running[0].vmx}"), set KUNGLAO_VM_HOST=<ip>, and '
                   f"ensure {ports} are listening inside the guest")
            na = NextAction("vm-reip",
                            f'vmrun getGuestIPAddress "{running[0].vmx}"',
                            tuple(e.name for e in running))
        else:
            fix = (f"no running VM discovered - start the analysis VM "
                   f"(candidates above), resolve its IP, set "
                   f"KUNGLAO_VM_HOST=<ip>, ensure {ports} in-guest")
            na = NextAction("vm-start", 'vmrun -T ws start "<vmx>" nogui',
                            names)
        return detail, fix, na
    if len(entries) == 1:
        e = entries[0]
        if e.running:
            fix = (f"single candidate {e.name} is RUNNING - resolve its IP "
                   f'(vmrun getGuestIPAddress "{e.vmx}"), set '
                   f"KUNGLAO_VM_HOST=<ip>, ensure {ports} in-guest")
            na = NextAction("vm-reip",
                            f'vmrun getGuestIPAddress "{e.vmx}"', (e.name,))
        else:
            fix = (f'single candidate - start it: vmrun -T ws start "{e.vmx}" '
                   f'nogui; resolve: vmrun getGuestIPAddress "{e.vmx}"; set '
                   f"KUNGLAO_VM_HOST=<ip>; ensure {ports} in-guest")
            na = NextAction("vm-start",
                            f'vmrun -T ws start "{e.vmx}" nogui', (e.name,))
        return detail, fix, na
    if len(entries) > 1:
        return detail, (
            "multiple VM candidates listed above - the OPERATOR picks the "
            "analysis VM (init never auto-selects among candidates); start "
            f"it, resolve its IP, set KUNGLAO_VM_HOST=<ip>, ensure {ports} "
            f"in-guest"), NextAction("vm-enumerate", "vmrun list", names)
    command = ("vmrun list" if has_vmrun
               else "VBoxManage list vms" if has_vbox else None)
    return detail, (
        "no VM discovered (vmrun inventory + VirtualBox) - register or boot "
        f"the analysis VM, then set KUNGLAO_VM_HOST=<ip> ({ports} reachable)"
    ), NextAction("vm-enumerate", command)


def _probe_native_so(ws: Path) -> bool:
    """True if the sample under bins/ contains native .so code: a .so file,
    or a zip (APK/JAR) whose central directory lists lib/*.so entries.

    #756: an APK's central directory sits at the TAIL of the file while its
    lib/ local file headers sit at arbitrary offsets — the previous head-4KB
    byte scan missed real samples (live-run sample: 206 lib/**/*.so entries, zero
    head-4KB hits -> has_native_so=False degraded the HARD decompiler gate).
    namelist() reads only central-directory metadata, so it stays cheap even
    on multi-hundred-MB APKs. Non-zip files keep the .so suffix rule; a
    corrupt zip fails OPEN to the legacy head-4KB scan (never raises)."""
    bins = ws / "bins"
    if not bins.is_dir():
        return False
    for p in sorted(bins.iterdir()):
        if not p.is_file():
            continue
        if p.name.endswith(".so"):
            return True
        # #756: read the central directory once instead of guessing from the
        # head bytes — entry layout is unbounded, the directory is not.
        try:
            with zipfile.ZipFile(p) as zf:
                names = zf.namelist()
        except (zipfile.BadZipFile, OSError):
            names = None  # fail open: fall through to the legacy head scan
        if names is not None:
            if any(n.startswith("lib/") and n.endswith(".so")
                   for n in names):
                return True
            continue
        try:
            head = p.read_bytes()[:4096]
        except OSError:
            continue
        if b"lib/" in head or b".so" in head:
            return True
    return False


def _agent_do_device_bringup(adb: str, port: int, name_hint: str,
                             timeout: int = 2) -> tuple[bool, str,
                                                        tuple[str, ...]]:
    """AGENT-DO device-service bring-up (frida-server / gserver).

    The gate looks for the (renamed) binary in /data/local/tmp over su,
    starts it bound to the custom port, re-forwards and re-probes. Returns
    (ok, detail, attempts) — the attempts record rides into the report so
    the human sees exactly what the agent tried, never a bare dump."""
    ls_argv = [adb, "shell", "ls", "/data/local/tmp"]
    ls_rc, ls_out, ls_err = _run_cmd(ls_argv, timeout=10)
    candidates = [ln.strip() for ln in ls_out.splitlines()
                  if ln.strip() and name_hint in ln.lower()]
    if not candidates:
        return (False,
                (f"AGENT-DO bring-up attempt: no {name_hint} binary in "
                 f"/data/local/tmp (ls: {(ls_out or ls_err)[:80] or 'empty'})"),
                (" ".join(ls_argv),))
    binary = candidates[0]
    start_argv = [adb, "shell", "su", "-c",
                  f"nohup /data/local/tmp/{binary} -l 0.0.0.0:{port} "
                  f">/dev/null 2>&1 &"]
    _run_cmd(start_argv, timeout=10)
    attempts = (" ".join(ls_argv), " ".join(start_argv))
    time.sleep(0.5)  # device-side bring-up latency before the re-probe
    ok, detail = _adb_forward_probe(adb, port, timeout=timeout)
    return ok, detail, attempts


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


@dataclass(frozen=True)
class McpServerSpec:
    """One task_spec-declared required MCP server (issue 202, MCP face).

    task_spec `tools.mcp_servers` entries: a bare name string, or a mapping
    {name, transport, url} — the url is what makes `claude mcp add
    --transport http ida-pro-vm <url>` a runnable AGENT-DO command."""
    name: str
    transport: str = "stdio"
    url: str | None = None


@dataclass(frozen=True)
class Requirements:
    """Which environment capabilities the TASK needs (env = f(task_spec)).

    needs_vm: the windows/linux VM channel (vmr-shell + frida-to-VM) is
        required. True is the conservative default — the pre-#449 status
        quo — whenever task_spec does not explicitly say otherwise.
    needs_debug_flag: the android JDWP device flag (ro.debuggable=1) is
        required. True is the conservative default (#304 F3 enforcement).
        #25 D1: ro.debuggable=1 is unreachable on Android 12+ user builds
        (SELinux property_service lock) while frida/android_server run fine
        via Magisk su without it — a task that does not need the flag must
        be able to say so (constraints.dynamic_re=forbidden, or an explicit
        constraints.debug_flag: false); the debug_flag check then downgrades
        FAIL -> WARN instead of blocking an init that can never pass.
    decompiler_lane: the task's declared decompiler lane (issue 202
        LANE-CONDITIONAL): "mcp" = the ida-pro-vm MCP lane (check
        registration + reachability, NEVER a local IDA install/license);
        "local" = local scripting (the probe ladder); None = undeclared
        (the pre-rework combined behavior: MCP defusal, then the ladder).
    required_mcp: exact MCP servers the task requires (tools.mcp_servers,
        issue 202) — when non-empty the MCP face checks THESE instead of the
        type manifest ("the exact servers from task_spec").
    basis: why (task_spec field citation, or the conservative default) —
        rides into the downgraded check details so a WARN is never mystery
        noise.
    """

    needs_vm: bool = True
    needs_debug_flag: bool = True
    decompiler_lane: str | None = None
    required_mcp: tuple[McpServerSpec, ...] = ()
    required_mcp_declared: bool = False  # explicit tools.mcp_servers key present
    basis: str = "task_spec absent/unreadable — conservative default (VM HARD)"


DEFAULT_REQUIREMENTS = Requirements()


# ---------- MCP supply + AGENT-DO registration face ----------

# Ownership: registering required MCP servers is AGENT work — the gate
# attempts `claude mcp add` itself and escalates only genuine failures with
# the error attached. Write-attempts are opt-in per process via
# KUNGLAO_AGENT_DO=1 (kunglao-init turns it on for the init run); the bare
# CLI stays read-only so test harnesses and forensics stay side-effect-free.
AGENT_DO_ENV = "KUNGLAO_AGENT_DO"

# Safety invariant: `claude mcp add` can only mutate the REAL registry
# (~/.claude.json). When the probe targets an override registry
# (KUNGLAO_CLAUDE_JSON — tests/forensics), an attempt would write a config
# the probe cannot see: suppressed with an honest reason instead.
CLAUDE_JSON_OVERRIDE_ENV = "KUNGLAO_CLAUDE_JSON"


def _agent_do_enabled() -> bool:
    """AGENT-DO write-attempts opt-in (KUNGLAO_AGENT_DO=1)."""
    return (_env_get(AGENT_DO_ENV) or "").strip() == "1"


# The astral installer — the AGENT-DO uv install command.
UV_INSTALL_CMD = "curl -LsSf https://astral.sh/uv/install.sh | sh"
_UV_FALLBACK_PATHS = ("~/.local/bin/uv", "~/bin/uv")


def _check_uv(report: ToolchainReport) -> None:
    """uv presence + working (issue 202 scope) — AGENT-DO ownership.

    The repo standard is `uv sync --locked` + `uv run` (the shipped hook
    commands already resolve through `uv run --project`); a missing uv is
    installed by the GATE itself via the astral installer, then re-probed.
    Only a genuine failure escalates — with the error attached. Desktop
    triple only: the labs faces (web/macos) stay zero-HARD by contract."""
    uv = _shutil_which("uv")
    if uv:
        rc, out, err = _run_cmd([uv, "--version"], timeout=15)
        if rc == 0 and out:
            report.items.append(CheckResult(
                name="uv", status=Status.PASS, tier=Tier.HARD,
                detail=f"uv at {uv}: {out.splitlines()[0]}",
                probe=ProbeTier.LIVENESS,
            ))
        else:
            report.items.append(CheckResult(
                name="uv", status=Status.FAIL, tier=Tier.HARD,
                detail=f"uv at {uv} but --version failed: {err or out[:80]}",
                probe=ProbeTier.LIVENESS, root_cause="uv",
            ))
        return
    attempts: tuple[str, ...] = ()
    attempt_error = ""
    if _agent_do_enabled():
        argv = ["sh", "-c", UV_INSTALL_CMD]
        rc, out, err = _run_cmd(argv, timeout=300)
        attempts = (" ".join(argv),)
        uv = _shutil_which("uv")
        if uv is None:
            for cand in _UV_FALLBACK_PATHS:
                p = Path(os.path.expanduser(cand))
                if p.is_file():
                    uv = str(p)
                    break
        if uv:
            rc2, out2, err2 = _run_cmd([uv, "--version"], timeout=15)
            if rc2 == 0 and out2:
                report.items.append(CheckResult(
                    name="uv", status=Status.PASS, tier=Tier.HARD,
                    detail=(f"AGENT-DO: uv installed via the astral "
                            f"installer — {uv}: {out2.splitlines()[0]}"),
                    probe=ProbeTier.LIVENESS, attempts=attempts,
                ))
                return
            attempt_error = err2 or out2 or f"rc={rc2}"
        else:
            attempt_error = err or out or f"rc={rc}"
    detail = ("uv not on PATH — the repo standard is `uv sync --locked` "
              "+ `uv run` for every shipped face")
    if attempts:
        detail += f"; AGENT-DO install attempt failed: {attempt_error}"
    report.items.append(CheckResult(
        name="uv", status=Status.FAIL, tier=Tier.HARD,
        detail=detail, probe=ProbeTier.PRESENCE, root_cause="uv",
        attempts=attempts,
        fix=(f"agent installs uv itself: {UV_INSTALL_CMD} (AGENT-DO); "
             "every kunglao face runs via the uv-managed env "
             "(`uv run --project <root>` / the recorded .venv python)"),
        next_action=NextAction("install", UV_INSTALL_CMD),
    ))


def _mcp_register_attempt_allowed() -> tuple[bool, str]:
    """Preconditions for a self-registration attempt (issue 202).

    Returns (allowed, why_not) — why_not rides into the item detail so a
    skipped attempt is never silent."""
    if not _agent_do_enabled():
        return False, "agent-do disabled (KUNGLAO_AGENT_DO != 1)"
    if not _shutil_which("claude"):
        return False, "claude CLI not on PATH — cannot self-register"
    return True, ""


def _attempt_mcp_register(argv: list[str]) -> tuple[bool, str]:
    """Run `claude mcp add ...` (the AGENT-DO registration itself).

    Callers gate on _mcp_register_attempt_allowed() first; this function is
    the execution seam tests substitute. Safety invariant: `claude mcp add`
    can only mutate the REAL registry — when the probe targets an override
    registry (KUNGLAO_CLAUDE_JSON), the attempt is REFUSED here with an
    honest reason (a write the probe cannot see is never attempted)."""
    if _env_get(CLAUDE_JSON_OVERRIDE_ENV):
        return False, ("suppressed: probe targets an override registry "
                       f"({CLAUDE_JSON_OVERRIDE_ENV}) — claude mcp add would "
                       "mutate the real config")
    rc, out, err = _run_cmd(argv, timeout=60)
    return rc == 0, (err or out or f"rc={rc}")


def _concrete_register_argv(register_template: str,
                            url: str | None) -> list[str] | None:
    """Resolve a manifest register template into a runnable argv (issue 202).

    `<placeholder>` tokens resolve from the task_spec url (ida-pro-vm);
    a placeholder that cannot be resolved yields None — a literal
    `<ida-mcp-url>` never reaches a shell."""
    try:
        argv = shlex.split(register_template)
    except ValueError:
        return None
    placeholder = re.compile(r"<[^>]+>")
    out: list[str] = []
    for a in argv:
        if placeholder.search(a):
            # a placeholder may ride inside a larger token
            # (<path>/bridge-mcp-ghidra.exe) — only a resolvable url keeps
            # the template runnable
            if url is None:
                return None
            out.append(placeholder.sub(url, a))
        else:
            out.append(a)
    return out


def _task_spec_mcp_checks(specs: "tuple[McpServerSpec, ...]",
                          claude_json: Path | None,
                          ws: Path) -> list["mcp_probe.MCPCheck"]:
    """MCP face over the task_spec-declared server set (issue 202).

    When the task declares `tools.mcp_servers`, the face checks THESE exact
    servers instead of the type manifest (env = f(task_spec))."""
    found = mcp_probe.registered_names(claude_json, ws)
    checks: list[mcp_probe.MCPCheck] = []
    for spec in specs:
        if spec.name in found:
            checks.append(mcp_probe.MCPCheck(
                name=spec.name, status="PASS", tier="HARD",
                detail=f"registered ({', '.join(found[spec.name])})",
            ))
            continue
        meta = mcp_probe._BY_NAME.get(spec.name)
        if spec.transport == "http" and spec.url:
            register = (f"claude mcp add --transport http {spec.name} "
                        f"{spec.url}")
        elif meta is not None:
            register = meta.register
        else:
            register = None
        checks.append(mcp_probe.MCPCheck(
            name=spec.name, status="FAIL", tier="HARD",
            detail="not registered (required by task_spec tools.mcp_servers)",
            fix=register,
        ))
    return checks


def _mcp_server_url(name: str, claude_json: Path | None,
                    ws: Path) -> str | None:
    """Registered endpoint url for a server (first http url across the
    registration surfaces), or None."""
    urls = mcp_probe.registered_server_urls(claude_json, ws)
    return urls.get(name.lower())


def _mcp_reachability_face(item: CheckResult, name: str,
                           claude_json: Path | None, ws: Path) -> CheckResult:
    """Honest reachability evidence for a REGISTERED http-transport server.

    Registered + endpoint reachable -> probe upgrades to LIVENESS; endpoint
    dead -> WARN with the connect error (registration alone is not a live
    server). stdio servers keep presence evidence (honesty rule)."""
    url = _mcp_server_url(name, claude_json, ws)
    if not url:
        return item
    parts = urllib.parse.urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    host = parts.hostname or "127.0.0.1"
    ok, err = _tcp_connect(host, port)
    if ok:
        return dataclasses.replace(
            item, probe=ProbeTier.LIVENESS,
            detail=item.detail + f"; endpoint reachable ({host}:{port})")
    return dataclasses.replace(
        item, status=Status.WARN,
        detail=item.detail + f"; registered but endpoint unreachable: {err}")


def _check_mcp(report: ToolchainReport, ws: Path, project_type: str,
               reqs: Requirements = DEFAULT_REQUIREMENTS,
               claude_json: Path | None = None) -> None:
    """Append MCP supply checks (probe ~/.claude.json + workspace .mcp.json).

    Manifest + probe live in mcp_probe.py — single source of truth shared
    with the kunglao-init .mcp.json scaffold and the doc tables.
    issue 202: a missing required server is an AGENT-DO item — the gate attempts
    `claude mcp add` itself (opt-in via KUNGLAO_AGENT_DO=1) and re-verifies
    registration; only a genuine failure escalates, with the error attached.
    """
    if claude_json is None:
        claude_json = mcp_probe.claude_json_path()
    if reqs.required_mcp or reqs.required_mcp_declared:
        checks = _task_spec_mcp_checks(reqs.required_mcp, claude_json, ws)
    else:
        checks = mcp_probe.check_mcp(ws, project_type,
                                     claude_json=claude_json)
    spec_urls = {s.name: s.url for s in reqs.required_mcp if s.url}
    for mc in checks:
        item = CheckResult(
            name=f"mcp:{mc.name}",
            status={"PASS": Status.PASS, "FAIL": Status.FAIL,
                    "WARN": Status.WARN}[mc.status],
            tier=Tier.HARD if mc.tier == "HARD" else Tier.WARN,
            detail=mc.detail,
            # #474: registry read is presence evidence (no handshake)
            probe=ProbeTier.PRESENCE,
        )
        if item.status is Status.PASS:
            item = _mcp_reachability_face(item, mc.name, claude_json, ws)
        elif item.status is Status.FAIL and mc.fix:
            argv = _concrete_register_argv(mc.fix, spec_urls.get(mc.name))
            if argv is not None:
                allowed, why = _mcp_register_attempt_allowed()
                if allowed:
                    ok, err = _attempt_mcp_register(argv)
                    item.attempts = (" ".join(argv),)
                    if ok:
                        found = mcp_probe.registered_names(claude_json, ws)
                        if mc.name in found:
                            item = CheckResult(
                                name=item.name, status=Status.PASS,
                                tier=item.tier,
                                detail=(f"registered by agent via "
                                        f"`{' '.join(argv[:3])} ...` — "
                                        f"verified after registration"),
                                probe=ProbeTier.PRESENCE,
                                owner=OwnerTier.AGENT_DO,
                                attempts=item.attempts,
                            )
                        else:
                            item.detail += ("; register attempt ran but the "
                                            "server is still not registered")
                            item.fix = mc.fix
                    else:
                        item.detail += (f"; agent-do register attempt failed: "
                                        f"{err}")
                else:
                    item.detail += f"; agent-do register skipped: {why}"
        report.items.append(item)


# ---------- lane-conditional decompiler face ----------
# The decompiler face branches on the task's declared lane. The
# blanket "install IDA" dump is gone: MCP lane -> registration +
# reachability (never a local IDA install/license); local lane -> the
# ordered probe ladder; neither -> the exit-8 PendingDecision CHOICE.

# Registry keys checked by mcp_probe.registered_names (user ~/.claude.json +
# workspace .mcp.json). A registered MCP decompiler is the PRIMARY signal
# for the UNDECLARED lane; CLI supply is the probe-ladder surface.
_DECOMPILER_MCP_NAMES = ("ghidra", "ida-pro-vm")

# #474: a Python probe cannot reach into the MCP session (analysis tools
# register only after connect_instance succeeds — agents/ghidra-light.md),
# so the honest ceiling for registry-only evidence is WARN. Same for a
# present-but-untrialled CLI binary on the UNDECLARED lane's MCP branch.
_UNVERIFIED = "capability unverified"

# IDA probe ladder: PATH -> mdfind -> find bundle sweep -> brew cask
# -> known dirs (first hit wins). The find sweep and known-dir sweep MUST
# match macOS `.app/Contents/MacOS/` bundle layouts — the addendum's
# field-evidenced blind spot (an installed IDA reported missing because the
# probes only knew `/Applications/IDA Pro*/idabin` shapes).
_IDA_APP_DIRS_ENV = "KUNGLAO_IDA_APP_DIRS"
_DEFAULT_IDA_APP_DIRS: tuple[Path, ...] = (
    Path("/Applications"), Path.home() / "Applications")

# Known-dir sweep patterns (addendum rung d): macOS classic + bundle
# layouts, Windows and Linux equivalents. `~` expands at probe time.
_IDA_KNOWN_DIR_PATTERNS: tuple[str, ...] = (
    "/Applications/IDA Pro*/idabin/idat64*",        # classic macOS layout
    "/Applications/IDA*/Contents/MacOS/idat64",     # .app bundle (addendum)
    "/Applications/IDA*/*.app/Contents/MacOS/idat64",
    "~/Applications/IDA*/Contents/MacOS/idat64",
    "~/.ida*/idat64*",
    "/opt/ida*/idat64*",                            # linux equivalents
    "/opt/ida*/bin/idat64*",
    "/opt/ida*/*/idat64*",
    "C:/Program Files/IDA*/idat64.exe",             # windows equivalents
    "C:/Program Files/IDA*/*/idat64.exe",
)


def _ida_app_dirs() -> tuple[Path, ...]:
    """Application dirs for the find sweep (KUNGLAO_IDA_APP_DIRS override)."""
    raw = _env_get(_IDA_APP_DIRS_ENV)
    if raw and raw.strip():
        return tuple(Path(p) for p in raw.split(os.pathsep) if p.strip())
    return _DEFAULT_IDA_APP_DIRS


def _is_exec_file(p: Path) -> bool:
    try:
        return p.is_file() and os.access(p, os.X_OK)
    except OSError:
        return False


def _probe_ida_via_path() -> Path | None:
    """Ladder rung 0: idat64 already on PATH."""
    p = _shutil_which("idat64")
    if p is None and os.name == "nt":
        p = _shutil_which("idat64.exe")
    return Path(p) if p else None


def _probe_ida_via_mdfind() -> Path | None:
    """Ladder rung a (addendum): Spotlight sees .app bundles that plain
    directory probing misses. Missing mdfind / no index -> fall through."""
    queries = (["mdfind", "-name", "idat64"],
               ["mdfind", "kMDItemFSName == 'idat64'"])
    for query in queries:
        rc, out, _err = _run_cmd(query, timeout=10)
        if rc != 0:
            continue
        for line in out.splitlines():
            cand = Path(line.strip())
            if _is_exec_file(cand):
                return cand
    return None


def _walk_bounded(root: Path, max_depth: int):
    """Yield (path, depth) under root up to max_depth levels; permission
    walls (TCC) fail open — a silent shrink, never a crash."""
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for entry in entries:
            yield entry, depth
            if entry.is_dir() and depth < max_depth:
                stack.append((entry, depth + 1))


def _probe_ida_via_find(app_dirs: tuple[Path, ...]) -> Path | None:
    """Ladder rung b (addendum): the `find /Applications ~/Applications
    -maxdepth 4 (-iname idat64 -o -iname 'IDA*.app' -o -iname
    'IDAProfessional*')` sweep as a bounded pure-Python walk — same match
    set, TCC-safe, portable. .app hits resolve to
    <bundle>/Contents/MacOS/idat64."""
    for root in app_dirs:
        if not root.is_dir():
            continue
        for entry, _depth in _walk_bounded(root, 4):
            name = entry.name.lower()
            if name == "idat64" and _is_exec_file(entry):
                return entry
            if name.endswith(".app") and ("ida" in name):
                for sub in ("Contents/MacOS/idat64", "Contents/MacOS/idat64.exe"):
                    cand = entry / sub
                    if _is_exec_file(cand):
                        return cand
                macos = entry / "Contents" / "MacOS"
                if macos.is_dir():
                    for cand, _d in _walk_bounded(macos, 1):
                        if cand.name.lower().startswith("idat64") \
                                and _is_exec_file(cand):
                            return cand
            elif name.startswith("idaprofessional") and entry.is_dir():
                for cand, _d in _walk_bounded(entry, 4):
                    if cand.name.lower() == "idat64" and _is_exec_file(cand):
                        return cand
    return None


def _probe_ida_via_brew() -> Path | None:
    """Ladder rung c (addendum): brew cask inventory — `brew list --cask`
    names an ida cask, resolve the binary through the cask prefix."""
    brew = _shutil_which("brew")
    if not brew:
        return None
    rc, out, _err = _run_cmd([brew, "list", "--cask"], timeout=15)
    if rc != 0:
        return None
    casks = [ln.strip() for ln in out.splitlines()
             if "ida" in ln.lower() and ln.strip()]
    for cask in casks:
        rc2, prefix, _err2 = _run_cmd([brew, "--prefix", cask], timeout=15)
        if rc2 != 0 or not prefix.strip():
            continue
        root = Path(prefix.strip())
        for entry, _depth in _walk_bounded(root, 4):
            if entry.name.lower() in ("idat64", "idat64.exe") \
                    and _is_exec_file(entry):
                return entry
    return None


def _probe_ida_via_known_dirs(
        patterns: tuple[str, ...] | None = None) -> Path | None:
    """Ladder rung d: the known-dir sweep — classic shapes AND the
    .app/Contents/MacOS bundle layout, plus Windows/Linux equivalents."""
    for pattern in (patterns or _IDA_KNOWN_DIR_PATTERNS):
        expanded = os.path.expanduser(pattern)
        try:
            hits = sorted(glob.glob(expanded))
        except Exception:  # noqa: BLE001 — a bad pattern never kills the gate
            continue
        for hit in hits:
            cand = Path(hit)
            if _is_exec_file(cand):
                return cand
    return None


def _probe_local_ida(
        app_dirs: tuple[Path, ...] | None = None) -> tuple[Path | None, str]:
    """Ordered IDA probe ladder (issue 202 + addendum) — first hit wins.

    Returns (path, strategy) so the PASS detail records HOW the binary was
    found (probe strategy is evidence, not noise)."""
    dirs = tuple(app_dirs) if app_dirs is not None else _ida_app_dirs()
    hit = _probe_ida_via_path()
    if hit:
        return hit, "PATH"
    hit = _probe_ida_via_mdfind()
    if hit:
        return hit, "mdfind"
    hit = _probe_ida_via_find(dirs)
    if hit:
        return hit, "find-sweep"
    hit = _probe_ida_via_brew()
    if hit:
        return hit, "brew-cask"
    hit = _probe_ida_via_known_dirs()
    if hit:
        return hit, "known-dirs"
    return None, ""


def _probe_ghidra(
        search_dirs: tuple[Path, ...] | None = None) -> Path | None:
    """Ghidra probe (ladder tail): GHIDRA_HOME first (platform-correct
    analyzeHeadless name), then the known Ghidra dirs (/opt/ghidra*,
    /usr/local/ghidra*, ~/ghidra*) and the brew prefix."""
    ghidra_home = _env_get("GHIDRA_HOME")
    if ghidra_home:
        ah = platform_paths.analyze_headless(ghidra_home)
        if ah and Path(ah).exists():
            return Path(ah)
    name = platform_paths.analyze_headless_name()
    roots = search_dirs if search_dirs is not None else (
        Path("/opt"), Path("/usr/local"),
        Path(os.path.expanduser("~")),
        Path.home() / "opt" / "homebrew" / "Caskroom",
        Path("/usr/local/Caskroom"),
    )
    for root in roots:
        for pattern in (f"ghidra*/support/{name}",
                        f"ghidra*/ghidra*/support/{name}"):
            try:
                hits = sorted(root.glob(pattern))
            except OSError:
                continue
            for hit in hits:
                if _is_exec_file(hit) or hit.exists():
                    return hit
    brew = _shutil_which("brew")
    if brew:
        rc, prefix, _err = _run_cmd([brew, "--prefix", "ghidra"], timeout=15)
        if rc == 0 and prefix.strip():
            root = Path(prefix.strip())
            for entry, _depth in _walk_bounded(root, 4):
                if entry.name == name and (entry.exists()):
                    return entry
    return None


def _decompiler_choice(
        context: dict | None = None) -> decision_pending.PendingDecision:
    """The exit-8 CHOICE (issue 202): the decompiler-lane decision is the ONLY
    user touchpoint of the decompiler face, and it is a choice."""
    return decision_pending.PendingDecision(
        decision_id="decompiler_lane",
        question=(
            "No local decompiler supply found (probed: PATH, mdfind, find "
            "bundle sweep, brew cask, known dirs, GHIDRA_HOME, ghidra dirs, "
            "ghidra/ida-pro-vm MCP). Choose the decompiler lane: "
            "install-local-ida (HUMAN-ONLY: license purchase), "
            "install-ghidra (agent-run #408 installer), or "
            "skip-decompiler-lane (static depth limited)."),
        kind=decision_pending.KIND_CHOICE,
        options=("install-local-ida", "install-ghidra",
                 "skip-decompiler-lane"),
        default=None,  # never a silent default (#448 must-ask)
        context=context or {},
    )


# The lane-conditional failure copy. Kept peer-equal (Ghidra and
# IDA are equals — never an "install IDA" order) and anchored on the
# init-gate tests pin the installer reference) — but phrased as the CHOICE
# it now is, not a blocker dump.
_DECOMPILER_NEITHER_DETAIL = (
    "No decompiler supply found (probed: PATH, mdfind, find bundle sweep, "
    "brew cask, known dirs, GHIDRA_HOME, ghidra dirs, ghidra/ida-pro-vm "
    "MCP) — this is a CHOICE, not a blocker: install-local-ida "
    "(HUMAN-ONLY: license purchase) / install-ghidra (#408 installer) / "
    "skip-decompiler-lane (static depth limited). Ghidra OR IDA — either "
    "satisfies this check when present."
)
_DECOMPILER_NEITHER_FIX = (
    "decompiler supply is LANE-CONDITIONAL (#202): MCP lane (task_spec "
    "tools.decompiler_lane: mcp) -> the gate verifies ida-pro-vm "
    "registration + reachability and registers it itself via "
    "`claude mcp add` — never a local IDA install; local lane -> the agent "
    "probe ladder runs (PATH, mdfind, find bundle sweep incl. "
    ".app/Contents/MacOS, brew cask, known dirs), then the Ghidra probe "
    "(GHIDRA_HOME, ghidra dirs, brew). Ghidra OR IDA — either satisfies "
    "this check when present; neither -> exit-8 PendingDecision CHOICE: "
    "install-local-ida (license) / install-ghidra (#408 installer) / "
    "skip-decompiler-lane"
)


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


def _check_decompiler_mcp_lane(report: ToolchainReport, ws: Path,
                               registered: dict[str, list[str]],
                               reqs: Requirements) -> None:
    """MCP lane (LANE-CONDITIONAL): the task declared the ida-pro-vm
    MCP lane — the face gates on registration + reachability and NEVER
    probes a local IDA install or license. Missing server -> the gate
    registers it itself (AGENT-DO, task_spec url) and re-verifies."""
    spec = next((s for s in reqs.required_mcp if s.name == "ida-pro-vm"),
                McpServerSpec(name="ida-pro-vm", transport="http"))
    claude_json = mcp_probe.claude_json_path()
    if "ida-pro-vm" not in registered:
        register = (f"claude mcp add --transport http ida-pro-vm {spec.url}"
                    if spec.url else
                    "claude mcp add --transport http ida-pro-vm <ida-mcp-url>"
                    " (the url comes from task_spec tools.mcp_servers)")
        detail = ("ida-pro-vm not registered (task declares the ida-pro-vm "
                  "MCP lane)")
        if _agent_do_enabled():
            argv = _concrete_register_argv(
                "claude mcp add --transport http ida-pro-vm <ida-mcp-url>",
                spec.url)
            if argv is not None:
                allowed, why = _mcp_register_attempt_allowed()
                if allowed:
                    ok, err = _attempt_mcp_register(argv)
                    attempts = (" ".join(argv),)
                    registered = mcp_probe.registered_names(claude_json, ws)
                    if "ida-pro-vm" in registered:
                        report.items.append(CheckResult(
                            name="decompiler", status=Status.PASS,
                            tier=Tier.HARD,
                            detail=("ida-pro-vm registered by agent "
                                    "(`claude mcp add --transport http`) — "
                                    "MCP lane, no local IDA involved"),
                            probe=ProbeTier.PRESENCE,
                            owner=OwnerTier.AGENT_DO, attempts=attempts,
                        ))
                        return
                    detail += f"; agent-do register attempt failed: {err}"
                    report.items.append(CheckResult(
                        name="decompiler", status=Status.FAIL,
                        tier=Tier.HARD, detail=detail, probe=ProbeTier.PRESENCE,
                        fix=("verify the ida-pro-vm endpoint is up, then "
                             "re-register: " + register),
                        attempts=attempts,
                    ))
                    return
        report.items.append(CheckResult(
            name="decompiler", status=Status.FAIL, tier=Tier.HARD,
            detail=detail, probe=ProbeTier.PRESENCE, fix=register,
        ))
        return
    url = spec.url or _mcp_server_url("ida-pro-vm", claude_json, ws)
    if url:
        parts = urllib.parse.urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        host = parts.hostname or "127.0.0.1"
        ok, err = _tcp_connect(host, port)
        if ok:
            report.items.append(CheckResult(
                name="decompiler", status=Status.PASS, tier=Tier.HARD,
                detail=(f"via MCP lane (ida-pro-vm) — registered + endpoint "
                        f"reachable ({host}:{port}); session capability "
                        f"unverified (tools register after connect_instance)"),
                probe=ProbeTier.LIVENESS,
            ))
            return
        report.items.append(CheckResult(
            name="decompiler", status=Status.FAIL, tier=Tier.HARD,
            detail=(f"ida-pro-vm registered but endpoint unreachable: {err} "
                    f"(url from task_spec/registry — bring the server up; "
                    f"never a local IDA install)"),
            probe=ProbeTier.LIVENESS,
            fix=("bring the ida-pro-vm endpoint up (task_spec "
                 "tools.mcp_servers url) — the lane is the MCP surface, "
                 "not a local IDA install"),
        ))
        return
    # registered, no url anywhere -> registry presence only (honesty)
    report.items.append(CheckResult(
        name="decompiler", status=Status.WARN, tier=Tier.HARD,
        detail=(f"via MCP lane (ida-pro-vm) — registered, {_UNVERIFIED} "
                f"(no endpoint url in task_spec or registry to probe)"),
        probe=ProbeTier.PRESENCE,
    ))


def _check_decompiler(report: ToolchainReport, ws: Path,
                      has_native_so: bool | None = None,
                      caps: bool = False,
                      reqs: Requirements = DEFAULT_REQUIREMENTS) -> None:
    """Append the decompiler availability check — LANE-CONDITIONAL (issue 202).

    Face branches on the task's declared lane (task_spec
    tools.decompiler_lane):
      - "mcp": ida-pro-vm registration + reachability. NEVER a local IDA
        install/license demand, never the local probe ladder.
      - "local": the ordered probe ladder (PATH -> mdfind -> find bundle
        sweep -> brew cask -> known dirs) -> PASS with the wired binary
        path; then the Ghidra probe -> PASS as Ghidra.
      - None (undeclared): the pre-rework combined behavior — MCP-first
        defusal, then the ladder; the ladder's found-hits now PASS (issue 202)
        with the probe strategy recorded.
      Neither found -> exit-8 PendingDecision CHOICE (install-local-ida /
      install-ghidra / skip-decompiler-lane) — the ONLY user touchpoint,
      and it is a choice, not a blocker dump.

    `has_native_so` keeps the android nuance: pure-DEX (False) keeps the
    WARN (no HARD blocker, no choice needed — the lane is freely skipped).
    """
    registered = mcp_probe.registered_names(mcp_probe.claude_json_path(), ws)

    if reqs.decompiler_lane == "mcp":
        _check_decompiler_mcp_lane(report, ws, registered, reqs)
        return

    # MCP-first supply defusal — undeclared lane only (a declared LOCAL
    # lane is decided by the probe ladder, never by MCP presence).
    if reqs.decompiler_lane is None:
        for name in _DECOMPILER_MCP_NAMES:
            if name in registered:
                report.items.append(CheckResult(
                    name="decompiler", status=Status.WARN, tier=Tier.HARD,
                    detail=f"via MCP ({name}) — registered, {_UNVERIFIED} "
                           f"(registry read only; a probe cannot reach the "
                           f"MCP session — tools register after "
                           f"connect_instance)",
                    probe=ProbeTier.LIVENESS,
                ))
                return

    # ---- local probe ladder (issue 202 + addendum) ----
    ida_path, strategy = _probe_local_ida()
    if ida_path:
        report.items.append(CheckResult(
            name="ida", status=Status.PASS, tier=Tier.HARD,
            detail=(f"idat64 at {ida_path} (probe: {strategy}) — wired: "
                    f"export PATH={ida_path.parent}:$PATH"),
            probe=ProbeTier.PRESENCE,
        ))
        return

    ah = _probe_ghidra()
    if ah:
        trial_note = ""
        probe = ProbeTier.PRESENCE
        if caps:
            ok, trial_detail = _capability_probe_ghidra(ah)
            trial_note = (f"; capability trial: {trial_detail}"
                          if ok else
                          f"; capability trial FAILED (presence PASS stands "
                          f"per #202): {trial_detail}")
            if ok:
                probe = ProbeTier.CAPABILITY
        report.items.append(CheckResult(
            name="ghidra", status=Status.PASS, tier=Tier.HARD,
            detail=f"analyzeHeadless at {ah} — Ghidra supplies the "
                   f"decompiler lane{trial_note}",
            probe=probe,
        ))
        return

    if has_native_so is False:
        # android pure-DEX: the lane is freely skippable — WARN, no choice
        report.items.append(CheckResult(
            name="decompiler", status=Status.WARN, tier=Tier.HARD,
            detail="No decompiler found (Ghidra, IDA, or a ghidra/ida-pro-vm "
                   "MCP registration satisfies this check) — WARN for "
                   "pure-DEX samples; HARD if the sample has .so "
                   "(see the #408 installer)",
            probe=ProbeTier.PRESENCE,
        ))
        return

    # Neither supply anywhere -> the exit-8 CHOICE.
    report.items.append(CheckResult(
        name="decompiler", status=Status.FAIL, tier=Tier.HARD,
        detail=_DECOMPILER_NEITHER_DETAIL,
        root_cause="decompiler" if has_native_so else None,
        probe=ProbeTier.PRESENCE,
        pending_decision=_decompiler_choice(),
    ))


# ---------- #449: env = f(task_spec) — needs-first requirements ----------

# The environment contract derives from the TASK, not the type template: a
# static-only task_spec must not HARD-require the VM channel (#449 evidence
# 2: 2026-08-17 transcript — task_spec unanswered while the full VM chain
# was already brought up). Conservative rule: every field the task_spec does
# not explicitly answer keeps its current HARD tier — an absent/unreadable
# task_spec is byte-identical to the pre-#449 gate.
TASK_SPEC_FILENAME = "task_spec.yaml"




def requirements_from_task_spec(task_spec: dict | None) -> Requirements:
    """Derive the environment requirement set from a parsed task_spec.

    Reads ONLY explicit task_spec fields: constraints.dynamic_re ("allowed"
    | "forbidden" — templates/state/task_spec.yaml, the master switch for
    emulation/Frida). "forbidden" = static-only → the VM channel is not
    needed. Anything else (absent, empty, non-mapping, garbage, "allowed")
    stays conservative: needs_vm=True, pre-#449 behavior.

    #25 D1 debug_flag: constraints.dynamic_re == "forbidden" implies no
    JDWP dynamics (static-only), and constraints.debug_flag: false is the
    explicit user-build opt-out (ro.debuggable=1 unreachable on Android 12+
    user builds; the dynamic plan runs via Magisk su without it). Only the
    exact YAML boolean false demotes — a string "false" or any other value
    stays conservative, the same rule dynamic_re applies to its vocabulary.

    primary_questions carry no env-relevant explicit field today (their
    `need:` enum says how to answer, not which environment to bring up);
    when one lands (#450+), it extends HERE, never at the checkers.
    vm_detonation ALONE does not relax (openspec issue-449 design R1): it
    forbids vmr-shell detonation only — frida-on-VM may still be the plan;
    the per-port contract is #450 env-facts scope.
    """
    if not isinstance(task_spec, dict):
        return DEFAULT_REQUIREMENTS
    needs_vm = True
    needs_debug_flag = True
    decompiler_lane: str | None = None
    required_mcp: tuple[McpServerSpec, ...] = ()
    required_mcp_declared = False
    basis = DEFAULT_REQUIREMENTS.basis
    tools = task_spec.get("tools")
    if isinstance(tools, dict):
        lane_raw = str(tools.get("decompiler_lane", "")).strip().lower()
        if lane_raw in ("mcp", "local"):
            decompiler_lane = lane_raw
        servers = tools.get("mcp_servers")
        if isinstance(servers, list):
            required_mcp_declared = True  # explicit declaration, even empty
            specs: list[McpServerSpec] = []
            for entry in servers:
                if isinstance(entry, str):
                    specs.append(McpServerSpec(name=entry.strip().lower()))
                elif isinstance(entry, dict) and entry.get("name"):
                    specs.append(McpServerSpec(
                        name=str(entry["name"]).strip().lower(),
                        transport=str(entry.get("transport", "stdio")).strip()
                        .lower() or "stdio",
                        url=(str(entry["url"]).strip()
                             if entry.get("url") else None)))
            required_mcp = tuple(specs)
    constraints = task_spec.get("constraints")
    if isinstance(constraints, dict):
        dynamic_re = str(constraints.get("dynamic_re", "")).strip().lower()
        if dynamic_re == "forbidden":
            needs_vm = False
            needs_debug_flag = False  # static-only: no JDWP dynamics either (#25 D1)
            basis = "task_spec constraints.dynamic_re=forbidden (static-only)"
        if constraints.get("debug_flag") is False:
            needs_debug_flag = False
            basis = ("task_spec constraints.debug_flag=false "
                     "(user build: JDWP flag not required)")
    if (needs_vm and needs_debug_flag and decompiler_lane is None
            and not required_mcp_declared):
        return DEFAULT_REQUIREMENTS
    return Requirements(needs_vm=needs_vm,
                        needs_debug_flag=needs_debug_flag,
                        decompiler_lane=decompiler_lane,
                        required_mcp=required_mcp,
                        required_mcp_declared=required_mcp_declared,
                        basis=basis)


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


def _channel_backend() -> tuple[str, str | None]:
    """(#698) Parse KUNGLAO_CHANNEL -> (backend, warn_note).

    unset/"vmr" -> vmr (default; pre-#698 behavior byte-identical). Known
    backends: ssh | docker | adb | local | mcp (#757: mcp = web normal-state
    channel — dynamic face is MCP/browser, no command control plane).
    Unknown value -> vmr fallback
    with a note naming the offending value (never crash on config noise).
    """
    raw = (_env_get("KUNGLAO_CHANNEL") or "").strip().lower()
    if raw in ("", "vmr"):
        return "vmr", None
    if raw in ("ssh", "docker", "adb", "local", "mcp"):
        return raw, None
    return "vmr", f"(unknown KUNGLAO_CHANNEL={raw!r} - falling back to vmr backend)"


def _ssh_base_args(vm_host: str) -> list[str]:
    """BatchMode ssh argv prefix shared by the ssh channel probes."""
    return ["ssh", "-p", str(VM_SHELL_PORT),
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
            vm_host]


def _docker_over_ssh_check(vm_host: str, container: str) -> tuple[bool, str]:
    """(#698) Optional docker execution target reached THROUGH the ssh
    channel: daemon reachable, then a real `docker exec <c> true`.
    Docker tri-state detail: daemon unreachable / container missing /
    exec rejected."""
    rc, out, err = _run_cmd([*_ssh_base_args(vm_host), "docker", "version"],
                            timeout=CHANNEL_CMD_TIMEOUT)
    if rc != 0:
        return False, (f"docker daemon unreachable (ssh docker version "
                       f"rc={rc}: {(err or out).strip()[:80] or 'no output'})")
    rc, out, err = _run_cmd([*_ssh_base_args(vm_host),
                             "docker", "exec", container, "true"],
                            timeout=CHANNEL_CMD_TIMEOUT)
    if rc != 0:
        blob = (err or out).lower()
        if "no such container" in blob or "no such object" in blob:
            return False, f"container missing ({container})"
        return False, (f"docker exec rejected (rc={rc}: "
                       f"{(err or out).strip()[:80] or 'no output'})")
    return True, ""


def _vm_probe_vmr(vm_host: str) -> tuple[bool, str, str, "ProbeTier"]:
    """vmr backend: dual-port TCP liveness - the pre-#698 logic verbatim
    (v6 'vmr unchanged'; PASS detail stays byte-identical, no backend tag)."""
    ok_shell, err_shell = _tcp_connect(vm_host, VM_SHELL_PORT)
    ok_frida, err_frida = _tcp_connect(vm_host, FRIDA_PORT)
    ok = ok_shell and ok_frida
    err = "; ".join(e for e in (err_shell, err_frida) if e)
    detail = f"VM {vm_host} reachable on {VM_SHELL_PORT}+{FRIDA_PORT}"
    return ok, detail, err, ProbeTier.LIVENESS


def _vm_probe_ssh(vm_host: str) -> tuple[bool, str, str, "ProbeTier"]:
    """ssh backend: CAPABILITY probe - TCP pre-check, then a real BatchMode
    `ssh ... true`. Tri-state detail: port unreachable / auth failed /
    channel dialect mismatch; frida port stays liveness; optional
    KUNGLAO_DOCKER_CONTAINER adds the docker-over-ssh check."""
    ok_shell, err_shell = _tcp_connect(vm_host, VM_SHELL_PORT)
    if not ok_shell:
        return False, "", f"port unreachable ({err_shell})", ProbeTier.CAPABILITY
    rc, out, err = _run_cmd([*_ssh_base_args(vm_host), "true"],
                            timeout=CHANNEL_CMD_TIMEOUT)
    if rc != 0:
        blob = (err or out or "").lower()
        if rc == 255 and "permission denied" in blob:
            return False, "", "auth failed (ssh rc=255, permission denied)", ProbeTier.CAPABILITY
        return False, "", (f"channel dialect mismatch (ssh rc={rc}: "
                           f"{(err or out).strip()[:100] or 'no output'})"), ProbeTier.CAPABILITY
    ok_frida, err_frida = _tcp_connect(vm_host, FRIDA_PORT)
    if not ok_frida:
        return False, "", f"ssh ok but frida port closed ({err_frida})", ProbeTier.CAPABILITY
    detail = (f"VM {vm_host} via ssh backend: shell exec ok "
              f"(port {VM_SHELL_PORT}, BatchMode) + frida liveness on {FRIDA_PORT}")
    container = _env_get("KUNGLAO_DOCKER_CONTAINER")
    if container:
        dok, derr = _docker_over_ssh_check(vm_host, container)
        if not dok:
            return False, "", f"docker: {derr}", ProbeTier.CAPABILITY
        detail += f"; docker exec {container} ok"
    return True, detail, "", ProbeTier.CAPABILITY


def _vm_probe_docker() -> tuple[bool, str, str, "ProbeTier"]:
    """docker backend: DIRECT channel - no ssh, no KUNGLAO_VM_HOST needed.
    `docker version` honors DOCKER_HOST (local socket or remote daemon);
    optional KUNGLAO_DOCKER_CONTAINER adds a real `docker exec <c> true`."""
    rc, out, err = _run_cmd(["docker", "version"], timeout=CHANNEL_CMD_TIMEOUT)
    if rc != 0:
        return False, "", (f"docker daemon unreachable (docker version "
                           f"rc={rc}: {(err or out).strip()[:80] or 'no output'})"), ProbeTier.CAPABILITY
    detail = "docker daemon reachable via docker backend (DOCKER_HOST honored)"
    container = _env_get("KUNGLAO_DOCKER_CONTAINER")
    if container:
        rc, out, err = _run_cmd(["docker", "exec", container, "true"],
                                timeout=CHANNEL_CMD_TIMEOUT)
        if rc != 0:
            blob = (err or out).lower()
            if "no such container" in blob or "no such object" in blob:
                return False, "", f"container missing ({container})", ProbeTier.CAPABILITY
            return False, "", (f"docker exec rejected (rc={rc}: "
                               f"{(err or out).strip()[:80] or 'no output'})"), ProbeTier.CAPABILITY
        detail += f"; docker exec {container} ok"
    return True, detail, "", ProbeTier.CAPABILITY


def _vm_probe_adb(vm_host: str | None = None) -> tuple[bool, str, str, "ProbeTier"]:
    """adb backend: real `adb devices` (device/emulator online) + frida
    liveness (KUNGLAO_VM_HOST or 127.0.0.1 - adb forward topology)."""
    rc, out, err = _run_cmd(["adb", "devices"], timeout=CHANNEL_CMD_TIMEOUT)
    if rc != 0:
        return False, "", (f"no device (adb devices rc={rc}: "
                           f"{(err or out).strip()[:80] or 'no output'})"), ProbeTier.CAPABILITY
    lines = [ln.strip() for ln in out.splitlines()[1:] if ln.strip()
             and not ln.strip().startswith("*")]
    online = [ln for ln in lines if ln.endswith("device")]
    unauthorized = [ln for ln in lines if "unauthorized" in ln]
    if not online and unauthorized:
        return False, "", ("unauthorized (adb devices shows unauthorized - "
                           "accept the debugging prompt on the device)"), ProbeTier.CAPABILITY
    if not online:
        return False, "", ("no device (adb devices empty - start the "
                           "emulator or plug the device in)"), ProbeTier.CAPABILITY
    fhost = vm_host or "127.0.0.1"
    ok_frida, err_frida = _tcp_connect(fhost, FRIDA_PORT)
    if not ok_frida:
        return False, "", (f"frida port closed ({err_frida}) - run "
                           f"`adb forward tcp:{FRIDA_PORT} tcp:{FRIDA_PORT}`"), ProbeTier.CAPABILITY
    serial = online[0].split()[0]
    return True, (f"VM via adb backend: {len(online)} device(s) online "
                  f"({serial}); frida liveness on {fhost}:{FRIDA_PORT}"), "", ProbeTier.CAPABILITY


# Per-backend fix guidance for a FAILED dynamic check (vmr keeps the #451
# inventory-driven fixes; remote backends get env-var-specific pointers).
_CHANNEL_FIXES: dict[str, str] = {
    "ssh": ("set KUNGLAO_VM_HOST=<remote host> and KUNGLAO_VM_SHELL_PORT; "
            "verify key auth (ssh -o BatchMode=yes <host> true); the "
            "execution layer is the ssh-mcp control plane (see README "
            "'Bring your own analysis environment')"),
    "docker": ("verify the docker daemon (docker version; set DOCKER_HOST "
               "for a remote daemon) and KUNGLAO_DOCKER_CONTAINER for the "
               "execution target"),
    "adb": ("start the emulator or plug the device (adb devices), accept "
            f"the debugging prompt, then `adb forward tcp:{FRIDA_PORT} "
            f"tcp:{FRIDA_PORT}` for frida"),
}


def _check_dynamic_channel(report: ToolchainReport,
                           reqs: Requirements = DEFAULT_REQUIREMENTS) -> None:
    """Dynamic-analysis control plane + remote-debugger cascade.

    #698 (arbitration v6): KUNGLAO_CHANNEL picks one of five first-class
    backends (vmr default | ssh | docker | adb | local) - the goal is to
    give the agent an EXECUTION CONTROL PLANE for dynamic debugging.
    needs-aware x channel matrix (design D3):
      * static-only task, ANY channel -> whole block WARN, zero probe
        subprocesses ("dynamic channel unchecked (static-only task)";
        local says "local static-only channel").
      * dynamic task + local -> HARD policy reject, no probes.
      * dynamic task + vmr/ssh/docker/adb -> HARD probe (vmr liveness
        byte-identical to pre-#698; ssh/docker/adb capability level).

    #449 downgrade semantics preserved: capability absence is REPORTED
    (WARN with the task_spec basis), never silently skipped. Absent/
    unreadable task_spec keeps the HARD status quo byte-identical.

    Android has NO VM channel by design (#455: dynamics go through ADB +
    device services; NEVER_CHECKS pins it) - windows/linux only.
    """
    backend, chan_warn = _channel_backend()
    vm_host = _env_get("KUNGLAO_VM_HOST")

    # ---- mcp (#757): browser/MCP dynamic face, no command control plane
    # Desktop dynamic RE cannot execute through an MCP channel yet (#698 D5
    # execution layer is declarative); zero probes, fail-closed (D9).
    # Static-only tasks fall through to the generic zero-probe WARN row.
    if backend == "mcp" and reqs.needs_vm:
        _mcp_detail = ("mcp channel provides no command control plane for "
                       "desktop dynamic analysis — switch KUNGLAO_CHANNEL "
                       "to vmr/ssh/docker/adb")
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.FAIL, tier=Tier.HARD,
            detail=_mcp_detail,
            root_cause="VM", probe=ProbeTier.PRESENCE,
        ))
        report.items.append(CheckResult(
            name="remote_debugger", status=Status.FAIL, tier=Tier.HARD,
            detail=_mcp_detail,
            root_cause="VM", probe=ProbeTier.PRESENCE,
        ))
        return

    # ---- local: policy channel, never probes -------------------------
    if backend == "local":
        if reqs.needs_vm:
            report.items.append(CheckResult(
                name="vm_reachable", status=Status.FAIL, tier=Tier.HARD,
                detail=("local channel forbids dynamic analysis — switch "
                        "KUNGLAO_CHANNEL to vmr/ssh/docker/adb"),
                root_cause="VM", probe=ProbeTier.PRESENCE,
            ))
            report.items.append(CheckResult(
                name="remote_debugger", status=Status.FAIL, tier=Tier.HARD,
                detail=("Remote debugger unavailable (local channel "
                        "forbids dynamic analysis)"),
                root_cause="VM", probe=ProbeTier.PRESENCE,
            ))
        else:
            report.items.append(CheckResult(
                name="vm_reachable", status=Status.WARN, tier=Tier.WARN,
                detail=(f"local static-only channel - not required by "
                        f"task_spec ({reqs.basis})"),
                probe=ProbeTier.PRESENCE,
            ))
            report.items.append(CheckResult(
                name="remote_debugger", status=Status.WARN, tier=Tier.WARN,
                detail=(f"local static-only channel - not required by "
                        f"task_spec ({reqs.basis})"),
                probe=ProbeTier.PRESENCE,
            ))
        return

    # ---- static-only: WARN contract, zero probes ----------------------
    if not reqs.needs_vm:
        detail = (f"VM unreachable: dynamic channel unchecked (static-only "
                  f"task) - not required by task_spec ({reqs.basis})")
        if chan_warn:
            detail += f" {chan_warn}"
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.WARN, tier=Tier.WARN,
            detail=detail, probe=ProbeTier.LIVENESS,
        ))
        report.items.append(CheckResult(
            name="remote_debugger", status=Status.WARN, tier=Tier.WARN,
            detail=("VM unreachable - remote debugger unprobed; not required "
                    f"by task_spec ({reqs.basis})"),
            probe=ProbeTier.LIVENESS,
        ))
        return

    # ---- dynamic task, remote backend: HARD probe ---------------------
    vm_next: NextAction | None = None
    if backend == "vmr":
        if not vm_host:
            vm_ok, vm_err = False, "KUNGLAO_VM_HOST unset"
            probe_tier = ProbeTier.LIVENESS
            pass_detail = ""
        else:
            vm_ok, pass_detail, vm_err, probe_tier = _vm_probe_vmr(vm_host)
    elif backend == "ssh":
        if not vm_host:
            vm_ok, vm_err = False, ("KUNGLAO_VM_HOST unset (ssh backend "
                                    "needs the remote host)")
            probe_tier = ProbeTier.CAPABILITY
            pass_detail = ""
        else:
            vm_ok, pass_detail, vm_err, probe_tier = _vm_probe_ssh(vm_host)
    elif backend == "docker":
        vm_ok, pass_detail, vm_err, probe_tier = _vm_probe_docker()
    else:  # adb
        vm_ok, pass_detail, vm_err, probe_tier = _vm_probe_adb(vm_host)

    if vm_ok:
        detail = pass_detail
        if chan_warn:
            detail += f" {chan_warn}"
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.PASS,
            tier=Tier.HARD, detail=detail, probe=probe_tier,
        ))
    elif backend == "vmr":
        # #451 inventory-driven FAIL surface - vmr only, byte-identical.
        detail, fix, vm_next = _vm_fail_fixes(vm_host, vm_err)
        if chan_warn:
            detail += "\n" + chan_warn
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.FAIL, tier=Tier.HARD,
            detail=detail,
            root_cause="VM", probe=probe_tier,
            fix=fix, next_action=vm_next,
        ))
    else:
        detail = (f"dynamic channel failed via {backend} backend: {vm_err}")
        if chan_warn:
            detail += f" {chan_warn}"
        report.items.append(CheckResult(
            name="vm_reachable", status=Status.FAIL, tier=Tier.HARD,
            detail=detail, root_cause="VM", probe=probe_tier,
            fix=_CHANNEL_FIXES[backend],
        ))

    # T2: remote debugger (x64dbg/ida_server/frida-server | gdbserver/
    # linux_server64/frida-server) - cascade from the channel
    if not vm_ok:
        report.items.append(CheckResult(
            name="remote_debugger", status=Status.FAIL, tier=Tier.HARD,
            detail="Remote debugger unreachable (VM not reachable)",
            root_cause="VM", probe=probe_tier,
            # #451: the cascade shares the channel's next_action - its
            # root cause is the channel (fix the root cause first)
            next_action=vm_next,
        ))
    else:
        # Would need actual VM-side probing - mark as WARN if can't verify
        report.items.append(CheckResult(
            name="remote_debugger", status=Status.WARN, tier=Tier.HARD,
            detail="VM reachable; remote debugger presence not verified",
            probe=probe_tier,
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
    _check_uv(report)
    _check_decompiler(report, ws, caps=caps, reqs=reqs)

    # T2: VM channel (vmr-shell 9876 + frida 1337 + remote-debugger
    # cascade) — shared helper; #449 env = f(task_spec): static-only
    # task_spec downgrades the pair to WARN (basis in the detail).
    _check_dynamic_channel(report, reqs)

    # T2: Docker (WARN)
    report.items.extend(_which_items(
        ("docker",), Tier.WARN,
        missing_status=Status.WARN,
        missing_detail="docker not found (optional)",
        found_detail="docker at {path}"))

    # #316: MCP supply (registry: ~/.claude.json + workspace .mcp.json)
    _check_mcp(report, ws, "windows", reqs=reqs)


# ---------- Linux manifest ----------

def _check_linux(report: ToolchainReport, ws: Path,
                 caps: bool = False,
                 reqs: Requirements = DEFAULT_REQUIREMENTS) -> None:
    """Linux toolchain checks (ELF)."""
    # T0: venv + binutils (file/readelf/objdump)
    report.items.extend(_which_items(
        ("file", "readelf", "objdump"), Tier.HARD))

    # T1: Ghidra or IDA (#407: MCP-first, CLI fallback — one shared helper;
    # #474: three-state honest, caps plumbs the capability trial)
    _check_uv(report)
    _check_decompiler(report, ws, caps=caps, reqs=reqs)

    # T2: VM channel (vmr-shell 9876 + frida 1337 + remote-debugger
    # cascade) — shared helper; #449 env = f(task_spec): static-only
    # task_spec downgrades the pair to WARN (basis in the detail).
    _check_dynamic_channel(report, reqs)

    # T2: Docker (WARN)
    report.items.extend(_which_items(
        ("docker",), Tier.WARN,
        missing_status=Status.WARN,
        missing_detail="docker not found (optional)",
        found_detail="docker at {path}"))

    # #316: MCP supply (registry: ~/.claude.json + workspace .mcp.json)
    _check_mcp(report, ws, "linux", reqs=reqs)

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

    #449: `reqs` is accepted for checker-signature uniformity — android's
    VM-face has nothing to relax (its dynamic contract is the ADB channel,
    device-side services, not the VMware/VBox VM channel (#455;
    NEVER_CHECKS)). #25 D1 wires the ONE android relaxation that exists:
    the debug_flag gate downgrades FAIL -> WARN when the task does not
    need the JDWP flag (reqs.needs_debug_flag False — static-only, or the
    explicit constraints.debug_flag=false opt-out); the basis rides into
    the detail. The default path is byte-identical to the pre-#25 gate."""
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
    report.items.extend(_which_items(
        ("jadx", "apktool"), Tier.HARD))

    # T1: apkid — presence probe ONLY, WARN tier (so it can never enter the
    # HARD exit-4 refusal set). apkid is a TOOL: init probes existence and
    # surfaces the first-claim recommendation; the agent decides whether or
    # when to run it (init never executes the scanner — issue 669 ruling).
    # The recommendation rides every apkid item's detail verbatim so the
    # init summary face and the intake promise mirror one source phrase.
    # missing_status is explicit: the _which_items default compares a Tier
    # against a Status enum, which never compares equal across classes.
    apkid_items = _which_items(("apkid",), Tier.WARN,
                               missing_status=Status.WARN)
    for apkid_item in apkid_items:
        apkid_item.detail += (" — apkid recommended for apk fingerprinting "
                              "(packer / obfuscator / anti-*); agent to run "
                              "on first claim")
    report.items.extend(apkid_items)

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
    _check_uv(report)
    _check_decompiler(report, ws, has_native_so=_probe_native_so(ws),
                      caps=caps, reqs=reqs)

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

    # T2: device root (cascades from ADB) — rooting itself stays HUMAN-ONLY
    # (physical device decision); the CHECK is an agent adb attempt.
    rooted = False
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
        rooted = rc == 0 and "uid=0" in out
        if rooted:
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
    # #25 D1: ro.debuggable=1 is unreachable on Android 12+ user builds
    # (SELinux property_service lock) while frida/android_server run fine
    # via Magisk su — when the task does not need the flag
    # (reqs.needs_debug_flag False), a miss downgrades FAIL -> WARN with
    # the task_spec basis in the detail (reported, never silently skipped;
    # the #449 VM-downgrade contract). The default path stays byte-identical.
    flag_optional = not reqs.needs_debug_flag
    if not adb_ok:
        detail = "Cannot check debug flag — ADB unavailable"
        if flag_optional:
            detail += f" — not required by task_spec ({reqs.basis})"
        report.items.append(CheckResult(
            name="debug_flag",
            status=Status.WARN if flag_optional else Status.FAIL,
            tier=Tier.WARN if flag_optional else Tier.HARD,
            detail=detail,
            root_cause=None if flag_optional else "ADB",
        ))
    else:
        assert adb  # noqa: S101 — adb is set when adb_ok is True
        rc, out, err = _run_cmd([adb, "shell", "getprop", "ro.debuggable"],
                                timeout=10)
        debuggable = out.strip() if rc == 0 else ""
        # AGENT-DO: on a ROOTED device an unset flag is set by the gate
        # itself (`su -c resetprop`), then read back — the user is never
        # handed the command. Attempts fire only when the task needs the
        # flag and AGENT-DO is enabled; failures escalate WITH the error.
        attempts: tuple[str, ...] = ()
        flag_attempt_error = ""
        flag_handled = False
        if (debuggable != "1" and rooted and _agent_do_enabled()
                and not flag_optional):
            set_argv = [adb, "shell", "su", "-c", "resetprop ro.debuggable 1"]
            rc2, out2, err2 = _run_cmd(set_argv, timeout=10)
            attempts = (" ".join(set_argv),)
            rc, out, err = _run_cmd(
                [adb, "shell", "getprop", "ro.debuggable"], timeout=10)
            debuggable = out.strip() if rc == 0 else ""
            if debuggable == "1":
                flag_handled = True
                report.items.append(CheckResult(
                    name="debug_flag", status=Status.PASS, tier=Tier.HARD,
                    detail=("AGENT-DO: ro.debuggable=1 set via "
                            "`su -c resetprop ro.debuggable 1` (read-back "
                            "verified)"),
                    probe=ProbeTier.CAPABILITY, attempts=attempts,
                ))
            else:
                flag_attempt_error = (err2 or out2 or f"rc={rc2}")
        if flag_handled:
            pass  # AGENT-DO PASS already appended
        elif debuggable == "1":
            report.items.append(CheckResult(
                name="debug_flag", status=Status.PASS, tier=Tier.HARD,
                detail="ro.debuggable=1 — debug flag set (read back verified)",
                probe=ProbeTier.CAPABILITY,
            ))
        else:
            detail = (f"debug flag not set (ro.debuggable="
                      f"{debuggable or 'unreadable'}; {err or out[:60]})")
            if flag_optional:
                detail += f" — not required by task_spec ({reqs.basis})"
            else:
                detail += " — required for Android dynamic analysis"
            if flag_attempt_error:
                detail += (f"; AGENT-DO resetprop attempt failed: "
                           f"{flag_attempt_error}")
            report.items.append(CheckResult(
                name="debug_flag",
                status=Status.WARN if flag_optional else Status.FAIL,
                tier=Tier.WARN if flag_optional else Tier.HARD,
                detail=detail,
                root_cause=None if flag_optional else "debug_flag",
                probe=ProbeTier.CAPABILITY,
                attempts=attempts,
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
        # AGENT-DO: bring-up is agent work — the gate looks for a
        # (renamed) frida binary on the device, starts it on the custom
        # port over su, re-forwards and re-probes. Escalates with the
        # attempt evidence only on genuine failure.
        attempts: tuple[str, ...] = ()
        if not ok and _agent_do_enabled() and rooted:
            ok, detail, attempts = _agent_do_device_bringup(
                adb, FRIDA_PORT, name_hint="frida")
        if ok:
            note = (" — AGENT-DO bring-up" if attempts else "")
            report.items.append(CheckResult(
                name="frida_server", status=Status.PASS, tier=Tier.HARD,
                detail=f"frida-server reachable on custom port {FRIDA_PORT} "
                       f"(renamed binary verified by port){note}",
                probe=ProbeTier.LIVENESS, attempts=attempts,
            ))
        else:
            if attempts:
                detail += ("; AGENT-DO bring-up attempt did not bring the "
                           "port up")
            report.items.append(CheckResult(
                name="frida_server", status=Status.FAIL, tier=Tier.HARD,
                detail=f"frida-server NOT verified on custom port {FRIDA_PORT}: {detail} — "
                       f"must run a RENAMED binary on the custom port "
                       f"(default name/port 27042 is detected by samples)",
                root_cause="frida_server", probe=ProbeTier.LIVENESS,
                attempts=attempts,
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
        # AGENT-DO: same bring-up shape as frida-server (gserver).
        attempts: tuple[str, ...] = ()
        if not ok and _agent_do_enabled() and rooted:
            ok, detail, attempts = _agent_do_device_bringup(
                adb, ANDROID_SERVER_PORT, name_hint="android_server")
        if ok:
            note = (" — AGENT-DO bring-up" if attempts else "")
            report.items.append(CheckResult(
                name="android_server", status=Status.PASS, tier=Tier.HARD,
                detail=f"android_server listening on device port {ANDROID_SERVER_PORT} "
                       f"(via adb forward){note}",
                probe=ProbeTier.LIVENESS, attempts=attempts,
            ))
        else:
            if attempts:
                detail += ("; AGENT-DO bring-up attempt did not bring the "
                           "port up")
            report.items.append(CheckResult(
                name="android_server", status=Status.FAIL, tier=Tier.HARD,
                detail=f"android_server NOT verified on port {ANDROID_SERVER_PORT}: {detail} — "
                       f"adb push android_server to the device and run it",
                root_cause="android_server", probe=ProbeTier.LIVENESS,
                attempts=attempts,
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
    _check_mcp(report, ws, "android", reqs=reqs)


# ---------- Web manifest (#728, labs: WARN-only) ----------

def _check_web(report: ToolchainReport, ws: Path,
               caps: bool = False,
               reqs: Requirements = DEFAULT_REQUIREMENTS) -> None:
    """#728 web (labs) checks — minimal face, ZERO HARD items by contract
    (labs: no robust toolchain validation; real-usage follow-up).

    - camoufox-reverse MCP supply (WARN — mcp_probe manifest entry)
    - docker channel presence (WARN; the web channel default is docker,
      #698 owns the channel matrix itself)
    No VM channel, no decompiler, no caps path — the web dynamic surface is
    the browser, not a VM."""
    _check_mcp(report, ws, "web", reqs=reqs)

    docker = _shutil_which("docker")
    if docker:
        rc, out, err = _run_cmd(["docker", "--version"], timeout=10)
        detail = (f"docker present ({out.strip()[:60] or err.strip()[:60]})"
                  if rc == 0 else f"docker binary found but --version rc={rc}")
        status = Status.PASS if rc == 0 else Status.WARN
    else:
        status = Status.WARN
        detail = ("docker not on PATH — web channel default is docker; "
                  "install Docker Desktop or set KUNGLAO_CHANNEL explicitly")
    report.items.append(CheckResult(
        name="channel:docker", status=status, tier=Tier.WARN,
        detail=detail, probe=ProbeTier.PRESENCE,
    ))


# ---------- macOS manifest (#760, labs: WARN-only) ----------

def _check_macos(report: ToolchainReport, ws: Path,
                 caps: bool = False,
                 reqs: Requirements = DEFAULT_REQUIREMENTS) -> None:
    """#760 macos (labs) checks — minimal Mach-O face, ZERO HARD items by
    contract (labs semantics, same shape as #728 web).

    - otool / class-dump / swift-demangle presence probes (WARN — the static
      Mach-O toolset; class-dump is a manual build, never auto-installed)
    - Darwin runtime note (WARN): dynamic analysis needs a Darwin host;
      non-Darwin analysis hosts keep the STATIC face without blocking
    No VM channel (NEVER_CHECKS pins vm_reachable/remote_debugger absence —
    the #698 channel matrix belongs to windows/linux), no caps path."""
    for tool in ("otool", "class-dump", "swift-demangle"):
        path = _shutil_which(tool)
        if path:
            report.items.append(CheckResult(
                name=tool, status=Status.PASS, tier=Tier.WARN,
                detail=f"found at {path}", probe=ProbeTier.PRESENCE,
            ))
        else:
            report.items.append(CheckResult(
                name=tool, status=Status.WARN, tier=Tier.WARN,
                detail=(f"{tool} not on PATH (Xcode CLT via `xcode-select "
                        f"--install`; class-dump is a manual build)"),
                probe=ProbeTier.PRESENCE,
            ))

    darwin = sys.platform == "darwin"
    report.items.append(CheckResult(
        name="darwin_runtime", status=Status.PASS if darwin else Status.WARN,
        tier=Tier.WARN,
        detail=("Darwin host — Mach-O dynamic surface available" if darwin
                else f"host is {sys.platform} — Mach-O DYNAMIC analysis needs "
                     "a Darwin environment; the static face still works "
                     "(not blocking, labs WARN tier)"),
        probe=ProbeTier.PRESENCE,
    ))


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
        "pefile", "die", "floss", "decompiler", "ghidra", "ida", "uv",
        "vm_reachable", "remote_debugger", "docker",
    }),
    "linux": frozenset({
        "file", "readelf", "objdump", "decompiler", "ghidra", "ida", "uv",
        "vm_reachable", "remote_debugger", "docker", "gdbserver",
        "ebpf", "strace", "ltrace",
    }),
    "android": frozenset({
        "aapt", "aapt2", "jadx", "apktool", "gitnexus",
        "decompiler", "ghidra", "ida", "uv",
        "adb", "device_root", "debug_flag", "frida_server",
        "android_server", "jdwp_debug", "ebpf_android", "unidbg",
    }),
    # #760: labs Mach-O face (WARN-only; mirrors the web labs posture)
    "macos": frozenset({
        "otool", "class-dump", "swift-demangle", "darwin_runtime",
    }),
}

# The explicit negative declaration: items a type must NEVER produce.
# Regression-pinned by tests/test_target_alignment.py (#455 checkbox 4).
NEVER_CHECKS: dict[str, frozenset[str]] = {
    "android": frozenset({"vm_reachable", "remote_debugger"}),
    # #760: the VM channel is the windows/linux contract; a macOS workspace
    # runs dynamics natively on a Darwin host, never through vmr-shell.
    "macos": frozenset({"vm_reachable", "remote_debugger"}),
}

# ---------- report formatting ----------

def _next_action_json(item: CheckResult) -> dict | None:
    """--json rendering of a FAIL item's next_action (None otherwise)."""
    if item.status != Status.FAIL:
        return None
    na = next_action_for(item)
    if na is None:
        return None
    return {"action": na.action, "command": na.command,
            "options": list(na.options)}


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
        # ownership rides every non-PASS line (who owns the fix).
        if item.status != Status.PASS:
            lines.append(f"      owner: {item.owner.value}")
        if item.status != Status.PASS and (item.fix or item.name in FIXES):
            lines.append(f"      fix: {item.fix or FIXES[item.name]}")
            # #680: structured metadata supplements the fix prose — the
            # upstream URL on its OWN line (never inline, never fabricated:
            # url=None -> line omitted) + the verify command when present.
            meta = FIXES.get(item.name)
            if meta is not None:
                if meta.url:
                    lines.append(f"      url: {meta.url}")
                if meta.verify_cmd:
                    lines.append(f"      verify: {meta.verify_cmd}")
        # AGENT-DO attempt evidence — the human sees what the agent
        # already tried, never a bare command dump.
        for attempt in item.attempts:
            lines.append(f"      attempted: {attempt}")
        # #451: machine-parseable key-value lines — anchored prefixes the
        # negotiation consumers grep for (never part of detail/fix prose).
        if item.status == Status.FAIL:
            na = next_action_for(item)
            if na is not None:
                lines.append(f"      action: {na.action}")
                if na.command:
                    lines.append(f"      command: {na.command}")
                for i, opt in enumerate(na.options, 1):
                    lines.append(f"      option {i}: {opt}")
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
                "owner": i.owner.value,  # #202: agent_do|human_only|lane_conditional
                "detail": i.detail,
                "root_cause": i.root_cause,
                "fix": (i.fix or fix_text(i.name))
                       if i.status != Status.PASS else None,
                # #680: fix stays the TEXT (schema stability); fix_url is
                # additive — null when unknown (mcp:*, PASS items).
                "fix_url": (FIXES[i.name].url
                            if i.status != Status.PASS and i.name in FIXES
                            else None),
                "next_action": _next_action_json(i),  # #451
                # AGENT-DO attempt evidence + pending CHOICE
                "attempts": list(i.attempts),
                "pending_decision": (
                    dataclasses.asdict(i.pending_decision)
                    if i.pending_decision is not None else None),
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


def _report_pending(report: ToolchainReport) -> bool:
    """True when the report carries at least one pending CHOICE item (issue 202)."""
    return any(i.pending_decision is not None for i in report.items)


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
        "web": _check_web,
        "macos": _check_macos,
    }
    checkers[project_type](report, ws, caps=caps, reqs=reqs)
    # single-point owner stamping — every item leaves the gate with
    # its ownership tier (rebuilt items, no in-place mutation).
    report.items = [dataclasses.replace(i, owner=owner_for(i.name))
                    for i in report.items]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="toolchain",
        description="Type-aware toolchain probe matrix",
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
                             "only)")
    args = parser.parse_args(argv)

    ws = Path(args.workspace).resolve()
    # #449 needs-first: consume <ws>/task_spec.yaml when present; garbage
    # never relaxes anything — warn + conservative HARD (pre-#449 tiers).
    try:
        task_spec = load_task_spec(ws)
    except ValueError as exc:
        print(f"WARNING: {exc} — toolchain layers stay conservative HARD "
              f"(fix task_spec.yaml at needs-first intake)",
              file=sys.stderr)
        task_spec = None
    try:
        report = check(ws, args.type, caps=args.capability,
                       task_spec=task_spec)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # the decompiler-lane CHOICE is the gate's only user touchpoint —
    # when it is the SOLE blocker, the pending doc IS the stdout
    # machine channel (a second JSON doc would break parsers) and the human
    # report moves to stderr; a mixed report keeps exit 1 with the choice
    # riding in the --json surface for the agent layer to relay.
    pending = [i.pending_decision for i in report.items
               if i.pending_decision is not None]
    blocking = [i for i in report.items
                if i.status is Status.FAIL and i.tier is Tier.HARD
                and i.pending_decision is None]
    if pending and not blocking:
        doc = decision_pending.build_pending_doc(
            flow="toolchain", workspace=str(ws),
            guidance=decision_pending.GUIDANCE_TEMPLATE, decisions=pending)
        print(format_human(report), file=sys.stderr)
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return 8

    if args.json:
        print(format_json(report))
    elif args.reproduce:
        print(format_reproduce(report)
              + (" pending=decompiler_lane" if _report_pending(report) else ""))
    else:
        print(format_human(report))

    return report.exit_code


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())


# ---------- #588/#590: Phase "-1" quick presence + preconditions group ----------

# PRESENCE-tier binaries only (shutil.which, ~0ms each — no subprocess, no
# network): the banner answers "is this host even shaped like an RE host?"
# seconds into init, BEFORE the step-0 intake conversation (#588's O(hours)
# → O(seconds) fix). It NEVER adopts values or downgrades anything — #449
# needs-first precedence is untouched; step-5's full-tier check stands.
_PRESENCE_PROBES = ("uv", "python3", "git", "ghidra", "jadx", "adb", "frida")


def quick_presence(ws: Path) -> str:
    """#588: O(seconds) host-health banner for the pre-intake phase.

    Pure PRESENCE tier: which() lookups only. Never raises — a broken host
    gets an honest all-missing banner, not a crash."""
    import shutil
    try:
        found, missing = [], []
        for binname in _PRESENCE_PROBES:
            (found if shutil.which(binname) else missing).append(binname)
        parts = [f"host presence: {len(found)}/{len(_PRESENCE_PROBES)}"]
        if found:
            parts.append("found: " + ", ".join(found))
        if missing:
            parts.append("MISSING: " + ", ".join(missing))
        return " | ".join(parts) + "  (PRESENCE only — full tiers run at step 5)"
    except Exception:
        return "host presence: probe unavailable (PRESENCE only — step 5 decides)"


def preconditions_questions(ws: Path | None = None) -> list[dict]:
    """#590: the hidden-assumption question group, riding the SAME native
    decision round as workspace/type (#455 shape). Probe findings attach as
    decision CONTEXT only — `pending` is the floor; the probe never
    auto-fills an answer (precedence: explicit > resolve > persisted >
    pending, decision_pending.py contract)."""
    context: dict = {"note": "probe findings are CONTEXT, not answers"}
    if ws is not None:
        try:
            context["presence_banner"] = quick_presence(ws)
        except Exception:
            context["presence_banner"] = None
    return [{
        "id": "preconditions",
        "question": ("Host/device preconditions: analysis device availability, "
                     "VM host (KUNGLAO_VM_HOST), GHIDRA_HOME, VM guest OS "
                     "matching the sample's project type, MCP supply state"),
        "context": context,
    }]
