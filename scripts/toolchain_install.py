#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolchain_install.py — #408 ask-then-install installer for kunglao-init.

kunglao-init currently refuses (exit 4) on missing tools with only textual
FIXES guidance (#304 "human-install event"). This module turns that refusal
into an interactive "install X?" flow:

  - per-item install commands assembled from (manager, package) DATA x
    LIVE DETECTION (#477 ①: pkg_detect — winget/choco/scoop/brew/apt/
    dnf/apk/pacman/pip/uv/npm; the sys.platform hardcode is gone)
  - INSTALL_PLANS covers the auto-installable check surface 17-fold
    (#477 ②; the rest is declared NOT_AUTO_INSTALLABLE with reasons)
  - consent prompt (safe decline on non-TTY stdin; --assume-yes for CI)
  - after a successful install: register the related MCP (ghidra bridge)
    and RE-PROBE via toolchain.check — PASS is required before continuing
    — and record the outcome in <ws>/env-facts.yaml's installed ledger
    (#477 ④ unified loop; #450 facts file)
  - on decline or install failure: print the official guidance and DEGRADE
    that item (WARN where static analysis proceeds; HARD only where it
    cannot — the decompiler)

#304 safety preserved: no silent sudo (needs_sudo managers print the
exact sudo-prefixed command for the human), no system-wide auto-install
without explicit consent, IDA never auto-installed.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Per repo convention, inject scripts/ into sys.path before importing sibling
# modules (compatible with `python -m` style invocations).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import toolchain  # noqa: E402  (#304 toolchain probes — re-probe after install)
import env_manifest  # noqa: E402  (#450 facts file — installed ledger, #477 ④)
import pkg_detect  # noqa: E402  (#477 ① manager detection + half-state)


def _ensure_utf8_stderr(stream=None) -> bool:
    """#451 乱码 fix: stderr unified to utf-8/replace (stdout already is).

    A GBK-default stderr next to a utf-8 stdout garbles the mixed terminal
    stream (2026-08-17 transcript). Fail-open on streams without
    reconfigure (returns False, never raises)."""
    target = sys.stderr if stream is None else stream
    reconfigure = getattr(target, "reconfigure", None)
    if reconfigure is None:
        return False
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        return False
    return True


_ensure_utf8_stderr(sys.stderr)

# Seam for tests: subprocess.run is accessed via this private name so tests
# can assert the exact argv without executing real installs.
_subprocess_run = subprocess.run


@dataclass(frozen=True)
class PkgSpec:
    """#477 ①: how ONE manager installs ONE tool — the install plan is
    (manager, argv) DATA (order = preference), not a sys.platform-keyed
    command. Resolution picks the first spec whose manager is DETECTED
    (pkg_detect), so a winget-only Windows never suggests choco and an
    unpacked ghidra never gets a reinstall suggestion."""

    manager: str              # key into pkg_detect.MANAGERS
    argv: tuple[str, ...]     # full argv for that manager


@dataclass(frozen=True)
class InstallPlan:
    """One auto-installable (or MCP-register-only) toolchain item.

    - kind: "auto" executes install commands; "mcp_url" never installs a
      product — it registers an existing MCP URL on consent (IDA).
    - degrade: what a decline/install-failure means for the item —
      "WARN" (static analysis proceeds degraded) or "HARD" (blocking).
    - packages: (manager, argv) data, declaration order = preference
      (#477: same item, many managers; the platform hardcode is gone).
      needs_sudo managers (apt/dnf/apk/pacman) are never auto-executed
      (#304) — the exact sudo-prefixed command is printed for the human.
    - mcp_register: "ghidra" -> register the bridge after install.
    """

    kind: str                                  # "auto" | "mcp_url"
    degrade: str                               # "WARN" | "HARD"
    packages: tuple[PkgSpec, ...] = ()         # per-manager install data
    mcp_register: str | None = None            # "ghidra" bridge after install


# Per-item install plans (#408; #477 ② coverage 5 -> 17). Keyed by
# toolchain.py check item name. Package names are real distro packages
# only — a manager without a real package for the tool is simply absent
# (honest data; an unresolvable item falls to manual guidance, never a
# fabricated command).
#   Python items     -> pip / uv
#   RE system tools  -> winget / choco / brew
#   Linux families   -> apt / dnf / apk / pacman (needs_sudo — #304)
#   decompiler       -> the Ghidra path (auto) — pkg installs + MCP
#                       bridge registration; IDA is the mcp_url path
#   ida              -> NEVER auto-installed; operator supplies the
#                       existing MCP URL (claude mcp add --transport http)
INSTALL_PLANS: dict[str, InstallPlan] = {
    # --- T0 Python packages ---
    "pefile": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("pip", ("pip", "install", "pefile")),
            PkgSpec("uv", ("uv", "pip", "install", "pefile")),
        ),
    ),
    "floss": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("pip", ("pip", "install", "flare-floss")),
            PkgSpec("uv", ("uv", "pip", "install", "flare-floss")),
        ),
    ),
    # --- T0/T1 RE system tools ---
    "die": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("choco", ("choco", "install", "die", "-y")),
            PkgSpec("brew", ("brew", "install", "die")),
            PkgSpec("apt", ("apt-get", "install", "-y", "die")),
            PkgSpec("dnf", ("dnf", "install", "-y", "die")),
            PkgSpec("apk", ("apk", "add", "die")),
            PkgSpec("pacman", ("pacman", "-S", "--noconfirm", "die")),
        ),
    ),
    "decompiler": InstallPlan(
        kind="auto", degrade="HARD",
        packages=(
            PkgSpec("choco", ("choco", "install", "ghidra", "-y")),
            PkgSpec("brew", ("brew", "install", "--cask", "ghidra")),
            PkgSpec("apt", ("apt-get", "install", "-y", "ghidra")),
        ),
        mcp_register="ghidra",
    ),
    "ida": InstallPlan(
        kind="mcp_url", degrade="WARN", packages=(),
    ),
    # --- binutils family (linux manifest) ---
    "file": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("choco", ("choco", "install", "file", "-y")),
            PkgSpec("brew", ("brew", "install", "file")),
            PkgSpec("apt", ("apt-get", "install", "-y", "file")),
            PkgSpec("dnf", ("dnf", "install", "-y", "file")),
            PkgSpec("apk", ("apk", "add", "file")),
            PkgSpec("pacman", ("pacman", "-S", "--noconfirm", "file")),
        ),
    ),
    "readelf": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("brew", ("brew", "install", "binutils")),
            PkgSpec("apt", ("apt-get", "install", "-y", "binutils")),
            PkgSpec("dnf", ("dnf", "install", "-y", "binutils")),
            PkgSpec("apk", ("apk", "add", "binutils")),
            PkgSpec("pacman", ("pacman", "-S", "--noconfirm", "binutils")),
        ),
    ),
    "objdump": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("brew", ("brew", "install", "binutils")),
            PkgSpec("apt", ("apt-get", "install", "-y", "binutils")),
            PkgSpec("dnf", ("dnf", "install", "-y", "binutils")),
            PkgSpec("apk", ("apk", "add", "binutils")),
            PkgSpec("pacman", ("pacman", "-S", "--noconfirm", "binutils")),
        ),
    ),
    # --- optional/WARN-tier but package-installable ---
    "docker": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("winget", ("winget", "install",
                               "--id=Docker.DockerDesktop", "-e")),
            PkgSpec("choco", ("choco", "install", "docker-desktop", "-y")),
            PkgSpec("brew", ("brew", "install", "--cask", "docker")),
            PkgSpec("apt", ("apt-get", "install", "-y", "docker.io")),
            PkgSpec("dnf", ("dnf", "install", "-y", "docker")),
            PkgSpec("apk", ("apk", "add", "docker")),
            PkgSpec("pacman", ("pacman", "-S", "--noconfirm", "docker")),
        ),
    ),
    "jadx": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("choco", ("choco", "install", "jadx", "-y")),
            PkgSpec("brew", ("brew", "install", "jadx")),
        ),
    ),
    "apktool": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("choco", ("choco", "install", "apktool", "-y")),
            PkgSpec("brew", ("brew", "install", "apktool")),
            PkgSpec("apt", ("apt-get", "install", "-y", "apktool")),
        ),
    ),
    "gitnexus": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("npm", ("npm", "install", "-g", "gitnexus")),
        ),
    ),
    "adb": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("winget", ("winget", "install",
                               "--id=Google.PlatformTools", "-e")),
            PkgSpec("choco", ("choco", "install", "adb", "-y")),
            PkgSpec("brew", ("brew", "install", "--cask",
                             "android-platform-tools")),
            PkgSpec("apt", ("apt-get", "install", "-y", "adb")),
            PkgSpec("dnf", ("dnf", "install", "-y", "android-tools")),
            PkgSpec("pacman", ("pacman", "-S", "--noconfirm",
                               "android-tools")),
        ),
    ),
    "aapt": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("apt", ("apt-get", "install", "-y", "aapt")),
        ),
    ),
    "gdbserver": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("apt", ("apt-get", "install", "-y", "gdbserver")),
            PkgSpec("dnf", ("dnf", "install", "-y", "gdb-gdbserver")),
            PkgSpec("pacman", ("pacman", "-S", "--noconfirm", "gdb")),
            PkgSpec("apk", ("apk", "add", "gdb")),
        ),
    ),
    "strace": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("apt", ("apt-get", "install", "-y", "strace")),
            PkgSpec("dnf", ("dnf", "install", "-y", "strace")),
            PkgSpec("apk", ("apk", "add", "strace")),
            PkgSpec("pacman", ("pacman", "-S", "--noconfirm", "strace")),
            PkgSpec("brew", ("brew", "install", "strace")),
        ),
    ),
    "ltrace": InstallPlan(
        kind="auto", degrade="WARN",
        packages=(
            PkgSpec("apt", ("apt-get", "install", "-y", "ltrace")),
            PkgSpec("dnf", ("dnf", "install", "-y", "ltrace")),
            PkgSpec("pacman", ("pacman", "-S", "--noconfirm", "ltrace")),
        ),
    ),
}

