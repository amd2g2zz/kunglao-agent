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

import sys
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


def test_install_commands_detection_matrix(monkeypatch):
    """#477: commands are assembled from (manager, package) DATA x
    DETECTED managers — the sys.platform hardcode is gone.

    Issue acceptance 2: winget present + choco absent on win32 -> the
    winget plan is selected (docker carries a winget spec); die carries
    no winget package, so a winget-only Windows yields NO command (the
    choco suggestion no longer dead-ends pretending choco exists)."""
    def _hits(*names):
        import pkg_detect
        return [pkg_detect.ManagerHit(name=n, path=f"/fake/{n}",
                                      source="PATH") for n in names]

    # win32 + winget only -> winget-spec items resolve via winget
    monkeypatch.setattr(ti, "_detect_managers", lambda platform=None: _hits("winget"))
    cmds = ti.install_commands("docker")
    assert cmds and cmds[:2] == ["winget", "install"], cmds
    # die has no winget package: honest empty (manual guidance via
    # resolve_install) instead of a fabricated choco command
    assert ti.install_commands("die") == []
    res = ti.resolve_install("die")
    assert res.mode == "manual" and res.next_action is not None
    assert res.next_action.action == "install"
    assert "choco" in (res.next_action.command or ""), res.next_action

    # choco present -> die resolves through choco
    monkeypatch.setattr(ti, "_detect_managers", lambda platform=None: _hits("choco"))
    cmds = ti.install_commands("die")
    assert cmds and "choco install" in " ".join(cmds), cmds

    # brew (darwin) -> die via brew
    monkeypatch.setattr(ti, "_detect_managers", lambda platform=None: _hits("brew"))
    cmds = ti.install_commands("die")
    assert cmds and "brew install" in " ".join(cmds), cmds

    # pefile via python package manager on any platform
    monkeypatch.setattr(ti, "_detect_managers", lambda platform=None: _hits("pip"))
    cmds = ti.install_commands("pefile")
    assert cmds and ("pip install" in " ".join(cmds)
                     or "uv pip install" in " ".join(cmds)), cmds

    # IDA: never auto-install — no commands, and the plan is mcp_url
    assert ti.install_commands("ida") == [], \
        "IDA must never yield an install command"
    assert ti.INSTALL_PLANS["ida"].degrade == "WARN", \
        "IDA absence degrades WARN (the decompiler item carries the HARD tier)"


def test_resolve_install_elevation_never_autosudoes(monkeypatch):
    """#304 parity: a needs_sudo manager (apt/dnf/apk/pacman) resolves to
    mode 'elevation' — the exact sudo-prefixed command is PRINTED for the
    human, never auto-executed by _run_install_plan."""
    import pkg_detect
    monkeypatch.setattr(
        ti, "_detect_managers",
        lambda platform=None: [pkg_detect.ManagerHit(
            name="apt", path="/usr/bin/apt-get", source="known-path")])
    res = ti.resolve_install("docker")
    assert res.mode == "elevation", res
    assert res.manager == "apt"
    assert res.argv and res.argv[0] == "apt-get", res.argv

    ran: list[list[str]] = []
    monkeypatch.setattr(ti, "_subprocess_run",
                        lambda argv, **kw: ran.append(argv) or _cp(argv))
    rc, out, err = ti._run_install_plan("docker", ti.INSTALL_PLANS["docker"],
                                        True, Path("/tmp/ws"))
    assert rc != 0 and "elevation" in err, (rc, err)
    assert ran == [], "an elevation-required install must never auto-run"


def test_resolve_install_setenv_for_unpacked_ghidra(tmp_path, monkeypatch):
    """Issue acceptance 3: an unpacked ghidra directory already on disk ->
    the recommendation is 'configure GHIDRA_HOME', not a reinstall."""
    ghidra = tmp_path / "ghidra_11.3_PUBLIC"
    (ghidra / "support").mkdir(parents=True)
    ah_name = "analyzeHeadless.bat" if sys.platform == "win32" \
        else "analyzeHeadless"
    (ghidra / "support" / ah_name).write_text("@echo off\n", encoding="utf-8")
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    monkeypatch.setenv("KUNGLAO_TOOL_DIRS", str(tmp_path))
    monkeypatch.setattr(ti, "_detect_managers", lambda platform=None: [])
    res = ti.resolve_install("decompiler")
    assert res.mode == "set-env", res
    assert res.next_action is not None
    assert res.next_action.action == "set-env"
    assert str(ghidra) in (res.next_action.command or ""), res.next_action


