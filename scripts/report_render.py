#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_render.py — the report/console rendering face of the toolchain.

One home for the guidance-and-next-action rendering data that the
toolchain check reports and the installer both consume:

  ToolMeta           structured per-item guidance metadata (fix text,
                     description, url/repo/package, verify command)
  FIXES              the ToolMeta table keyed by check item name
                     (including the mcp:<name> entries derived from the
                     MCP supply manifest)
  fix_text()         typed string accessor (`fix_text(name) or default`)
  NEXT_ACTION_VERBS  the closed remediation-verb vocabulary
  NextAction         one mechanically consumable remediation step

Pairs with toolchain_install (the ask-then-install loop renders these
fields) and toolchain (the check report composes them into every FAIL).
This module also single-sources the guidance-facing port defaults
(FRIDA_PORT / ANDROID_SERVER_PORT) that both sides embed.

Import rule: report_render imports no toolchain module (toolchain
composes THIS) — the dependency arrow points one way.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import mcp_probe  # noqa: E402  (same dir, sys.path injected by the importer;
                  #  derived mcp:<name> FIXES entries come from its manifest)


# frida custom port convention — config-driven, default 1337
# (frida-server renamed + non-default port to evade sample detection).
# Defensive parse: garbage / out-of-range env values fall back to the
# default instead of crashing the import (kunglao-init imports this module).
def parse_port(raw: str | None, default: int) -> int:
    """Defensive port parse: int(raw) in [1, 65535], else default."""
    try:
        value = int((raw or "").strip() or str(default))
    except ValueError:
        return default
    return value if 1 <= value <= 65535 else default


FRIDA_PORT = parse_port(os.environ.get("KUNGLAO_FRIDA_PORT"), 1337)
ANDROID_SERVER_PORT = 23946  # IDA android_server default listener port


# Per-item friendly install commands (the init HARD-refusal amendment):
# kunglao-init prints these on HARD refusal so the HUMAN knows exactly what to
# install — init does NOT silently repair. Keyed by check item name.
#
# FIXES values are structured ToolMeta, not bare strings. The legacy
# guidance text survives verbatim as ToolMeta.fix (still what init prints);
# the new fields end the "agent hunts for the install page / picks the wrong
# package" waste — url/description always, repo/package/verify_cmd where
# applicable. Old string callers keep a working string face: ToolMeta.__str__
# renders the fix text, and fix_text(name) is the typed accessor.
@dataclass(frozen=True)
class ToolMeta:
    """Metadata for one FIXES entry.

    fix:         remediation guidance (the legacy FIXES string, verbatim)
    description: one-line purpose (what the tool is FOR)
    url:         official homepage / docs (None = unknown -> rendering omits
                 the line; never fabricated)
    repo:        source repository (None when none applies separately from url)
    package:     PyPI / npm / apt package name (None when not a package)
    verify_cmd:  post-install verification command (e.g. `jadx --version`)
    """

    fix: str
    description: str
    url: str | None
    repo: str | None = None
    package: str | None = None
    verify_cmd: str | None = None

    def __str__(self) -> str:
        """String face: a FIXES value interpolated into a
        string renders the legacy guidance text, never a dataclass repr."""
        return self.fix