# #477 ②: the CLOSED declaration of the rest of the toolchain check
# surface (CHECK_SETS union) — every item is either auto-installable
# (INSTALL_PLANS) or explicitly here with a reason. mcp:<name> items are
# dynamic (mcp_probe.MANIFEST) and register-mcp, never install. Pinned
# by tests: union == the full check surface, no overlap, no invention.
NOT_AUTO_INSTALLABLE: dict[str, str] = {
    "ghidra": "the already-present env face (set GHIDRA_HOME); a missing "
              "binary surfaces as the decompiler item",
    "aapt2": "the aapt item's found-face alias (surfaced when aapt2 is "
             "detected); a miss is the aapt item",
    "vm_reachable": "VM channel — human event (#408), never auto-installed",
    "remote_debugger": "VM-side service — deployed via the VM channel "
                       "after vm_reachable (#451 vm-* verbs)",
    "device_root": "rooting is a human decision (#451 human-configure)",
    "debug_flag": "device property — human-configure (#451)",
    "frida_server": "device-side deploy — scripts/deploy_shim.py deploy "
                    "(#477 ③)",
    "android_server": "device-side deploy — scripts/deploy_shim.py deploy "
                      "(#477 ③)",
    "jdwp_debug": "capability of a running debuggable app — not a package",
    "ebpf": "target-kernel property — not installable from the host",
    "ebpf_android": "device SDK property — not installable",
    "unidbg": "Java library consumed by analysis code, not a CLI package",
}