def test_resolve_install_mcp_url_is_none():
    res = ti.resolve_install("ida")
    assert res.mode == "none" and res.argv == [], res


def test_resolve_install_unknown_item():
    with pytest.raises(KeyError):
        ti.resolve_install("not-a-tool")


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


# ---------- degrade detail wording (#451 review M-1) ----------
# "declined" is reserved for a REAL user choice (--resolve on the
# negotiation surface); this module has no user channel left (#455), so
# its degrade details must say why WITHOUT that word.

def test_degrade_report_default_reason_is_no_consent_not_declined():
    """Default reason (the standalone CLI headless decline): the REPORT
    detail says 'no consent channel (non-interactive)' — never 'declined'."""
    r = ti.degrade_report(_report("pefile"), "pefile")
    item = next(i for i in r.items if i.name == "pefile")
    assert "declined" not in item.detail, item.detail
    assert "no consent channel (non-interactive, #455)" in item.detail
    assert "static analysis proceeds degraded (WARN, #408)" in item.detail


def test_degrade_report_hard_item_detail_no_consent_not_declined():
    """Same pin on the decompiler (HARD) branch of the no-choice path."""
    r = ti.degrade_report(_report("decompiler"), "decompiler")
    item = next(i for i in r.items if i.name == "decompiler")
    assert "declined" not in item.detail, item.detail
    assert "no consent channel (non-interactive, #455)" in item.detail
    assert "this item is REQUIRED and stays HARD (#408)" in item.detail


def test_degrade_report_install_failed_reason_wording():
    """reason=DEGRADE_INSTALL_FAILED (a consented install that ran and
    failed): 'install failed' wording, still never 'declined'; the CLI
    --json 'degraded' key still rides on the WARN branch text."""
    r = ti.degrade_report(_report("pefile"), "pefile",
                          reason=ti.DEGRADE_INSTALL_FAILED)
    item = next(i for i in r.items if i.name == "pefile")
    assert "declined" not in item.detail, item.detail
    assert (" — install failed; "
            "static analysis proceeds degraded (WARN, #408)") in item.detail


def test_degrade_report_unknown_reason_fails_closed():
    with pytest.raises(ValueError):
        ti.degrade_report(_report("pefile"), "pefile", reason="declined")


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


def test_ask_then_install_decline_report_detail_not_declined(monkeypatch):
    """M-1 end-to-end (REPORT surface, not the print stream): a headless
    decline's resolved report — what format_human / --json consume —
    carries the no-consent wording and never 'declined'."""
    monkeypatch.setattr(ti, "_run_install_plan",
                        lambda name, plan, assume_yes, ws: (1, "", "unreached"))
    monkeypatch.setattr(ti.toolchain, "check",
                        lambda ws, project_type: tc.ToolchainReport(
                            project_type=project_type, items=[]))

    r = ti.ask_then_install(_report("pefile"), ws=Path("/tmp/ws"),
                            project_type="windows", assume_yes=False)
    item = next(i for i in r.items if i.name == "pefile")
    assert item.status == tc.Status.WARN, item
    assert "declined" not in item.detail, item.detail
    assert "no consent channel" in item.detail, item.detail
    assert "declined" not in tc.format_human(r)


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


def test_ask_then_install_ida_report_detail_not_declined(monkeypatch):
    """M-1: the IDA mcp_url degrade is a no-user-choice path too — its
    REPORT detail (what format_human / --json consume), not just the
    stderr guidance, must not claim 'declined'."""
    monkeypatch.setattr(ti.toolchain, "check",
                        lambda ws, project_type: tc.ToolchainReport(
                            project_type=project_type, items=[]))

    r = ti.ask_then_install(_report("ida"), ws=Path("/tmp/ws"),
                            project_type="windows", assume_yes=True)
    item = next(i for i in r.items if i.name == "ida")
    assert item.status == tc.Status.WARN, item
    assert "declined" not in item.detail, item.detail
    assert "no consent channel" in item.detail, item.detail


