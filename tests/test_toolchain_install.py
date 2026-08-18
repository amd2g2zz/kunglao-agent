# -*- coding: utf-8 -*-
"""Tests for #408 — ask-then-install: per-item install commands, consent
prompt, re-probe after install, and graceful degrade on decline.

TDD RED phase: these fail before scripts/toolchain_install.py lands.

Contract:
1. INSTALL_PLANS keys the auto-installable items (pefile/floss/die/ghidra)
   plus the never-auto-installed IDA (kind="mcp_url").
2. install_commands() returns platform-appropriate commands
   (pip/uv for pefile+floss, brew/choco/apt for die+ghidra; IDA none).
3. run_install() executes the command; returns (rc, out, err).
4. register_ghidra_mcp() runs `claude mcp add ghidra -- <bridge>`;
   register_ida_mcp_url() runs the http-transport `claude mcp add` with the
   operator-supplied URL — IDA is NEVER auto-installed.
5. prompt_yes_no() NEVER reads stdin (#455): True only under assume_yes,
   everything else is the safe decline. The interactive consent/URL flow is
   the agent layer's job (pending-decision list + --resolve; #451 menu).
6. degrade_report() maps a failed item to WARN (static-ok) or HARD
   (decompiler) by returning a NEW report with the item degraded.
7. ask_then_install() re-probes via toolchain.check after a successful
   install and returns the fresh report; on decline/install-failure it
   returns the degraded report.
"""
from __future__ import annotations

from pathlib import Path

import subprocess

import pytest

import toolchain as tc
import toolchain_install as ti