# ---------- #477 ①: detection-driven resolution ----------

# Seams (repo pattern): tests inject deterministic detection / half-state.
_detect_managers = pkg_detect.detect_managers
_find_ghidra_install = pkg_detect.find_ghidra_install

# Resolution modes (design.md D2):
RESOLVE_INSTALL = "install"      # a detected manager runs the argv
RESOLVE_ELEVATION = "elevation"  # needs_sudo manager: print, never run
RESOLVE_SET_ENV = "set-env"      # unpacked ghidra: configure, not install
RESOLVE_MANUAL = "manual"        # no usable manager: guidance + NextAction
RESOLVE_NONE = "none"            # mcp_url (IDA) — no install face


@dataclass(frozen=True)
class InstallResolution:
    """What the (manager, package) data + live detection decided for one
    item. mode drives _run_install_plan; next_action (when set) uses the
    #451 closed verb vocabulary — detection failure guides the operator
    to install a manager or the tool manually, the half-state to
    configure GHIDRA_HOME instead of reinstalling."""

    mode: str
    argv: list[str] = field(default_factory=list)
    manager: str | None = None
    reason: str = ""
    next_action: "toolchain.NextAction | None" = None


def resolve_install(
        name: str,
        plan: "InstallPlan | None" = None,
        managers: "list[pkg_detect.ManagerHit] | None" = None,
        ) -> InstallResolution:
    """Assemble the install command for `name` from DATA x DETECTION.

    Decision order (design.md D2): mcp_url -> none; ghidra-install item
    with an unpacked dir on disk -> set-env (acceptance 3); first
    detected manager (spec order = preference) -> install / elevation
    (needs_sudo, #304); no usable manager -> manual with a NextAction
    naming the managers that COULD install the item (acceptance 2's
    counterpart: the guidance stays real instead of dead-ending).
    Unknown items raise KeyError (same surface as install_commands).
    """
    resolved_plan = plan if plan is not None else INSTALL_PLANS[name]
    if resolved_plan.kind == "mcp_url":
        return InstallResolution(
            mode=RESOLVE_NONE,
            reason=f"{name} is mcp_url — never auto-installed (#408)")
    # Half-state first: an unpacked ghidra beats a reinstall suggestion.
    if resolved_plan.mcp_register == "ghidra":
        unpacked = _find_ghidra_install()
        if unpacked:
            return InstallResolution(
                mode=RESOLVE_SET_ENV,
                reason=(f"unpacked ghidra found at {unpacked} — configure "
                        f"GHIDRA_HOME instead of reinstalling (#477)"),
                next_action=toolchain.NextAction(
                    "set-env", f"set GHIDRA_HOME={unpacked}"))
    hits = managers if managers is not None else _detect_managers()
    present = {h.name for h in hits}
    for spec in resolved_plan.packages:
        if spec.manager in present:
            manager = pkg_detect.MANAGERS[spec.manager]
            argv = list(spec.argv)
            if manager.needs_sudo:
                return InstallResolution(
                    mode=RESOLVE_ELEVATION, argv=argv,
                    manager=spec.manager,
                    reason=(f"{spec.manager} installs are system-wide — "
                            f"not auto-sudoed (#304); run: "
                            f"sudo {' '.join(argv)}"))
            return InstallResolution(
                mode=RESOLVE_INSTALL, argv=argv, manager=spec.manager,
                reason=f"via {spec.manager} ({' '.join(argv)})")
    carriers = sorted({spec.manager for spec in resolved_plan.packages})
    if not carriers:
        return InstallResolution(
            mode=RESOLVE_MANUAL,
            reason=f"{name} has no package data for any manager",
            next_action=toolchain.NextAction(
                "install",
                f"install {name} manually — see the fix text (#477)"))
    return InstallResolution(
        mode=RESOLVE_MANUAL,
        reason=(f"no usable package manager detected (none of "
                f"{', '.join(carriers)} present)"),
        next_action=toolchain.NextAction(
            "install",
            f"install one of {', '.join(carriers)} (or install {name} "
            f"manually), then re-run init"))