FIXES: dict[str, ToolMeta] = {
    # web (labs): direct-npx JS recovery tools (agent-invoked, never
    # init-gated). url/package/verify_cmd verified against upstream
    # READMEs + execution on 2026-08-26.
    "wakaru": ToolMeta(
        fix="npx -y wakaru --version (first use installs via npx)",
        description="bundler-aware JS module recovery (unpack webpack/"
                    "esbuild/Browserify/Metro + transpiler/minifier undo)",
        url="https://github.com/pionxzh/wakaru",
        package="wakaru", verify_cmd="npx wakaru --version"),
    "webcrack": ToolMeta(
        fix="npx -y webcrack --version (first use installs via npx)",
        description="obfuscator.io-class JS deobfuscation + unminification",
        url="https://github.com/j4k0xb/webcrack",
        package="webcrack", verify_cmd="npx webcrack --version"),
    "pefile": ToolMeta(
        fix="pip install pefile",
        description="PE/COFF parsing and Authenticode signature extraction",
        url="https://github.com/erocarrera/pefile",
        package="pefile", verify_cmd="pip show pefile"),
    "uv": ToolMeta(
        fix="missing uv -> agent installs it itself: "
            "curl -LsSf https://astral.sh/uv/install.sh | sh (AGENT-DO); "
            "every kunglao face runs via the uv-managed env "
            "(`uv sync --locked` + `uv run --project <root>` / the recorded "
            ".venv python — never bare python3/system python)",
        description="uv — the Python environment manager (repo standard: "
                    "uv sync --locked + uv run)",
        url="https://docs.astral.sh/uv/",
        package="uv", verify_cmd="uv --version"),
    "die": ToolMeta(
        fix="install DIE (Detect It Easy) and add it to PATH",
        description="packer/compiler detector for PE/ELF/Mach-O",
        url="https://github.com/horsicq/Detect-It-Easy",
        package="die", verify_cmd="diec --version"),
    "floss": ToolMeta(
        fix="pip install flare-floss (or add floss to PATH)",
        description="FLARE string deobfuscation (stack/tight strings)",
        url="https://github.com/mandiant/flare-floss",
        package="flare-floss", verify_cmd="floss --version"),
    "file": ToolMeta(
        fix="install binutils (file) and add to PATH",
        description="file-type identification",
        url="https://www.darwinsys.com/file/",
        repo="https://github.com/file/file",
        package="file", verify_cmd="file --version"),
    "readelf": ToolMeta(
        fix="install binutils (readelf) and add to PATH",
        description="ELF header/section/segment inspection",
        url="https://www.gnu.org/software/binutils/",
        repo="https://sourceware.org/git/binutils-gdb.git",
        package="binutils", verify_cmd="readelf --version"),
    "objdump": ToolMeta(
        fix="install binutils (objdump) and add to PATH",
        description="disassembly and object-file inspection",
        url="https://www.gnu.org/software/binutils/",
        repo="https://sourceware.org/git/binutils-gdb.git",
        package="binutils", verify_cmd="objdump --version"),
    "decompiler": ToolMeta(
        fix="decompiler supply is LANE-CONDITIONAL (#202): MCP lane (task_spec "
            "tools.decompiler_lane: mcp) -> the gate verifies ida-pro-vm "
            "registration + reachability and registers it itself via "
            "`claude mcp add` — never a local IDA install; local lane -> the "
            "agent probe ladder runs (PATH, mdfind, find bundle sweep incl. "
            ".app/Contents/MacOS, brew cask, known dirs), then the Ghidra "
            "probe (GHIDRA_HOME, ghidra dirs, brew). Ghidra OR IDA — either "
            "satisfies this check when present; a ghidra/ida-pro-vm MCP "
            "registration satisfies it on the MCP lane; neither -> exit-8 "
            "PendingDecision CHOICE: install-local-ida (license) / "
            "install-ghidra (#408 installer) / skip-decompiler-lane",
        description="headless decompiler supply (Ghidra or IDA)",
        url="https://ghidra-sre.org/",
        repo="https://github.com/NationalSecurityAgency/ghidra",
        package="ghidra", verify_cmd="analyzeHeadless"),
    "ghidra": ToolMeta(
        fix="set GHIDRA_HOME=<Ghidra install root> (support/analyzeHeadless must exist, platform-correct name #409)",
        description="Ghidra reverse-engineering suite (headless analyzeHeadless)",
        url="https://ghidra-sre.org/",
        repo="https://github.com/NationalSecurityAgency/ghidra",
        verify_cmd="analyzeHeadless"),
    "ida": ToolMeta(
        fix="agent-run probe ladder first (#202): PATH -> mdfind -> find "
            "bundle sweep (.app/Contents/MacOS) -> brew cask -> known dirs; "
            "a found idat64 is wired automatically — the HUMAN-ONLY "
            "touchpoint is only the LICENSE purchase when the user chooses "
            "local IDA at the exit-8 choice",
        description="IDA Pro disassembler (commercial)",
        url="https://hex-rays.com/ida-pro/"),
    "vm_reachable": ToolMeta(
        fix="set KUNGLAO_VM_HOST=<live VM lease IP> (vmr-shell discovery) and ensure ports are open",
        description="analysis VM channel liveness (vmrun/VBoxManage lease IP + open ports)",
        url="https://github.com/amd2g2zz/kunglao-agent"),
    "remote_debugger": ToolMeta(
        fix="fix the root cause first: make the VM reachable (set KUNGLAO_VM_HOST), then deploy the remote debugger on the VM",
        description="remote debugger deployed on the analysis VM",
        url="https://github.com/amd2g2zz/kunglao-agent"),
    "aapt": ToolMeta(
        fix="install Android SDK build-tools (aapt/aapt2) and add to PATH (or install unzip as a substitute)",
        description="Android asset packaging tool (APK manifest inspection)",
        url="https://developer.android.com/tools/aapt",
        package="aapt", verify_cmd="aapt version"),
    "jadx": ToolMeta(
        fix="install jadx and add it to PATH",
        description="DEX-to-Java decompiler",
        url="https://github.com/skylot/jadx",
        package="jadx", verify_cmd="jadx --version"),
    "apktool": ToolMeta(
        fix="install apktool and add it to PATH",
        description="APK resource decoding and rebuilding",
        url="https://github.com/iBotPeaches/Apktool",
        package="apktool", verify_cmd="apktool --version"),
    "gitnexus": ToolMeta(
        fix="npm i -g gitnexus (or install per GitNexus docs); verify `gitnexus --version`",
        description="post-decompile code graph builder (npm)",
        url="https://www.npmjs.com/package/gitnexus",
        package="gitnexus", verify_cmd="gitnexus --version"),
    "unidbg": ToolMeta(
        fix="bash scripts/install_unidbg.sh (registered installer: JDK required, "
            "Maven wrapper-eligible; remote clone + first build; verify the "
            ".unidbg-installed.json build marker)",
        description="Java analysis fallback emulator (unidbg; optional WARN tier)",
        url="https://github.com/unidbg/unidbg",
        repo="https://github.com/unidbg/unidbg",
        verify_cmd="cat ./vendor/unidbg/.unidbg-installed.json"),
    "dexdc": ToolMeta(
        fix="install dex-decompiler: build the PyO3 wheel (cd dex-decompiler-py && maturin build --release && pip install target/wheels/dex_decompiler-*.whl) or cargo build --release; verify `pip show dex_decompiler`",
        description="Rust DEX decompiler + per-method CFG + value-flow taint + offline emulator (no JVM)",
        url="https://github.com/androguard/dex-decompiler",
        repo="https://github.com/androguard/dex-decompiler",
        verify_cmd="pip show dex_decompiler"),
    "apkid": ToolMeta(
        fix="install apkid: `pip install apkid` (https://github.com/rednaga/APKiD); verify `apkid --version` returns 2.x",
        description="APK packer/compiler/obfuscator fingerprinting (YARA)",
        url="https://github.com/rednaga/APKiD",
        package="apkid", verify_cmd="apkid --version"),
    "baksmali": ToolMeta(
        fix="install baksmali (https://github.com/baksmali/smali/releases - download jar or `apt install baksmali`); verify `baksmali --version` returns 2.x",
        description="DEX disassembler to smali",
        url="https://github.com/baksmali/smali/releases",
        repo="https://github.com/baksmali/smali",
        package="baksmali", verify_cmd="baksmali --version"),
    "adb": ToolMeta(
        fix="install Android SDK platform-tools and add adb to PATH; attach a device (`adb devices` must be non-empty)",
        description="Android Debug Bridge host client",
        url="https://developer.android.com/tools/adb",
        package="adb", verify_cmd="adb --version"),
    "device_root": ToolMeta(
        fix="root the device: `adb root` (emulator) or su via Magisk; verify `adb shell su -c id` returns uid=0",
        description="rooted device (su/Magisk) for dynamic instrumentation",
        url="https://github.com/topjohnwu/Magisk"),
    "debug_flag": ToolMeta(
        fix="set the debug flag: `adb shell am set-debug-app -w <pkg>` or `adb shell setprop ro.debuggable 1`; verified at init via `adb shell getprop ro.debuggable` (must read back 1)",
        description="device ro.debuggable / debug-app state for JDWP",
        url="https://developer.android.com/tools/adb"),
    "frida_server": ToolMeta(
        fix="fix the root cause first (ADB); then deploy a RENAMED frida-server binary on custom port "
            f"{FRIDA_PORT} and verify at init via `adb forward tcp:{FRIDA_PORT} tcp:{FRIDA_PORT}` + TCP connect "
            "(default name/port 27042 is detected by samples)",
        description="renamed frida-server on a custom port (anti-detection)",
        url="https://frida.re/",
        repo="https://github.com/frida/frida"),
    "android_server": ToolMeta(
        fix="fix the root cause first (ADB); then adb push android_server to the device and run it; "
            f"verified at init via `adb forward tcp:{ANDROID_SERVER_PORT} tcp:{ANDROID_SERVER_PORT}` + TCP connect",
        description="IDA remote debug server pushed to the device",
        url="https://hex-rays.com/ida-pro/"),
    "jdwp_debug": ToolMeta(
        fix="optional capability (WARN): only needed when the task actually drives jdb. "
            "To enable: ADB ok + ro.debuggable=1 + the target app running (`adb jdwp` lists "
            "a pid); the probe forwards tcp:8700 -> jdwp:<pid> and exchanges the raw 14-byte "
            "JDWP-Handshake (jdb stays the interactive driver; never jdb -attach — side effects)",
        description="JDWP capability probe (jdb handoff, WARN tier)",
        url="https://docs.oracle.com/javase/8/docs/technotes/guides/jpda/jdwp-spec.html"),
    "jvm": ToolMeta(
        fix="install a JDK so `java -version` answers (jadx is a Java "
            "program — probe the environment, never read the JVM state off "
            "a tool description)",
        description="JVM availability for the jadx java-source lane "
                    "(HARD when jadx is present, WARN otherwise)",
        url="https://adoptium.net/"),
}