# ---------- #477 ②: coverage — closed declaration over the check surface ----------

def test_coverage_closed_declaration_covers_check_sets():
    """Every toolchain check item is classified: either it carries an
    InstallPlan (auto-installable) or it is declared NOT_AUTO_INSTALLABLE
    with a reason. 100% classified, no overlap, no invention (structural
    declaration — the memory doctrine)."""
    all_items: set[str] = set()
    for type_items in tc.CHECK_SETS.values():
        all_items |= set(type_items)
    auto = set(ti.INSTALL_PLANS)
    declared = set(ti.NOT_AUTO_INSTALLABLE)
    assert auto >= {"pefile", "floss", "die", "decompiler", "ida"}
    assert len(auto) >= 12, f"coverage expansion required (5 -> >=12): {len(auto)}"
    missing = all_items - auto - declared
    assert not missing, f"unclassified check items: {sorted(missing)}"
    overlap = auto & declared
    assert not overlap, f"items both auto and declared-not-auto: {overlap}"
    for name, reason in ti.NOT_AUTO_INSTALLABLE.items():
        assert isinstance(reason, str) and reason.strip(), (
            f"NOT_AUTO_INSTALLABLE[{name!r}] must carry a reason")


def test_coverage_every_auto_plan_has_package_data():
    """kind='auto' without package data would resolve to manual forever —
    a silent coverage hole (the issue's original 5/31 complaint)."""
    for name, plan in ti.INSTALL_PLANS.items():
        if plan.kind == "auto":
            assert plan.packages, f"{name}: auto plan with no packages"


def test_not_auto_family_membership_pinned():
    """FAULT-INJECT M8 pin (survivor 8): every never-auto family item
    (VM channel / device-side / host-property) is declared in
    NOT_AUTO_INSTALLABLE with a reason AND carries NO InstallPlan.

    Complements test_coverage_closed_declaration_covers_check_sets, which
    only pins union-completeness + no-overlap + auto>=12 — all three are
    INVARIANT under a side swap (moving vm_reachable into INSTALL_PLANS
    kept that test green while resolve_install fabricated
    `winget install VMware.WorkstationPro` for a VM-CHANNEL item). Only
    a per-item attribution pin notices the swap."""
    never_auto_family = {
        "vm_reachable", "remote_debugger",   # VM channel (#408, #451 vm-*)
        "device_root", "debug_flag",         # human/device property
        "frida_server", "android_server",    # device-side deploy (#477 ③)
        "jdwp_debug",                        # running-app capability
        "ebpf", "ebpf_android",              # kernel/SDK properties
        "unidbg",                            # Java library, not a CLI
    }
    for name in never_auto_family:
        assert name in ti.NOT_AUTO_INSTALLABLE, (
            f"{name} must stay declared NOT_AUTO_INSTALLABLE "
            f"(family: never auto-installed)")
        reason = ti.NOT_AUTO_INSTALLABLE[name]
        assert isinstance(reason, str) and reason.strip(), (
            f"NOT_AUTO_INSTALLABLE[{name!r}] must carry a reason")
        assert name not in ti.INSTALL_PLANS, (
            f"{name} must never carry an InstallPlan — a side swap broke "
            f"the closed declaration (union test cannot see this)")
    # Generic vm_* leak scan: the VM channel is a human event (#408) —
    # no vm_* item may ever resolve to a package install.
    vm_leaked = sorted(n for n in ti.INSTALL_PLANS if n.startswith("vm_"))
    assert not vm_leaked, f"VM-channel items must not be installable: {vm_leaked}"


# ---------- #477 ④: unified re-probe loop -> env-facts installed ledger ----------