def install_commands(name: str) -> list[str]:
    """Install argv list for a tool on THIS host (detection-driven, #477).

    IDA yields [] (never auto-installed — use the MCP URL path). A known
    item with no usable manager on this host also yields [] — the reason
    and the operator guidance live in resolve_install(name). Unknown
    items raise KeyError.
    """
    plan = INSTALL_PLANS[name]
    if plan.kind == "mcp_url":
        return []
    return resolve_install(name, plan=plan).argv


def run_install(argv: list[str], timeout: int = 300) -> tuple[int, str, str]:
    """Execute one install command; returns (rc, stdout, stderr).

    #304 safety: never prefixes sudo here — the printed command carries the
    sudo prefix only when the human re-runs it manually.
    """
    try:
        r = _subprocess_run(argv, capture_output=True, text=True, timeout=timeout,
                            encoding="utf-8", errors="replace")
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as exc:
        return 1, "", str(exc)


def _bridge_mcp_path() -> str | None:
    """Locate the ghidra stdio bridge (bridge-mcp-ghidra) on this host.

    Searches the skill repo for a bundled bridge, then the host PATH. Returns
    None when not found — the printed guidance tells the operator to install
    the bridge before re-running init.
    """
    skill_root = _SCRIPT_DIR.parent
    for candidate in (
        skill_root / "tools" / "bridge-mcp-ghidra" / "bridge-mcp-ghidra.exe",
        skill_root / "tools" / "bridge-mcp-ghidra" / "bridge-mcp-ghidra",
        skill_root / "tools" / "bridge-mcp-ghidra" / "bridge-mcp-ghidra.bat",
    ):
        if candidate.exists():
            return str(candidate)
    return shutil.which("bridge-mcp-ghidra")