# Registration guidance for MCP supply checks — fix text rendered by the
# formatters like every other FIXES entry (keyed by report item name mcp:<name>).
# MCP server metadata is OUT OF SCOPE (separate manifest, mcp_probe.py)
# — the derived entries carry the register command as fix + the manifest
# purpose as description, url=None (the fallback rendering path).
FIXES.update({
    f"mcp:{i.name}": ToolMeta(fix=i.register, description=i.purpose, url=None)
    for i in mcp_probe.MANIFEST
})


def fix_text(name: str) -> str | None:
    """Typed string face of FIXES — the remediation guidance text for
    `name`, None when unknown. The canonical accessor for string callers
    (kunglao-init / negotiation / deploy_shim / toolchain_install);
    `fix_text(name) or default` preserves the old `.get(name, default)`
    semantics. Unknown names MUST return None (never raise, never invent)."""
    meta = FIXES.get(name)
    return None if meta is None else meta.fix


# ---------- machine-parseable next-action on every FAIL ----------
# A prose fix pushes discovery work back onto the
# human and cannot be consumed mechanically. Every FAIL therefore carries a
# structured next-action: a closed verb vocabulary + the exact command +
# enumerated options, rendered as key-value lines in the human output
# (`action:` / `command:` / `option N:`) and as a `next_action` object in
# --json. Downstream consumers (the negotiation menu, the
# init-worker's AskUserQuestion relay) parse THIS, never the prose.

