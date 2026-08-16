#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolchain_install.py — #408 ask-then-install installer for kunglao-init.

kunglao-init currently refuses (exit 4) on missing tools with only textual
FIXES guidance (#304 "human-install event"). This module turns that refusal
into an interactive "install X?" flow:

  - per-item install commands by platform (pip/uv for Python packages;
    brew/choco/apt for system tools; IDA is NEVER auto-installed)
  - consent prompt (safe decline on non-TTY stdin; --assume-yes for CI)
  - after a successful install: register the related MCP (ghidra bridge) and
    RE-PROBE via toolchain.check — PASS is required before continuing
  - on decline or install failure: print the official guidance and DEGRADE
    that item (WARN where static analysis proceeds; HARD only where it
    cannot — the decompiler)

#304 safety preserved: no silent sudo, no system-wide auto-install without
explicit consent.
"""
from __future__ import annotations

import builtins
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Per repo convention, inject scripts/ into sys.path before importing sibling
# modules (compatible with `python -m` style invocations).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import toolchain  # noqa: E402  (#304 toolchain probes — re-probe after install)

# Seam for tests: subprocess.run is accessed via this private name so tests
# can assert the exact argv without executing real installs.
_subprocess_run = subprocess.run


@dataclass(frozen=True)
class InstallPlan:
    """One auto-installable (or MCP-register-only) toolchain item.

    - kind: "auto" executes install commands; "mcp_url" never installs a
      product — it registers an existing MCP URL on consent (IDA).
    - degrade: what a decline/install-failure means for the item —
      "WARN" (static analysis proceeds degraded) or "HARD" (blocking).
    - commands: platform → argv list. sudo_platforms: platforms whose system
      command needs a sudo prefix — used ONLY to print the exact command the
      human must run; install never auto-sudoes.
    """
    kind: str                        # "auto" | "mcp_url"
    degrade: str                     # "WARN" | "HARD"
    commands: dict[str, list[str]]   # sys.platform key → install argv
    sudo_platforms: tuple[str, ...] = ()
    mcp_register: str | None = None  # "ghidra" -> register the bridge after install


# Per-item install plans (#408). Keyed by toolchain.py check item name.
#   pefile / floss -> Python packages (pip; uv pip when uv is on PATH)
#   die / ghidra   -> system tools (brew / choco / apt)
#   decompiler     -> the Ghidra path (auto) — brew/choco/apt install + MCP
#                     bridge registration; IDA is the mcp_url path (below)
#   ida            -> NEVER auto-installed; operator supplies the existing
#                     MCP URL, registered via `claude mcp add --transport http`
INSTALL_PLANS: dict[str, InstallPlan] = {
    "pefile": InstallPlan(
        kind="auto", degrade="WARN",
        commands={
            "win32": ["pip", "install", "pefile"],
            "darwin": ["pip", "install", "pefile"],
            "linux": ["pip", "install", "pefile"],
        },
    ),
    "floss": InstallPlan(
        kind="auto", degrade="WARN",
        commands={
            "win32": ["pip", "install", "flare-floss"],
            "darwin": ["pip", "install", "flare-floss"],
            "linux": ["pip", "install", "flare-floss"],
        },
    ),
    "die": InstallPlan(
        kind="auto", degrade="WARN",
        commands={
            "win32": ["choco", "install", "die", "-y"],
            "darwin": ["brew", "install", "die"],
            "linux": ["apt-get", "install", "-y", "die"],
        },
        sudo_platforms=("linux",),
    ),
    "decompiler": InstallPlan(
        kind="auto", degrade="HARD",
        commands={
            "win32": ["choco", "install", "ghidra", "-y"],
            "darwin": ["brew", "install", "--cask", "ghidra"],
            "linux": ["apt-get", "install", "-y", "ghidra"],
        },
        sudo_platforms=("linux",),
        mcp_register="ghidra",
    ),
    "ida": InstallPlan(
        kind="mcp_url", degrade="WARN", commands={},
    ),
}


def _os_platform() -> str:
    """Return the current sys.platform value (a seam for platform-matrix tests)."""
    return sys.platform


def install_commands(name: str) -> list[str]:
    """Install argv list for a tool on the current platform.

    IDA yields [] (never auto-installed — use the MCP URL path).
    Unknown items raise KeyError.
    """
    plan = INSTALL_PLANS[name]
    if plan.kind == "mcp_url":
        return []
    cmds = plan.commands.get(_os_platform())
    if not cmds:
        raise KeyError(
            f"no install command for {name!r} on platform {_os_platform()!r} "
            f"(see INSTALL_PLANS[{name!r}])"
        )
    return list(cmds)


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
    ida-pro-vm <url>`. Never installs the IDA product (#408)."""
    return _run_claude_mcp(["mcp", "add", "--transport", "http", "ida-pro-vm", url])


def prompt_yes_no(prompt: str, assume_yes: bool = False) -> bool:
    """Interactive consent prompt (y/n). Safe default: decline.

    Non-interactive stdin (CI/headless without --assume-yes) -> False so the
    flow never hangs on a closed pipe. --assume-yes forces True.
    """
    if assume_yes:
        return True
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return False
    try:
        raw = builtins.input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return raw in ("y", "yes")


def degrade_report(report: "toolchain.ToolchainReport", name: str
                   ) -> "toolchain.ToolchainReport":
    """Return a NEW report with `name` degraded per its plan:
    WARN for static-ok items; the decompiler stays FAIL (HARD).

    Immutable: the input report is never mutated (coding-style rule).
    """
    plan = INSTALL_PLANS[name]
    new_items = []
    for item in report.items:
        if item.name == name:
            if plan.degrade == "HARD":
                new_items.append(toolchain.CheckResult(
                    name=item.name, status=toolchain.Status.FAIL,
                    tier=toolchain.Tier.HARD,
                    detail=item.detail + " — install declined/failed; "
                            "this item is REQUIRED and stays HARD (#408)",
                    root_cause=item.root_cause,
                ))
            else:
                new_items.append(toolchain.CheckResult(
                    name=item.name, status=toolchain.Status.WARN,
                    tier=toolchain.Tier.HARD,
                    detail=item.detail + " — install declined/failed; "
                            "static analysis proceeds degraded (WARN, #408)",
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
    """Run an install plan: install command(s) + optional MCP registration.

    Returns (rc, detail, err). For the mcp_url kind (IDA) this is NOT used —
    ask_then_install handles the URL prompt directly.
    """
    # System-wide commands that need elevation are NEVER auto-sudoed (#304):
    # print the exact sudo-prefixed command the human must run instead.
    if _os_platform() in plan.sudo_platforms:
        cmd = install_commands(name)
        print(
            f"toolchain-install: {name} needs elevation on this platform — "
            f"not auto-running. Run: sudo {' '.join(cmd)}",
            file=sys.stderr,
        )
        return 1, "", "elevation required (not auto-sudoed, #304)"
    for cmd in plan.commands.get(_os_platform(), []):
        rc, out, err = run_install(cmd)
        if rc != 0:
            return rc, out, err
    if plan.mcp_register == "ghidra":
        rc = register_ghidra_mcp()
        if rc != 0:
            return rc, "", "ghidra MCP bridge registration failed"
    return 0, "install OK", ""


def ask_then_install(report: "toolchain.ToolchainReport", ws: Path,
                     project_type: str, assume_yes: bool = False,
                     ) -> "toolchain.ToolchainReport":
    """#408 orchestrator: for each HARD-FAIL item with an install plan, ask
    for consent; on consent install + register MCP + re-probe via
    toolchain.check; on decline/install-failure degrade the item.

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
              f"({item.detail})")

        if plan.kind == "mcp_url":
            # IDA: never auto-install. Ask for the existing MCP URL, register it.
            if assume_yes:
                print(
                    "toolchain-install: IDA is not auto-installable (#408) — "
                    "register your existing IDA MCP URL manually: "
                    "`claude mcp add --transport http ida-pro-vm <ida-mcp-url>`, "
                    "then re-run kunglao-init",
                    file=sys.stderr,
                )
                result = degrade_report(result, item.name)
                continue
            if not getattr(sys.stdin, "isatty", lambda: False)():
                result = degrade_report(result, item.name)
                continue
            try:
                url = builtins.input(
                    "  IDA is never auto-installed. Enter the existing IDA MCP "
                    "URL to register (or blank to skip): "
                ).strip()
            except EOFError:
                url = ""
            if not url:
                result = degrade_report(result, item.name)
                continue
            rc = register_ida_mcp_url(url)
            if rc != 0:
                print("toolchain-install: IDA MCP registration failed — "
                      "see the guidance above; the decompiler remains required",
                      file=sys.stderr)
                result = degrade_report(result, item.name)
                continue
            fresh = toolchain.check(ws, project_type)
            if fresh.overall_status == toolchain.Status.PASS:
                return fresh
            result = fresh
            continue

        consent = prompt_yes_no(f"  install {item.name}?", assume_yes=assume_yes)
        if not consent:
            print(f"  declined — {item.name} will be degraded "
                  f"({plan.degrade})")
            result = degrade_report(result, item.name)
            continue

        rc, out, err = _run_install_plan(item.name, plan, assume_yes, ws)
        if rc != 0:
            print(f"toolchain-install: {item.name} install FAILED "
                  f"({err or out or 'unknown error'})", file=sys.stderr)
            print(f"toolchain-install: official guidance — "
                  f"{_official_guidance(item.name)}", file=sys.stderr)
            result = degrade_report(result, item.name)
            continue

        print(f"toolchain-install: {item.name} installed ({out or 'ok'}) — "
              f"re-probing toolchain")
        fresh = toolchain.check(ws, project_type)
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
    try:
        report = toolchain.check(ws, args.type)
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
                                assume_yes=args.assume_yes)
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