def _claude_binary() -> str:
    """The claude CLI binary used for `claude mcp add` registrations."""
    found = shutil.which("claude")
    if found:
        return found
    return "claude"


def _run_claude_mcp(argv: list[str]) -> int:
    """Run `claude mcp add ...`; returns rc. Fail-open: registration is best
    effort — a failure is reported (guidance printed) but never crashes init."""
    try:
        r = _subprocess_run([_claude_binary(), *argv], capture_output=True,
                            text=True, timeout=60, encoding="utf-8",
                            errors="replace")
        return r.returncode
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return 1


def register_ghidra_mcp() -> int:
    """Register the ghidra stdio bridge: `claude mcp add ghidra -- <bridge>`."""
    bridge = _bridge_mcp_path()
    if not bridge:
        print(
            "toolchain-install: ghidra MCP bridge (bridge-mcp-ghidra) not found "
            "on PATH or in the skill repo — install the bridge, then re-run "
            "kunglao-init (or register manually: "
            "`claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe`)",
            file=sys.stderr,
        )
        return 1
    return _run_claude_mcp(["mcp", "add", "ghidra", "--", bridge])


def register_ida_mcp_url(url: str) -> int:
    """Register an existing IDA MCP URL: `claude mcp add --transport http
    ida-pro-vm <url>`. Never installs the IDA product (#408).

    #455: no longer called from ask_then_install (stdin URL collection
    removed); kept as the registration primitive the #451 negotiation menu
    (agent-collected URL -> this call) consumes."""
    return _run_claude_mcp(["mcp", "add", "--transport", "http", "ida-pro-vm", url])


def prompt_yes_no(prompt: str, assume_yes: bool = False) -> bool:
    """Consent gate (#408; #455 amendment: stdin is NOT a user channel).

    --assume-yes forces True. Everything else declines — the script NEVER
    reads stdin (no input(), no isatty branch): the interactive consent
    flow is the agent layer's job (pending-decision list + --resolve, the
    #451 negotiation menu); this module's default is the safe decline that
    degrades the item per its plan.
    """
    return bool(assume_yes)


