# -*- coding: utf-8 -*-
"""Tests for the #304 design amendment (comment 304-5289955958):

init toolchain validation = validate-first + remind human + refuse + cleanup.

  1. toolchain.check runs BEFORE scaffold (type -> toolchain.check -> PASS
     only then scaffold)
  2. HARD FAIL -> refuse init: non-zero exit + per-item friendly install
     commands (human installs) + no [initialized] marker
  3. cleanup (F2): only items created by THIS run are removed; pre-existing
     files / non-empty dirs (real facts) are preserved + notified
  4. no-sample cold start -> friendly prompt (bins/ empty)

TDD RED phase: these fail before the kunglao-init.py amendment lands.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

import platform_paths  # pytest.ini pythonpath = . hooks scripts tools

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

# Exit codes introduced by the amendment (documented in kunglao-init module docstring)
RC_TOOLCHAIN_REFUSE = 4
RC_NO_SAMPLE = 5


def _write_fake_headless(root: Path) -> Path:
    """Write a fake analyzeHeadless at the PLATFORM-correct name under
    root/support (#409: .bat on Windows, no extension on POSIX)."""
    support = root / "support"
    support.mkdir(parents=True, exist_ok=True)
    headless = support / platform_paths.analyze_headless_name()
    headless.write_text("@echo off\r\n", encoding="utf-8")
    return headless


@pytest.fixture
def gate_ws(tmp_path: Path) -> Path:
    """Workspace with a PE sample; NO toolchain on PATH (hostile env for the
    toolchain gate: PATH -> empty dir, GHIDRA_HOME/KUNGLAO_VM_HOST stripped)."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    return ws


def _run_init(ws: Path, extra: list[str] | None = None,
              profile_root: Path | None = None,
              flag: str | None = "0",
              claude_json: Path | None = None) -> subprocess.CompletedProcess:
    """Run kunglao-init hermetically with a HOSTILE toolchain env:
    PATH -> empty dir (no die/floss/jadx/...), GHIDRA_HOME + KUNGLAO_VM_HOST
    removed -> toolchain HARD checks FAIL deterministically."""
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *(extra or [])]
    if profile_root is None:
        profile_root = ws.parent / "profile-root"
    argv += ["--profile-root", str(profile_root)]
    env = {k: v for k, v in os.environ.items()
           if k not in (FLAG_NAME, "GHIDRA_HOME", "KUNGLAO_VM_HOST",
                        "KUNGLAO_CLAUDE_JSON")}
    env["PATH"] = str(ws.parent / "empty-bin")
    env["PYTHONIOENCODING"] = "utf-8"
    if claude_json is not None:
        env["KUNGLAO_CLAUDE_JSON"] = str(claude_json)
    if flag is not None:
        env[FLAG_NAME] = flag
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen in name blocks direct import)."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_gate_under_test", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- 1. toolchain-check-first ordering ----------

def test_hard_fail_refuses_no_scaffold(gate_ws):
    """HARD fail -> refuse: exit 4, NO scaffold files created
    (claim-register / analysis_state / CLAUDE.md / runs/ all absent)."""
    r = _run_init(gate_ws, ["--type", "windows"])
    assert r.returncode == RC_TOOLCHAIN_REFUSE, \
        f"expected toolchain refusal {RC_TOOLCHAIN_REFUSE}, got {r.returncode}: {r.stdout}{r.stderr}"
    assert not (gate_ws / "claim-register.yaml").exists(), "scaffold leaked on refusal"
    assert not (gate_ws / "analysis_state.txt").exists(), "scaffold leaked on refusal"
    assert not (gate_ws / "CLAUDE.md").exists(), "scaffold leaked on refusal"
    assert not (gate_ws / "global_plan.txt").exists(), "scaffold leaked on refusal"


def test_refuse_prints_per_item_install_guidance(gate_ws):
    """Refusal output carries per-item friendly install commands (human installs)."""
    r = _run_init(gate_ws, ["--type", "windows"])
    assert r.returncode == RC_TOOLCHAIN_REFUSE
    out = r.stdout + r.stderr
    assert "fix:" in out, f"per-item fix guidance missing: {out}"
    # At least one concrete install command must be named
    assert ("pip install" in out or "GHIDRA_HOME" in out
            or "KUNGLAO_VM_HOST" in out or "install" in out.lower()), \
        f"install guidance missing: {out}"


def test_refuse_does_not_mark_initialized(gate_ws):
    """Refused init must not leave a [initialized] marker anywhere."""
    r = _run_init(gate_ws, ["--type", "windows"])
    assert r.returncode == RC_TOOLCHAIN_REFUSE
    assert not (gate_ws / "claim-register.yaml").exists(), \
        "claim-register must not exist after refusal (no [initialized] marker)"
    assert "NOT initialized" in r.stderr or "not initialized" in (r.stdout + r.stderr).lower()


# ---------- 2. cleanup: pre-existing content PROTECTED (F2 #304 review) ----------

def test_partial_scaffold_preserved_on_refusal(gate_ws):
    """F2: pre-existing scaffold artifacts (e.g. an earlier interrupted run)
    are NOT deleted on refusal — refuse + notify (protected). User content
    (bins/, CLAUDE.md) preserved as before."""
    # Simulate a partial previous run
    (gate_ws / "analysis_state.txt").write_text("agent_teams_flag=0\n", encoding="utf-8")
    (gate_ws / "global_plan.txt").write_text("# stub\n", encoding="utf-8")
    (gate_ws / "facts").mkdir(exist_ok=True)
    (gate_ws / "facts" / "F001.md").write_text("# fact\n", encoding="utf-8")
    (gate_ws / "blockers").mkdir(exist_ok=True)
    user_claude = gate_ws / "CLAUDE.md"
    user_claude.write_text("# USER CONTENT\n", encoding="utf-8")

    r = _run_init(gate_ws, ["--type", "windows"])
    assert r.returncode == RC_TOOLCHAIN_REFUSE
    assert (gate_ws / "analysis_state.txt").exists(), "pre-existing state file deleted"
    assert (gate_ws / "global_plan.txt").exists(), "pre-existing plan file deleted"
    assert (gate_ws / "facts" / "F001.md").exists(), "pre-existing fact deleted"
    assert (gate_ws / "blockers").exists(), "pre-existing dir deleted"
    assert "preserv" in r.stderr.lower(), \
        f"cleanup must notify protected pre-existing content: {r.stderr}"
    # User content preserved
    assert user_claude.exists(), "user CLAUDE.md must survive cleanup"
    assert (gate_ws / "bins" / "sample.exe").exists(), "bins/ must survive cleanup"


def test_refuse_preserves_real_facts_unmarked_register(gate_ws):
    """F2(a): register WITHOUT [initialized] marker + real facts/F001.md ->
    toolchain refusal (exit 4) must NOT delete the real fact file nor the
    register (old code rmtree'd them unconditionally — data loss)."""
    (gate_ws / "facts").mkdir()
    fact = gate_ws / "facts" / "F001.md"
    fact.write_text("# fact: real evidence\n", encoding="utf-8")
    reg = gate_ws / "claim-register.yaml"
    reg.write_text("claims:\n- id: C-099\n  status: OPEN\n", encoding="utf-8")

    r = _run_init(gate_ws, ["--type", "windows"])
    assert r.returncode == RC_TOOLCHAIN_REFUSE, \
        f"expected toolchain refusal: {r.stdout}{r.stderr}"
    assert fact.exists(), "CRITICAL: real fact file was deleted on refusal"
    assert "# fact: real evidence" in fact.read_text(encoding="utf-8"), \
        "CRITICAL: fact content was destroyed on refusal"
    assert reg.exists(), "register without marker must survive refusal"
    assert "C-099" in reg.read_text(encoding="utf-8"), \
        "register content must survive refusal"


def test_force_refuse_preserves_initialized_workspace(gate_ws):
    """F2(b): --force on an INITIALIZED workspace + toolchain failure ->
    exit 4 while the register (still [initialized]) and real facts SURVIVE —
    symmetric with the successful --force path, which also keeps facts."""
    reg = gate_ws / "claim-register.yaml"
    reg.write_text(
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n",
        encoding="utf-8",
    )
    (gate_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=windows\n", encoding="utf-8",
    )
    (gate_ws / "facts").mkdir()
    fact = gate_ws / "facts" / "F001.md"
    fact.write_text("# fact: real evidence\n", encoding="utf-8")

    r = _run_init(gate_ws, ["--type", "windows", "--force"])
    assert r.returncode == RC_TOOLCHAIN_REFUSE, \
        f"expected toolchain refusal: {r.stdout}{r.stderr}"
    assert fact.exists() and "# fact: real evidence" in fact.read_text(encoding="utf-8"), \
        "CRITICAL: --force refusal deleted real facts"
    assert "[initialized]" in reg.read_text(encoding="utf-8"), \
        "register must survive refusal with its [initialized] marker intact"
    state = (gate_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=windows" in state, "analysis_state must survive refusal"


def test_cleanup_scaffold_removes_only_run_created(tmp_path):
    """F2: cleanup_scaffold(ws, created=...) deletes ONLY paths in the
    created manifest; pre-existing files/non-empty dirs are protected."""
    mod = _load_init_module()
    ws = tmp_path / "ws"
    ws.mkdir()
    mine_file = ws / "global_plan.txt"
    mine_file.write_text("# stub\n", encoding="utf-8")
    pre_file = ws / "analysis_state.txt"
    pre_file.write_text("agent_teams_flag=0\n", encoding="utf-8")
    pre_dir = ws / "facts"
    pre_dir.mkdir()
    (pre_dir / "F001.md").write_text("# fact\n", encoding="utf-8")

    removed, preserved = mod.cleanup_scaffold(ws, created={mine_file})
    assert not mine_file.exists(), "run-created file must be removed"
    assert "global_plan.txt" in removed
    assert pre_file.exists(), "pre-existing file must survive"
    assert (pre_dir / "F001.md").exists(), "pre-existing non-empty dir must survive"
    assert "analysis_state.txt" in preserved
    assert "facts/" in preserved


def test_retry_idempotent_after_cleanup(gate_ws):
    """After a refused attempt + cleanup, a retry (toolchain satisfied via
    --skip-toolchain) succeeds cleanly — no stale state."""
    r1 = _run_init(gate_ws, ["--type", "windows"])
    assert r1.returncode == RC_TOOLCHAIN_REFUSE
    # Retry with the toolchain gate bypassed (human installed tools)
    r2 = _run_init(gate_ws, ["--type", "windows", "--skip-toolchain"])
    assert r2.returncode == 0, f"retry failed: {r2.stdout}{r2.stderr}"
    reg = (gate_ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert "[initialized]" in reg
    state = (gate_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=windows" in state


# ---------- #407: MCP-first decompiler gate (ida-pro-vm provider) ----------

def _write_ida_pro_vm_claude_json(path):
    import json
    path.write_text(json.dumps({
        "mcpServers": {
            "sequential-thinking": {"type": "stdio", "command": "st", "args": []},
            "ida-pro-vm": {"type": "http", "url": "http://localhost:13337"},
        },
    }), encoding="utf-8")


def test_init_decompiler_passes_via_ida_pro_vm_mcp(gate_ws, tmp_path):
    """#407: ida-pro-vm registered -> the decompiler + mcp:ghidra HARD checks
    PASS (MCP-first): the toolchain gate must NOT refuse on them, even in the
    hostile env where every CLI tool is absent."""
    claude_json = tmp_path / "claude.json"
    _write_ida_pro_vm_claude_json(claude_json)
    r = _run_init(gate_ws, ["--type", "windows"], claude_json=claude_json)
    out = r.stdout + r.stderr
    assert "[FAIL] decompiler" not in out, \
        f"decompiler must PASS via ida-pro-vm MCP: {out}"
    assert "[FAIL] mcp:ghidra" not in out, \
        f"ghidra supply must be satisfied by ida-pro-vm: {out}"


def test_init_still_refuses_without_any_decompiler(gate_ws, tmp_path):
    """#407: neither MCP nor CLI decompiler -> toolchain gate still REFUSEs
    (exit 4) with install guidance for the decompiler (#408)."""
    claude_json = tmp_path / "claude.json"
    claude_json.write_text("{}", encoding="utf-8")
    r = _run_init(gate_ws, ["--type", "windows"], claude_json=claude_json)
    assert r.returncode == RC_TOOLCHAIN_REFUSE, r.stdout + r.stderr
    out = r.stdout + r.stderr
    assert "[FAIL] decompiler" in out, f"decompiler FAIL missing: {out}"
    assert "#408" in out, f"installer reference (#408) missing: {out}"


# ---------- 3. PASS path: scaffold happens after check ----------

def test_toolchain_check_runs_before_scaffold(tmp_path, monkeypatch):
    """Library-level ordering: toolchain.check is called BEFORE any scaffold
    file exists (fake check asserts claim-register absent at call time)."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "s.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    profile_root = tmp_path / "profile-root"
    monkeypatch.setenv(FLAG_NAME, "0")

    mod = _load_init_module()
    import toolchain as tc
    calls: list[dict] = []

    def fake_check(ws_arg, project_type=None):
        calls.append({
            "ws": ws_arg,
            "type": project_type,
            "register_existed": (ws_arg / "claim-register.yaml").exists(),
        })
        return tc.ToolchainReport(project_type=project_type or "windows", items=[])

    monkeypatch.setattr(mod.toolchain, "check", fake_check)
    rc = mod.run(ws, project_type="windows", profile_root=profile_root)
    assert rc == 0, "PASS toolchain must proceed to scaffold"
    assert len(calls) == 1, f"toolchain.check must be called once, got {len(calls)}"
    assert calls[0]["type"] == "windows"
    assert calls[0]["register_existed"] is False, \
        "toolchain.check must run BEFORE scaffold (claim-register must not exist yet)"
    assert (ws / "claim-register.yaml").exists(), "scaffold must complete after PASS"


def test_library_refuse_returns_4_no_scaffold(tmp_path, monkeypatch):
    """Library-level: fake failing check -> exit 4, nothing scaffolded."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "s.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    monkeypatch.setenv(FLAG_NAME, "0")

    mod = _load_init_module()
    import toolchain as tc

    def fake_fail(ws_arg, project_type=None):
        return tc.ToolchainReport(project_type=project_type or "windows", items=[
            tc.CheckResult(name="gitnexus", status=tc.Status.FAIL, tier=tc.Tier.HARD,
                           detail="gitnexus not found", root_cause=None),
        ])

    monkeypatch.setattr(mod.toolchain, "check", fake_fail)
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root")
    assert rc == RC_TOOLCHAIN_REFUSE
    assert not (ws / "claim-register.yaml").exists()
    assert not (ws / "analysis_state.txt").exists()


# ---------- 4. no-sample cold start friendly prompt ----------

def test_no_sample_friendly_prompt(tmp_path):
    """bins/ empty -> friendly prompt (place a sample into bins/), non-zero exit,
    no scaffold."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "bins").mkdir()
    profile_root = tmp_path / "profile-root"
    env = {k: v for k, v in os.environ.items()
           if k not in (FLAG_NAME, "GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["PYTHONIOENCODING"] = "utf-8"
    env[FLAG_NAME] = "0"
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
         "--profile-root", str(profile_root)],
        capture_output=True, text=True, timeout=120, env=env, errors="replace",
    )
    assert r.returncode == RC_NO_SAMPLE, \
        f"expected {RC_NO_SAMPLE}, got {r.returncode}: {r.stdout}{r.stderr}"
    out = r.stdout + r.stderr
    assert "bins/" in out, f"friendly prompt must mention bins/: {out}"
    assert not (ws / "claim-register.yaml").exists()


def test_skip_toolchain_flag_bypasses_gate(gate_ws):
    """--skip-toolchain (operator/test escape hatch) -> gate skipped, init OK."""
    r = _run_init(gate_ws, ["--type", "windows", "--skip-toolchain"])
    assert r.returncode == 0, f"skip-toolchain init failed: {r.stdout}{r.stderr}"
    assert "[initialized]" in (gate_ws / "claim-register.yaml").read_text(encoding="utf-8")


# ---------- #408: ask-then-install (interactive consent + --assume-yes) ----------

def test_assume_yes_flag_parsed(tmp_path):
    """#408: kunglao-init gains --assume-yes (CI/headless consent)."""
    mod = _load_init_module()
    args = mod.parse_args([str(tmp_path / "ws"), "--assume-yes"])
    assert args.assume_yes is True


def test_run_hard_fail_with_assume_yes_calls_installer(tmp_path, monkeypatch):
    """HARD FAIL + --assume-yes -> toolchain_install.ask_then_install is called
    with assume_yes=True; a resolved-PASS report lets init proceed to scaffold."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    monkeypatch.setenv(FLAG_NAME, "0")
    mod = _load_init_module()
    import toolchain as tc

    calls: list[str] = []

    def fake_check(ws_arg, project_type=None):
        calls.append("check")
        return tc.ToolchainReport(project_type=project_type or "windows", items=[
            tc.CheckResult(name="die", status=tc.Status.FAIL, tier=tc.Tier.HARD,
                           detail="die not found in PATH"),
        ])

    def fake_ask(report, ws_arg, project_type, assume_yes=False):
        calls.append(f"ask:{assume_yes}")
        return tc.ToolchainReport(project_type=project_type, items=[
            tc.CheckResult(name="die", status=tc.Status.WARN, tier=tc.Tier.HARD,
                           detail="die degraded (#408)"),
        ])

    monkeypatch.setattr(mod.toolchain, "check", fake_check)
    monkeypatch.setattr(mod.toolchain_install, "ask_then_install", fake_ask)
    rc = mod.run(ws, project_type="windows", profile_root=tmp_path / "profile-root",
                 assume_yes=True)
    assert rc == 0, "resolved-PASS must proceed to scaffold"
    assert calls == ["check", "ask:True"], calls
    assert (ws / "claim-register.yaml").exists()


# ---------- #409: platform de-hardcoding (analyzeHeadless by sys.platform) ----------

def test_init_gate_resolves_platform_headless(tmp_path, monkeypatch):
    """#409: the init toolchain gate's decompiler check must resolve
    support/analyzeHeadless by sys.platform (.bat on Windows, no extension on
    POSIX). GHIDRA_HOME pointing at the platform-correct name -> the ghidra
    check item PASSes inside toolchain.check — the subprocess toolchain probe
    in kunglao-init uses the same resolver."""
    mod = _load_init_module()
    import toolchain as tc

    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    monkeypatch.setenv(FLAG_NAME, "0")

    ghidra_home = tmp_path / "ghidra"
    _write_fake_headless(ghidra_home)
    monkeypatch.setenv("GHIDRA_HOME", str(ghidra_home))
    monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)

    # PATH with the host tools so binutils/pefile-style probes are satisfiable
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")

    report = tc.check(ws, "linux")
    ghidra = next((i for i in report.items if i.name == "ghidra"), None)
    assert ghidra is not None, f"ghidra check missing from report: {report.items}"
    assert ghidra.status == tc.Status.PASS, \
        f"platform-correct analyzeHeadless must PASS the ghidra check on this host: {ghidra}"
    assert platform_paths.analyze_headless_name() in ghidra.detail


def test_run_hard_fail_non_tty_without_assume_yes_refuses(tmp_path, monkeypatch):
    """HARD FAIL + non-interactive stdin + no --assume-yes -> refuse exit 4
    (keeps the #304 human-install event; no silent install, no hang)."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    monkeypatch.setenv(FLAG_NAME, "0")
    mod = _load_init_module()
    import toolchain as tc

    calls: list[str] = []

    def fake_check(ws_arg, project_type=None):
        calls.append("check")
        return tc.ToolchainReport(project_type="windows", items=[
            tc.CheckResult(name="die", status=tc.Status.FAIL, tier=tc.Tier.HARD,
                           detail="die not found"),
        ])

    def fake_ask(report, ws_arg, project_type, assume_yes=False):
        calls.append("ask")
        return report

    monkeypatch.setattr(mod.toolchain, "check", fake_check)
    monkeypatch.setattr(mod.toolchain_install, "ask_then_install", fake_ask)
    monkeypatch.setattr(mod.sys, "stdin",
                       type("SI", (), {"isatty": lambda self: False})())
    rc = mod.run(ws, project_type="windows", profile_root=tmp_path / "profile-root")
    assert rc == RC_TOOLCHAIN_REFUSE
    assert "ask" not in calls, "non-interactive without --assume-yes must not ask"


def test_run_ask_result_still_hard_refuses(tmp_path, monkeypatch):
    """ask_then_install returns a report still FAIL (decompiler declined stays
    HARD) -> refuse exit 4, no scaffold."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    monkeypatch.setenv(FLAG_NAME, "0")
    mod = _load_init_module()
    import toolchain as tc

    def fake_check(ws_arg, project_type=None):
        return tc.ToolchainReport(project_type="windows", items=[
            tc.CheckResult(name="decompiler", status=tc.Status.FAIL, tier=tc.Tier.HARD,
                           detail="no decompiler found"),
        ])

    def fake_ask(report, ws_arg, project_type, assume_yes=False):
        return report  # decompiler cannot degrade -> still HARD

    monkeypatch.setattr(mod.toolchain, "check", fake_check)
    monkeypatch.setattr(mod.toolchain_install, "ask_then_install", fake_ask)
    rc = mod.run(ws, project_type="windows", profile_root=tmp_path / "profile-root",
                 assume_yes=True)
    assert rc == RC_TOOLCHAIN_REFUSE
    assert not (ws / "claim-register.yaml").exists()


def test_init_decline_degrades_warn_and_proceeds(tmp_path, monkeypatch):
    """Real ask_then_install through run(): missing die + interactive decline
    -> die degraded WARN -> resolved report no longer FAIL -> init proceeds."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    monkeypatch.setenv(FLAG_NAME, "0")
    mod = _load_init_module()
    import toolchain as tc

    def fake_check(ws_arg, project_type=None):
        return tc.ToolchainReport(project_type="windows", items=[
            tc.CheckResult(name="die", status=tc.Status.FAIL, tier=tc.Tier.HARD,
                           detail="die not found in PATH"),
        ])

    monkeypatch.setattr(mod.toolchain, "check", fake_check)
    monkeypatch.setattr(mod.sys, "stdin",
                       type("SI", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(mod.toolchain_install.builtins, "input",
                        lambda prompt="": "n")
    rc = mod.run(ws, project_type="windows", profile_root=tmp_path / "profile-root")
    assert rc == 0, "declined static item (die) must degrade WARN and proceed"
    assert (ws / "claim-register.yaml").exists()


def test_assume_yes_subprocess_attempts_install_still_refuses_decompiler(
        gate_ws, tmp_path):
    """Hostile env + --assume-yes: the ask-then-install path runs
    ('toolchain-install:' output present); pefile/die/floss degrade but the
    decompiler stays HARD -> still exit 4 (no silent PASS)."""
    claude_json = tmp_path / "claude.json"
    claude_json.write_text("{}", encoding="utf-8")
    r = _run_init(gate_ws, ["--type", "windows", "--assume-yes"],
                  claude_json=claude_json)
    out = r.stdout + r.stderr
    assert "toolchain-install" in out, f"ask-then-install path must run: {out}"
    assert r.returncode == RC_TOOLCHAIN_REFUSE, \
        f"decompiler still missing must refuse: {r.stdout}{r.stderr}"
    assert "[FAIL] decompiler" in out or "[FAIL] mcp:ghidra" in out, \
        f"hard decompiler failure must remain in the refusal output: {out}"
