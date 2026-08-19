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