# Why an item degraded — selects the degrade_report detail wording (#451
# review M-1): "declined" is reserved for a REAL user choice, and this
# module no longer has a channel for one (#455). The negotiation surface
# (toolchain_negotiation --resolve) owns that wording in its own note.
DEGRADE_NO_CONSENT = "no-consent"          # headless decline / IDA mcp_url
DEGRADE_INSTALL_FAILED = "install-failed"  # a consented install ran + failed

_DEGRADE_CAUSES: dict[str, str] = {
    DEGRADE_NO_CONSENT: " — no consent channel (non-interactive, #455); ",
    DEGRADE_INSTALL_FAILED: " — install failed; ",
}


def degrade_report(report: "toolchain.ToolchainReport", name: str,
                   reason: str = DEGRADE_NO_CONSENT,
                   ) -> "toolchain.ToolchainReport":
    """Return a NEW report with `name` degraded per its plan:
    WARN for static-ok items; the decompiler stays FAIL (HARD).

    Immutable: the input report is never mutated (coding-style rule).

    reason selects the detail suffix: DEGRADE_NO_CONSENT (default — the
    headless decline and the IDA mcp_url degrade, both WITHOUT any user
    choice) or DEGRADE_INSTALL_FAILED (a --assume-yes install that ran and
    failed). "declined" never appears here — it is reserved for the
    negotiation surface's real --resolve choice.
    """
    if reason not in _DEGRADE_CAUSES:
        raise ValueError(
            f"unknown degrade reason {reason!r} "
            f"(expected one of {sorted(_DEGRADE_CAUSES)})")
    plan = INSTALL_PLANS[name]
    cause = _DEGRADE_CAUSES[reason]
    new_items = []
    for item in report.items:
        if item.name == name:
            if plan.degrade == "HARD":
                new_items.append(toolchain.CheckResult(
                    name=item.name, status=toolchain.Status.FAIL,
                    tier=toolchain.Tier.HARD,
                    detail=item.detail + cause
                            + "this item is REQUIRED and stays HARD (#408)",
                    root_cause=item.root_cause,
                ))
            else:
                new_items.append(toolchain.CheckResult(
                    name=item.name, status=toolchain.Status.WARN,
                    tier=toolchain.Tier.HARD,
                    detail=item.detail + cause
                            + "static analysis proceeds degraded (WARN, #408)",
                    root_cause=item.root_cause,
                ))
        else:
            new_items.append(item)
    return toolchain.ToolchainReport(project_type=report.project_type,
                                     items=new_items)


def _official_guidance(name: str) -> str:
    """Official install guidance (the toolchain.FIXES text) for a failed item."""
    return toolchain.FIXES.get(name, "see the toolchain check detail above")


def _run_install_plan(name: str, plan: "InstallPlan", assume_yes: bool,
                      ws: Path) -> tuple[int, str, str]:
    """Run an install plan: resolve DATA x DETECTION, then install or
    hand the exact remediation back (#477 ①; #304 safety preserved).

    Returns (rc, detail, err). For the mcp_url kind (IDA) this is NOT
    used — ask_then_install handles the URL path directly.

    Modes: install -> execute argv + optional MCP registration;
    elevation -> NEVER auto-run (#304), print the sudo-prefixed command
    for the human; set-env / manual -> print the guidance (acceptance 3 /
    the no-manager case) and fail the install attempt so the item takes
    its degrade path with the official guidance.
    """
    res = resolve_install(name, plan=plan)
    if res.mode == RESOLVE_ELEVATION:
        print(
            f"toolchain-install: {name} needs elevation "
            f"({res.manager} is system-wide) — not auto-running. "
            f"Run: sudo {' '.join(res.argv)}",
            file=sys.stderr,
        )
        return 1, "", "elevation required (not auto-sudoed, #304)"
    if res.mode == RESOLVE_SET_ENV:
        assert res.next_action is not None  # set-env always carries one
        print(
            f"toolchain-install: {name} — {res.reason}; configure it "
            f"instead of reinstalling: {res.next_action.command}",
            file=sys.stderr,
        )
        return 1, "", res.reason
    if res.mode == RESOLVE_MANUAL:
        na = res.next_action
        print(
            f"toolchain-install: {name} — {res.reason}",
            file=sys.stderr,
        )
        if na is not None:
            print(f"toolchain-install:   action: {na.action}", file=sys.stderr)
            if na.command:
                print(f"toolchain-install:   command: {na.command}",
                      file=sys.stderr)
        return 1, "", res.reason
    rc, out, err = run_install(res.argv)
    if rc != 0:
        return rc, out, err
    if plan.mcp_register == "ghidra":
        rc = register_ghidra_mcp()
        if rc != 0:
            return rc, "", "ghidra MCP bridge registration failed"
    return 0, "install OK", ""