def test_ask_then_install_records_installed_ledger(monkeypatch, tmp_path):
    """④: a consented successful install re-probes AND the outcome lands
    in <ws>/env-facts.yaml installed.<name> = {manager, at, reprobe}."""
    ws = tmp_path / "ws"
    recorded: dict = {}

    import env_manifest
    monkeypatch.setattr(env_manifest, "record_installed",
                        lambda ws_arg, name, manager, reprobe, at=None:
                        recorded.update(name=name, manager=manager,
                                        reprobe=reprobe) or True)

    def fake_install(name, plan, assume_yes, ws_arg):
        return (0, "ok", "")

    def fake_reprobe(ws_arg, project_type, caps=False, task_spec=None):
        return tc.ToolchainReport(project_type=project_type, items=[
            tc.CheckResult(name="pefile", status=tc.Status.PASS,
                           tier=tc.Tier.HARD, detail="now present"),
        ])

    monkeypatch.setattr(ti, "_run_install_plan", fake_install)
    monkeypatch.setattr(ti.toolchain, "check", fake_reprobe)
    import pkg_detect
    monkeypatch.setattr(ti, "_detect_managers",
                        lambda platform=None: [pkg_detect.ManagerHit(
                            name="pip", path="/x/pip", source="PATH")])

    r = ti.ask_then_install(_report("pefile"), ws=ws,
                            project_type="windows", assume_yes=True)
    assert r.overall_status == tc.Status.PASS
    assert recorded["name"] == "pefile", recorded
    assert recorded["manager"] == "pip", recorded
    assert recorded["reprobe"] == "PASS", recorded


def test_ask_then_install_failed_install_records_nothing(
        monkeypatch, tmp_path):
    """④: an install that FAILS takes the degrade+NextAction path — no
    installed-ledger entry (the failure surface is the guidance, not the
    ledger)."""
    ws = tmp_path / "ws"
    recorded: list[str] = []
    import env_manifest
    monkeypatch.setattr(env_manifest, "record_installed",
                        lambda *a, **kw: recorded.append("x") or True)

    monkeypatch.setattr(ti, "_run_install_plan",
                        lambda name, plan, assume_yes, ws_arg:
                        (1, "", "network down"))
    monkeypatch.setattr(ti.toolchain, "check",
                        lambda ws_arg, project_type, caps=False,
                        task_spec=None: tc.ToolchainReport(
                            project_type=project_type, items=[]))
    r = ti.ask_then_install(_report("pefile"), ws=ws,
                            project_type="windows", assume_yes=True)
    item = next(i for i in r.items if i.name == "pefile")
    assert item.status == tc.Status.WARN, item
    assert recorded == []


def test_cli_end_to_end_one_command(monkeypatch, tmp_path, capsys):
    """④ 'one command testable end-to-end': the standalone CLI runs the
    whole chain probe -> ask(--assume-yes) -> install -> re-probe ->
    env-facts ledger against seams."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)

    def fake_check(ws_arg, project_type=None, caps=False, task_spec=None):
        calls.append("check")
        return tc.ToolchainReport(project_type="windows", items=[
            tc.CheckResult(name="pefile",
                           status=tc.Status.FAIL if calls.count("check") == 1
                           else tc.Status.PASS,
                           tier=tc.Tier.HARD, detail="probe"),
        ])

    calls: list[str] = []
    monkeypatch.setattr(tc, "load_task_spec", lambda ws_arg: None)
    monkeypatch.setattr(ti.toolchain, "check", fake_check)
    monkeypatch.setattr(ti, "_run_install_plan",
                        lambda name, plan, assume_yes, ws_arg:
                        calls.append(f"install:{name}") or (0, "ok", ""))
    import pkg_detect
    monkeypatch.setattr(ti, "_detect_managers",
                        lambda platform=None: [pkg_detect.ManagerHit(
                            name="pip", path="/x/pip", source="PATH")])
    ledger: list[str] = []
    import env_manifest
    monkeypatch.setattr(env_manifest, "record_installed",
                        lambda ws_arg, name, manager, reprobe, at=None:
                        ledger.append(f"{name}:{manager}:{reprobe}") or True)

    rc = ti.main([str(ws), "--type", "windows", "--assume-yes", "--json"])
    assert rc == 0, rc
    assert calls == ["check", "install:pefile", "check"], calls
    assert ledger == ["pefile:pip:PASS"], ledger
    out = capsys.readouterr().out
    assert '"overall": "PASS"' in out, out