def _cp(argv: list[str], rc: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess:
    """CompletedProcess stub matching the real subprocess.run return contract."""
    return subprocess.CompletedProcess(args=argv, returncode=rc,
                                       stdout=out, stderr=err)


# ---------- install-plan shape ----------

def test_plan_keys_and_kinds():
    """Auto-installable items (pefile/floss/die/ghidra) are kind='auto';
    IDA is never auto-installed (kind='mcp_url')."""
    assert set(ti.INSTALL_PLANS) >= {"pefile", "floss", "die", "decompiler", "ida"}
    for name in ("pefile", "floss", "die", "decompiler"):
        assert ti.INSTALL_PLANS[name].kind == "auto", f"{name} must be auto-installable"
    assert ti.INSTALL_PLANS["ida"].kind == "mcp_url", \
        "IDA must never be auto-installed — only an MCP URL is registered"
    assert ti.INSTALL_PLANS["decompiler"].degrade == "HARD", \
        "decompiler-missing degrades HARD (cannot decompile native code)"
    for name in ("pefile", "floss", "die"):
        assert ti.INSTALL_PLANS[name].degrade == "WARN", \
            f"{name} missing degrades WARN (static analysis proceeds degraded)"


def test_install_commands_platform_matrix(monkeypatch):
    """Platform-appropriate commands: pip/uv for pefile+floss,
    brew/choco/apt for die+ghidra; IDA carries none."""
    # Windows (choco)
    monkeypatch.setattr(ti.sys, "platform", "win32")
    cmds = ti.install_commands("die")
    assert cmds and "choco install" in " ".join(cmds), cmds
    # macOS (brew)
    monkeypatch.setattr(ti.sys, "platform", "darwin")
    cmds = ti.install_commands("die")
    assert cmds and "brew install" in " ".join(cmds), cmds
    # Linux (apt)
    monkeypatch.setattr(ti.sys, "platform", "linux")
    cmds = ti.install_commands("die")
    assert cmds and "apt-get install" in " ".join(cmds), cmds
    # pefile via python package manager on any platform
    cmds = ti.install_commands("pefile")
    assert cmds and ("pip install" in " ".join(cmds)
                     or "uv pip install" in " ".join(cmds)), cmds
    # IDA: never auto-install — no commands, and the plan is mcp_url
    assert ti.install_commands("ida") == [], \
        "IDA must never yield an install command"
    assert ti.INSTALL_PLANS["ida"].degrade == "WARN", \
        "IDA absence degrades WARN (the decompiler item carries the HARD tier)"


def test_install_commands_unknown_item():
    with pytest.raises(KeyError):
        ti.install_commands("not-a-tool")


# ---------- install execution ----------

def test_run_install_executes_command(monkeypatch):
    """run_install() executes the given argv list and returns (rc, stdout, stderr)."""
    log: list[list[str]] = []

    def fake_run(argv, **kw):
        log.append(argv)
        return _cp(argv, rc=0, out="installed OK")

    monkeypatch.setattr(ti, "_subprocess_run", fake_run)
    rc, out, err = ti.run_install(["pip", "install", "pefile"])
    assert rc == 0 and "installed OK" in out
    assert log == [["pip", "install", "pefile"]]


def test_run_install_reports_failure(monkeypatch):
    def fake_run(argv, **kw):
        return _cp(argv, rc=1, err="network error")

    monkeypatch.setattr(ti, "_subprocess_run", fake_run)
    rc, out, err = ti.run_install(["pip", "install", "floss"])
    assert rc == 1 and "network error" in err


# ---------- MCP registration ----------

def test_register_ghidra_mcp(monkeypatch, tmp_path):
    """register_ghidra_mcp() runs `claude mcp add ghidra -- <bridge>` with a
    resolvable bridge path; the command is logged for assertion."""
    log: list[list[str]] = []
    bridge = tmp_path / "bridge-mcp-ghidra"

    def fake_run(argv, **kw):
        log.append(argv)
        return _cp(argv)

    monkeypatch.setattr(ti, "_subprocess_run", fake_run)
    monkeypatch.setattr(ti.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(ti, "_bridge_mcp_path", lambda: str(bridge))
    rc = ti.register_ghidra_mcp()
    assert rc == 0
    assert len(log) == 1
    assert log[0][0].endswith("claude"), log[0]
    assert log[0][1:] == ["mcp", "add", "ghidra", "--", str(bridge)], log[0]


def test_register_ida_mcp_url(monkeypatch):
    """register_ida_mcp_url() registers the operator-supplied URL via the
    http transport — it never installs the IDA product."""
    log: list[list[str]] = []

    def fake_run(argv, **kw):
        log.append(argv)
        return _cp(argv)

    monkeypatch.setattr(ti, "_subprocess_run", fake_run)
    monkeypatch.setattr(ti.shutil, "which", lambda name: "/usr/local/bin/claude")
    rc = ti.register_ida_mcp_url("http://localhost:13337")
    assert rc == 0
    assert len(log) == 1
    assert log[0][0].endswith("claude"), log[0]
    assert log[0][1:5] == ["mcp", "add", "--transport", "http"], log[0]
    assert log[0][-1] == "http://localhost:13337", log[0]


# ---------- consent gate (#455: stdin is NOT a user channel) ----------

def test_prompt_yes_no_never_reads_stdin(monkeypatch):
    """#455: even a TTY-looking stdin that would answer 'y' is IGNORED —
    input() must never be called; consent comes only from --assume-yes."""
    import builtins

    def _boom(*_args):
        raise AssertionError("input() must never be called (#455)")

    monkeypatch.setattr(builtins, "input", _boom)
    monkeypatch.setattr(ti.sys, "stdin",
                       type("SI", (), {"isatty": lambda self: True})())
    assert ti.prompt_yes_no("install pefile?") is False


def test_prompt_yes_no_decline_default():
    """No consent channel -> safe decline (never hang a headless run)."""
    assert ti.prompt_yes_no("install pefile?") is False


def test_prompt_yes_no_assume_yes():
    assert ti.prompt_yes_no("install pefile?", assume_yes=True) is True


# ---------- degrade ----------

def _report(*fails: str) -> tc.ToolchainReport:
    items = []
    for name in ("pefile", "die", "floss", "decompiler", "ida"):
        status = tc.Status.FAIL if name in fails else tc.Status.PASS
        items.append(tc.CheckResult(name=name, status=status, tier=tc.Tier.HARD,
                                    detail="probe detail"))
    return tc.ToolchainReport(project_type="windows", items=items)


def test_degrade_static_item_to_warn():
    """pefile/die/floss degrade to WARN (HARD tier kept); decompiler stays HARD."""
    r = ti.degrade_report(_report("pefile"), "pefile")
    item = next(i for i in r.items if i.name == "pefile")
    assert item.status == tc.Status.WARN, item
    assert item.tier == tc.Tier.HARD, item


def test_degrade_decompiler_stays_hard():
    r = ti.degrade_report(_report("decompiler"), "decompiler")
    item = next(i for i in r.items if i.name == "decompiler")
    assert item.status == tc.Status.FAIL, \
        "decompiler missing must remain HARD (cannot proceed without one)"


def test_degrade_report_returns_new_object():
    """Immutable pattern: degrade_report returns a NEW report, input untouched."""
    orig = _report("pefile")
    r = ti.degrade_report(orig, "pefile")
    assert r is not orig
    assert next(i for i in orig.items if i.name == "pefile").status == tc.Status.FAIL


# ---------- ask_then_install orchestration ----------

def test_ask_then_install_consent_reprobes(monkeypatch):
    """Consent (--assume-yes, #455: no stdin) -> install runs -> re-probe via
    toolchain.check returns the fresh PASS report; the degraded input report
    is replaced."""
    calls: list[str] = []

    def fake_install(name, plan, assume_yes, ws):
        calls.append(f"install:{name}")
        return (0, "ok", "")

    def fake_reprobe(ws, project_type):
        calls.append(f"reprobe:{project_type}")
        return tc.ToolchainReport(project_type=project_type, items=[
            tc.CheckResult(name="pefile", status=tc.Status.PASS,
                           tier=tc.Tier.HARD, detail="now present"),
        ])

    monkeypatch.setattr(ti, "_run_install_plan", fake_install)
    monkeypatch.setattr(ti.toolchain, "check", fake_reprobe)

    r = ti.ask_then_install(_report("pefile"), ws=Path("/tmp/ws"),
                            project_type="windows", assume_yes=True)
    assert calls == ["install:pefile", "reprobe:windows"], calls
    assert r.overall_status == tc.Status.PASS, r


def test_ask_then_install_decline_degrades(monkeypatch):
    """Decline (default, no consent channel #455) -> no install, no re-probe;
    the item is degraded (WARN)."""
    calls: list[str] = []

    monkeypatch.setattr(ti, "_run_install_plan",
                        lambda name, plan, assume_yes, ws: calls.append(f"install:{name}") or (1, "", "declined"))
    monkeypatch.setattr(ti.toolchain, "check",
                        lambda ws, project_type: calls.append("reprobe") or tc.ToolchainReport(project_type=project_type, items=[]))

    r = ti.ask_then_install(_report("pefile"), ws=Path("/tmp/ws"),
                            project_type="windows", assume_yes=False)
    assert calls == [], f"decline must not install or re-probe: {calls}"
    item = next(i for i in r.items if i.name == "pefile")
    assert item.status == tc.Status.WARN, item


def test_ask_then_install_install_failure_degrades(monkeypatch):
    """Install command fails -> official guidance path; item degraded, no re-probe."""
    calls: list[str] = []

    def fake_install(name, plan, assume_yes, ws):
        calls.append(f"install:{name}")
        return (1, "", "brew failed: no network")

    monkeypatch.setattr(ti, "_run_install_plan", fake_install)
    monkeypatch.setattr(ti.toolchain, "check",
                        lambda ws, project_type: calls.append("reprobe") or tc.ToolchainReport(project_type=project_type, items=[]))

    r = ti.ask_then_install(_report("die"), ws=Path("/tmp/ws"),
                            project_type="windows", assume_yes=True)
    assert calls == ["install:die"], calls
    item = next(i for i in r.items if i.name == "die")
    assert item.status == tc.Status.WARN, item


def test_ask_then_install_ida_degrades_with_guidance(monkeypatch, capsys):
    """#455: the IDA branch can no longer collect a URL via stdin — it prints
    the manual `claude mcp add` guidance, degrades the item (WARN), and never
    runs an install plan. register_ida_mcp_url stays the #451-menu primitive."""
    calls: list[str] = []
    calls2: list[str] = []
    monkeypatch.setattr(ti, "_run_install_plan",
                        lambda name, plan, assume_yes, ws: calls.append(f"install:{name}") or (0, "", ""))
    monkeypatch.setattr(ti.toolchain, "check",
                        lambda ws, project_type: tc.ToolchainReport(project_type=project_type, items=[]))
    monkeypatch.setattr(ti, "register_ida_mcp_url",
                        lambda url: calls2.append(url) or 0)

    r = ti.ask_then_install(_report("ida"), ws=Path("/tmp/ws"),
                            project_type="windows", assume_yes=True)
    assert calls == [], "IDA must never be auto-installed (no install plan runs)"
    assert calls2 == [], "no URL may be collected from stdin (#455)"
    item = next(i for i in r.items if i.name == "ida")
    assert item.status == tc.Status.WARN, item
    err = capsys.readouterr().err
    assert "claude mcp add" in err, "manual registration guidance must be printed"