NEXT_ACTION_VERBS = frozenset({
    "install",          # an exact install command exists (pip/npm/pkg mgr)
    "set-env",          # set an environment variable (GHIDRA_HOME)
    "register-mcp",     # register via `claude mcp add`
    "vm-enumerate",     # multiple/no candidates: enumerate (vmrun list / VBoxManage)
    "vm-start",         # single off candidate: boot it (vmrun -T ws start)
    "vm-reip",          # running/lease-drifted: re-resolve the live IP
    "human-configure",  # device-side human decision (root / debug flag)
    "human-deploy",     # device-side human deployment (frida/android_server)
})


@dataclass(frozen=True)
class NextAction:
    """One mechanically consumable remediation step.

    action:  verb from the closed NEXT_ACTION_VERBS vocabulary
    command: the exact command the human/agent runs (None when the action
             is a human decision with no single command)
    options: enumerated candidates (VM names); menu choices are built by
             the negotiation layer, not here
    """

    action: str
    command: str | None = None
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """The verb vocabulary is CLOSED — fail-closed at
        construction. A verb outside NEXT_ACTION_VERBS raises instead of
        silently rendering an unparseable `action:` line downstream."""
        if self.action not in NEXT_ACTION_VERBS:
            raise ValueError(
                f"NextAction.action {self.action!r} is not in the closed "
                f"NEXT_ACTION_VERBS vocabulary "
                f"{sorted(NEXT_ACTION_VERBS)}")