def _record_installed(ws: Path, name: str,
                      fresh: "toolchain.ToolchainReport") -> None:
    """#477 ④: merge the install outcome into <ws>/env-facts.yaml's
    installed ledger (the #450 facts file's bookkeeping face).

    Fail-open BOOKKEEPING (deliberately unlike the fail-closed READ
    surface): the re-probe outcome is already honestly reported in the
    returned report; a ledger write problem warns on stderr and never
    aborts the install loop. Manager attribution re-resolves the plan —
    detection is read-only and idempotent, and _run_install_plan's
    4-positional signature is pinned by tests/callers.
    """
    res = resolve_install(name)
    try:
        env_manifest.record_installed(
            ws, name, res.manager or "unknown",
            fresh.overall_status.value)
    except (ValueError, OSError) as exc:
        print(f"toolchain-install: WARNING installed-ledger write failed "
              f"({exc})", file=sys.stderr)


def ask_then_install(report: "toolchain.ToolchainReport", ws: Path,
                     project_type: str, assume_yes: bool = False,
                     task_spec: dict | None = None,
                     ) -> "toolchain.ToolchainReport":
    """#408 orchestrator: for each HARD-FAIL item with an install plan, ask
    for consent; on consent install + register MCP + re-probe via
    toolchain.check; on decline/install-failure degrade the item.

    #449 needs-first (review M1): task_spec is the SAME parsed mapping the
    calling gate derived its layers from — the post-install re-probe must
    re-derive identically (a static-only spec under --assume-yes must not
    have vm_reachable re-hardened by a spec-blind re-probe). None keeps
    the 2-arg check() call shape (stable for test fakes / direct callers).

    Returns the report to continue with:
      - install succeeded AND re-probe PASS -> the fresh re-probe report
      - decline / install failure -> the degraded report (WARN for static
        items, decompiler stays HARD)
    """
    result = report
    for item in report.items:
        if item.status != toolchain.Status.FAIL or item.tier != toolchain.Tier.HARD:
            continue
        if item.name not in INSTALL_PLANS:
            continue
        plan = INSTALL_PLANS[item.name]
        print(f"toolchain-install: {item.name} is missing "
              f"({item.detail})", flush=True)

        if plan.kind == "mcp_url":
            # IDA: never auto-install. #455 amendment: stdin is NOT a user
            # channel — the URL cannot be collected here (no input(), no
            # isatty branch). Print the manual registration guidance and
            # degrade; the agent layer surfaces the exact command to the
            # user (the interactive menu is #451's negotiation interface).
            print(
                "toolchain-install: IDA is not auto-installable (#408) — "
                "register your existing IDA MCP URL manually: "
                "`claude mcp add --transport http ida-pro-vm <ida-mcp-url>`, "
                "then re-run kunglao-init",
                file=sys.stderr,
            )
            result = degrade_report(result, item.name)
            continue

        consent = prompt_yes_no(f"  install {item.name}?", assume_yes=assume_yes)
        if not consent:
            # #451 伪装 fix: a headless no-channel degrade is NOT a user
            # refusal — "declined" is reserved for a real choice (a
            # --resolve answer in the negotiation menu). The prompt line is
            # flushed closed so the next stderr block cannot splice into it.
            print(f"  no consent channel (non-interactive, #455) — "
                  f"{item.name} degrades automatically ({plan.degrade}); "
                  f"decide via kunglao-init's negotiation menu "
                  f"(--resolve, #451) or re-run with --assume-yes",
                  flush=True)
            result = degrade_report(result, item.name)
            continue

        rc, out, err = _run_install_plan(item.name, plan, assume_yes, ws)
        if rc != 0:
            print(f"toolchain-install: {item.name} install FAILED "
                  f"({err or out or 'unknown error'})", file=sys.stderr)
            print(f"toolchain-install: official guidance — "
                  f"{_official_guidance(item.name)}", file=sys.stderr)
            result = degrade_report(result, item.name,
                                    reason=DEGRADE_INSTALL_FAILED)
            continue

        print(f"toolchain-install: {item.name} installed ({out or 'ok'}) — "
              f"re-probing toolchain")
        if task_spec is None:
            fresh = toolchain.check(ws, project_type)
        else:
            fresh = toolchain.check(ws, project_type, task_spec=task_spec)
        # #477 ④ unified loop: install -> re-probe -> env-facts installed
        # ledger. A FAILED install never reaches here (degrade + official
        # guidance above — the failure surface is the NextAction guidance,
        # not the ledger).
        _record_installed(ws, item.name, fresh)
        if fresh.overall_status == toolchain.Status.PASS:
            return fresh
        # Re-probe still failing on the same or another item: continue the
        # ask loop over the fresh report's remaining HARD fails.
        result = fresh
    return result


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI: probe a workspace, ask-then-install each HARD miss.

    kunglao-init calls ask_then_install directly; the CLI is for operators /
    tests: `python toolchain_install.py <ws> --type <t> [--assume-yes]`.
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="toolchain-install",
        description="ask-then-install for the kunglao toolchain (#408)",
    )
    parser.add_argument("workspace", help="workspace root path")
    parser.add_argument("--type", choices=toolchain.VALID_TYPES, default=None,
                        help="project type (default: read from analysis_state.txt)")
    parser.add_argument("--assume-yes", action="store_true",
                        help="consent to every install (CI/headless)")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    args = parser.parse_args(argv)

    ws = Path(args.workspace).resolve()
    # #449 needs-first (review M1): the standalone CLI consumes
    # <ws>/task_spec.yaml with the SAME single loading point and the SAME
    # conservative WARNING fallback as toolchain.py main, so the initial
    # probe and the ask-then-install re-probe derive layers identically.
    try:
        task_spec = toolchain.load_task_spec(ws)
    except ValueError as exc:
        print(f"WARNING: {exc} — toolchain layers stay conservative HARD "
              f"(#449; fix task_spec.yaml at needs-first intake)",
              file=sys.stderr)
        task_spec = None
    try:
        if task_spec is None:
            report = toolchain.check(ws, args.type)
        else:
            report = toolchain.check(ws, args.type, task_spec=task_spec)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if report.overall_status == toolchain.Status.PASS:
        if args.json:
            print(json.dumps({"overall": "PASS"}, indent=2))
        else:
            print(toolchain.format_human(report))
        return 0

    resolved = ask_then_install(report, ws, report.project_type,
                                assume_yes=args.assume_yes,
                                task_spec=task_spec)
    if args.json:
        print(json.dumps({
            "overall": resolved.overall_status.value,
            "checks": [i.name for i in resolved.items
                       if i.status == toolchain.Status.FAIL],
            "degraded": [i.name for i in resolved.items
                         if i.status == toolchain.Status.WARN
                         and "degraded" in i.detail],
        }, indent=2))
    else:
        print(toolchain.format_human(resolved))
    return resolved.exit_code


if __name__ == "__main__":
    sys.exit(main())
