# -*- coding: utf-8 -*-
"""Tests for issue #449 — init needs-first: env = f(task_spec).

The toolchain layers derive from the TASK, not the type template:
  * requirements_from_task_spec maps constraints.dynamic_re=forbidden
    (static-only) to "VM channel not needed";
  * static-only windows/linux workspaces downgrade vm_reachable /
    remote_debugger from HARD-FAIL to WARN with the task_spec basis in
    the detail (reported, never silently skipped);
  * an absent/unreadable task_spec keeps EVERY layer HARD — the output is
    byte-identical to the pre-#449 gate (backward compatibility: init
    before the needs-first intake, direct CLI calls, old test fakes);
  * kunglao-init reads task_spec before the toolchain gate and prints one
    guidance line when it is missing;
  * issue evidence 2 (2026-08-17 transcript: task_spec unanswered while the
    full VM chain was already brought up) is fixed as the negative example:
    a static-only task_spec under an otherwise-complete toolchain does NOT
    trigger the vm_reachable HARD refusal.

TDD RED phase: written BEFORE the implementation (requirements loader /
task_spec parameter / Flow step 0 do not exist yet).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SKILL_INIT = ROOT / "skills" / "init" / "SKILL.md"
AGENT_INIT_WORKER = ROOT / "agents" / "kunglao-init-worker.md"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
RC_TOOLCHAIN_REFUSE = 4

STATIC_ONLY_SPEC = {"constraints": {"dynamic_re": "forbidden",
                                    "vm_detonation": "forbidden"}}


def _write_task_spec(ws: Path, spec: dict) -> Path:
    """Write a task_spec.yaml mapping into the workspace (needs-first intake
    artifact — SKILL.md Flow step 0)."""
    import yaml
    p = ws / "task_spec.yaml"
    p.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return p


def _hermetic_env(monkeypatch, fake_bin: Path | None = None,
                  claude_json: Path | None = None) -> None:
    """Hostile toolchain env: no VM host, no GHIDRA_HOME, isolated MCP
    registry; PATH may point at a stub dir (die/floss presence).
    #451: VM discovery seams OFF (deterministic inventory — no vmrun /
    VBoxManage probing from module-level tests)."""
    import toolchain as tc
    monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    if hasattr(tc, "_vmrun_exe"):
        monkeypatch.setattr(tc, "_vmrun_exe", lambda: None)
    if hasattr(tc, "_vbox_exe"):
        monkeypatch.setattr(tc, "_vbox_exe", lambda: None)
    if fake_bin is not None:
        monkeypatch.setenv("PATH", str(fake_bin))  # replace, not prepend
    if claude_json is not None:
        monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(claude_json))
    monkeypatch.setenv(FLAG_NAME, "0")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")


def _fake_registry(tmp_path: Path, servers: list[str]) -> Path:
    p = tmp_path / "fake-claude.json"
    p.write_text(json.dumps({"mcpServers": {n: {} for n in servers}}),
                 encoding="utf-8")
    return p


def _stub_bin(tmp_path: Path, tools: tuple[str, ...] = ("die", "floss")) -> Path:
    """Stub dir satisfying shutil.which presence probes on both platforms
    (.bat on Windows via PATHEXT, extensionless executable on POSIX)."""
    fb = tmp_path / "stub-bin"
    fb.mkdir(exist_ok=True)
    for tool in tools:
        if os.name == "nt":
            (fb / f"{tool}.bat").write_text("@echo off\r\n", encoding="utf-8")
        else:
            p = fb / tool
            p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            p.chmod(0o755)
    return fb


def _ws_with_sample(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    return ws


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen in name blocks direct
    import) — same pattern as tests/test_init_toolchain_gate.py."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_needs_first_under_test", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _vm_items(report):
    return {i.name: i for i in report.items
            if i.name in ("vm_reachable", "remote_debugger")}


# ---------- requirements_from_task_spec: derivation rules ----------

def test_requirements_static_only_disables_vm():
    """constraints.dynamic_re=forbidden (static-only) → needs_vm False with
    the task_spec field cited in the basis."""
    import toolchain as tc
    reqs = tc.requirements_from_task_spec(STATIC_ONLY_SPEC)
    assert reqs.needs_vm is False, reqs
    assert "dynamic_re" in reqs.basis and "static-only" in reqs.basis, reqs


def test_requirements_dynamic_re_case_whitespace_tolerant():
    import toolchain as tc
    reqs = tc.requirements_from_task_spec(
        {"constraints": {"dynamic_re": "  Forbidden  "}})
    assert reqs.needs_vm is False, reqs


def test_requirements_conservative_family():
    """Every unreadable/missing/non-committal field keeps the conservative
    HARD default (needs_vm True) — the pre-#449 status quo."""
    import toolchain as tc
    for spec in (None, {}, {"constraints": {}},
                 {"constraints": "garbage"},
                 {"constraints": {"dynamic_re": "allowed"}},
                 {"constraints": {"dynamic_re": "maybe"}}):
        reqs = tc.requirements_from_task_spec(spec)
        assert reqs.needs_vm is True, f"{spec!r} must stay conservative: {reqs}"


def test_requirements_vm_detonation_alone_does_not_relax():
    """R1 pin: vm_detonation=forbidden alone (dynamic_re absent) does NOT
    relax the VM channel — frida-on-VM may still be the plan; per-port
    contracts are #450 env-facts scope."""
    import toolchain as tc
    reqs = tc.requirements_from_task_spec(
        {"constraints": {"vm_detonation": "forbidden"}})
    assert reqs.needs_vm is True, reqs


def test_requirements_immutable():
    import toolchain as tc
    reqs = tc.requirements_from_task_spec(STATIC_ONLY_SPEC)
    with pytest.raises(Exception):
        reqs.needs_vm = True  # type: ignore[misc]


# ---------- load_task_spec: single loading point ----------

def test_load_task_spec_absent_returns_none(tmp_path):
    import toolchain as tc
    assert tc.load_task_spec(_ws_with_sample(tmp_path)) is None


def test_load_task_spec_empty_returns_none(tmp_path):
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    (ws / "task_spec.yaml").write_text("", encoding="utf-8")
    assert tc.load_task_spec(ws) is None


def test_load_task_spec_valid_mapping(tmp_path):
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _write_task_spec(ws, STATIC_ONLY_SPEC)
    assert tc.load_task_spec(ws) == STATIC_ONLY_SPEC


def test_load_task_spec_garbage_fails_closed(tmp_path):
    """Unparseable / non-mapping task_spec → ValueError: callers must NOT
    relax anything on garbage (unreadable field = conservative HARD)."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    (ws / "task_spec.yaml").write_text("{{{ not yaml", encoding="utf-8")
    with pytest.raises(ValueError):
        tc.load_task_spec(ws)
    (ws / "task_spec.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        tc.load_task_spec(ws)


def test_load_task_spec_permission_error_fails_closed(tmp_path, monkeypatch):
    """Review M2: a present-but-unreadable task_spec (Windows share lock /
    ACL PermissionError) takes the SAME fail-closed path as unparseable
    garbage — ValueError out of load_task_spec, so every caller's existing
    WARNING + conservative-HARD handling fires; never a bare PermissionError
    traceback crashing the gate."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _write_task_spec(ws, STATIC_ONLY_SPEC)  # present — only the READ fails
    real_read_text = Path.read_text

    def denied_read_text(self, *args, **kwargs):
        if self.name == "task_spec.yaml":
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied_read_text)
    with pytest.raises(ValueError) as ei:
        tc.load_task_spec(ws)
    assert "unreadable" in str(ei.value), ei.value


def test_load_task_spec_non_utf8_fails_closed(tmp_path, monkeypatch, capsys):
    """B9 (fault-inject bypass round): NON-UTF-8 bytes in task_spec.yaml.

    read_text(encoding="utf-8") raises UnicodeDecodeError, which is neither
    a yaml.YAMLError nor an OSError, so load_task_spec's own except clauses
    never see it — it escapes ONLY because UnicodeDecodeError IS a
    ValueError and every consumer catches `except ValueError`. This test
    pins that type-hierarchy fallback as an explicit contract:
      * load_task_spec raises within the ValueError family (a bare
        UnicodeDecodeError traceback out of a consumer is a defect);
      * the kunglao-init consumer prints its WARNING line and keeps the
        conservative HARD gate (exit 4 on the unreachable VM), with ZERO
        tracebacks on stderr.
    A refactor to a narrower consumer except clause, or to load_task_spec
    raising outside the ValueError family, must fail here."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    (ws / "task_spec.yaml").write_bytes(b"\xff\xfe\x00garbage\x80\x81\x82")
    with pytest.raises(ValueError):
        tc.load_task_spec(ws)
    # consumer path: kunglao-init gate under the same hostile env as the
    # unparseable test — WARNING + conservative HARD, never a crash.
    _hermetic_env(monkeypatch, claude_json=_fake_registry(tmp_path, []))
    mod = _load_init_module()
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root")
    err = capsys.readouterr().err
    assert rc == RC_TOOLCHAIN_REFUSE, \
        f"non-UTF-8 task_spec must not relax the gate: {rc}: {err}"
    assert "kunglao-init: WARNING" in err, err
    assert "conservative HARD" in err, err
    assert "[FAIL] vm_reachable" in err, err
    assert "Traceback" not in err, err


# ---------- check(): static-only downgrades the VM channel to WARN ----------

def test_check_windows_static_only_vm_warn(tmp_path, monkeypatch):
    """static-only task_spec + hostile env (no VM) → vm_reachable WARN
    (tier WARN, basis in detail, no blocking root cause) and the cascaded
    remote_debugger is not a HARD FAIL either."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, claude_json=_fake_registry(tmp_path, []))
    report = tc.check(ws, "windows", task_spec=STATIC_ONLY_SPEC)
    items = _vm_items(report)
    vm = items["vm_reachable"]
    assert vm.status == tc.Status.WARN and vm.tier == tc.Tier.WARN, vm
    assert "not required by task_spec" in vm.detail, vm
    assert vm.root_cause is None, vm
    rd = items["remote_debugger"]
    assert rd.status != tc.Status.FAIL, rd
    assert rd.tier == tc.Tier.WARN, rd
    # W-3 (fault-inject M4): the task_spec basis annotation is pinned on
    # BOTH downgraded items — deleting the remote_debugger copy of "not
    # required by task_spec" must fail here, not only the vm_reachable one.
    assert "not required by task_spec" in rd.detail, rd


def test_check_linux_static_only_vm_warn(tmp_path, monkeypatch):
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, claude_json=_fake_registry(tmp_path, []))
    report = tc.check(ws, "linux", task_spec=STATIC_ONLY_SPEC)
    vm = _vm_items(report)["vm_reachable"]
    assert vm.status == tc.Status.WARN and vm.tier == tc.Tier.WARN, vm
    assert "not required by task_spec" in vm.detail, vm


def test_check_dynamic_re_allowed_keeps_vm_hard(tmp_path, monkeypatch):
    """An explicitly non-static task (dynamic_re=allowed) keeps the VM HARD —
    the field must be answered 'forbidden' to relax, never guessed."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, claude_json=_fake_registry(tmp_path, []))
    report = tc.check(
        ws, "windows", task_spec={"constraints": {"dynamic_re": "allowed"}})
    vm = _vm_items(report)["vm_reachable"]
    assert vm.status == tc.Status.FAIL and vm.tier == tc.Tier.HARD, vm


def test_check_no_task_spec_vm_hard_byte_identical(tmp_path, monkeypatch):
    """Backward compatibility: with NO task_spec input the VM items stay
    byte-identical between the default call and task_spec=None (status/
    tier/root_cause/probe pinned to the #449-era literals; #451 extends
    the FAIL detail with the deterministic discovery footer — seams off in
    _hermetic_env, so the block reads "(none)")."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, claude_json=_fake_registry(tmp_path, []))
    r_default = tc.check(ws, "windows")
    vm = _vm_items(r_default)["vm_reachable"]
    assert vm.status == tc.Status.FAIL and vm.tier == tc.Tier.HARD, vm
    assert vm.detail == ("VM unreachable: KUNGLAO_VM_HOST unset\n"
                         "discovered VMs (vmrun=False, vbox=False):\n"
                         "  (none)"), vm
    assert vm.root_cause == "VM", vm
    assert vm.probe == tc.ProbeTier.LIVENESS, vm
    rd = _vm_items(r_default)["remote_debugger"]
    assert rd.status == tc.Status.FAIL and rd.tier == tc.Tier.HARD, rd
    assert rd.detail == "Remote debugger unreachable (VM not reachable)", rd
    assert rd.root_cause == "VM", rd
    # explicit None == omitted parameter (byte-identical items)
    r_none = tc.check(ws, "windows", task_spec=None)
    assert [(i.name, i.status, i.tier, i.detail, i.root_cause)
            for i in _vm_items(r_none).values()] == \
           [(i.name, i.status, i.tier, i.detail, i.root_cause)
            for i in _vm_items(r_default).values()]


# ---------- CLI consumes the workspace task_spec ----------

def _run_toolchain_cli(ws: Path, extra: list[str],
                       tmp_path: Path) -> subprocess.CompletedProcess:
    empty = tmp_path / "cli-empty-bin"
    empty.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("GHIDRA_HOME", "KUNGLAO_VM_HOST",
                        "KUNGLAO_CLAUDE_JSON", FLAG_NAME)}
    env["PATH"] = str(empty)
    env["KUNGLAO_CLAUDE_JSON"] = str(_fake_registry(tmp_path, []))
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "toolchain.py"), str(ws), *extra],
        capture_output=True, text=True, timeout=120, env=env,
        errors="replace")


def test_cli_consumes_task_spec(tmp_path):
    """toolchain.py <ws> derives its layers from <ws>/task_spec.yaml when
    present (static-only → vm WARN); without the file the VM item FAILs
    HARD exactly as before."""
    ws = _ws_with_sample(tmp_path)
    _write_task_spec(ws, STATIC_ONLY_SPEC)
    r = _run_toolchain_cli(ws, ["--type", "windows", "--json"], tmp_path)
    data = json.loads(r.stdout)
    vm = next(c for c in data["checks"] if c["name"] == "vm_reachable")
    assert vm["status"] == "WARN" and vm["tier"] == "WARN", vm
    assert "not required by task_spec" in vm["detail"], vm

    ws2 = _ws_with_sample(tmp_path / "second")
    r2 = _run_toolchain_cli(ws2, ["--type", "windows", "--json"], tmp_path)
    data2 = json.loads(r2.stdout)
    vm2 = next(c for c in data2["checks"] if c["name"] == "vm_reachable")
    assert vm2["status"] == "FAIL" and vm2["tier"] == "HARD", vm2


def test_cli_unparseable_task_spec_stays_conservative(tmp_path):
    ws = _ws_with_sample(tmp_path)
    (ws / "task_spec.yaml").write_text("{{{ not yaml", encoding="utf-8")
    r = _run_toolchain_cli(ws, ["--type", "windows", "--json"], tmp_path)
    assert "task_spec" in r.stderr and "conservative" in r.stderr.lower(), \
        f"garbage task_spec must warn + stay conservative: {r.stderr}"
    data = json.loads(r.stdout)
    vm = next(c for c in data["checks"] if c["name"] == "vm_reachable")
    assert vm["status"] == "FAIL" and vm["tier"] == "HARD", vm


# ---------- kunglao-init wiring: read task_spec before the gate ----------

def test_init_guidance_line_when_task_spec_absent(tmp_path, monkeypatch,
                                                  capsys):
    """No task_spec → one guidance line on stderr + the conservative default
    path (toolchain.check still called WITHOUT the task_spec kwarg — the
    2-arg call shape old fakes depend on)."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, claude_json=_fake_registry(tmp_path, []))
    mod = _load_init_module()
    calls: list[dict] = []

    def fake_check(ws_arg, project_type=None, **kw):
        calls.append(kw)
        return tc.ToolchainReport(project_type=project_type or "windows",
                                  items=[])

    monkeypatch.setattr(mod.toolchain, "check", fake_check)
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root")
    err = capsys.readouterr().err
    assert rc == 0, f"init failed: {err}"
    assert "task_spec.yaml absent" in err, err
    assert "needs-first" in err, err
    assert calls == [{}], \
        f"no-spec path must call check(ws, type) with no extra kwargs: {calls}"


def test_init_passes_task_spec_to_check_when_present(tmp_path, monkeypatch,
                                                     capsys):
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _write_task_spec(ws, STATIC_ONLY_SPEC)
    _hermetic_env(monkeypatch, claude_json=_fake_registry(tmp_path, []))
    mod = _load_init_module()
    calls: list[dict] = []

    def fake_check(ws_arg, project_type=None, **kw):
        calls.append(kw)
        return tc.ToolchainReport(project_type=project_type or "windows",
                                  items=[])

    monkeypatch.setattr(mod.toolchain, "check", fake_check)
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root")
    err = capsys.readouterr().err
    assert rc == 0, f"init failed: {err}"
    assert "task_spec.yaml absent" not in err, err
    assert calls == [{"task_spec": STATIC_ONLY_SPEC}], calls


def test_init_unparseable_task_spec_stays_hard(tmp_path, monkeypatch, capsys):
    """A present-but-garbage task_spec: WARNING line + conservative HARD —
    init still refuses on the unreachable VM (never relaxes on garbage);
    the CLAUDE.md render fails closed on the same defect later."""
    ws = _ws_with_sample(tmp_path)
    (ws / "task_spec.yaml").write_text("{{{ not yaml", encoding="utf-8")
    _hermetic_env(monkeypatch, claude_json=_fake_registry(tmp_path, []))
    mod = _load_init_module()
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root")
    err = capsys.readouterr().err
    assert rc == RC_TOOLCHAIN_REFUSE, \
        f"garbage task_spec must not relax the gate: {rc}: {err}"
    # W-1 (fault-inject M7): exact WARNING prefix, no loose OR — a gate
    # that never reads task_spec prints no such line and must fail here.
    assert "kunglao-init: WARNING task_spec.yaml unparseable" in err, err
    assert "conservative HARD" in err, err
    assert "task_spec.yaml absent" not in err, err  # distinct scenario
    assert "[FAIL] vm_reachable" in err, err


# ---------- issue evidence 2 fixed as the negative example ----------

def _complete_static_env(tmp_path, monkeypatch) -> Path:
    """An otherwise-COMPLETE windows toolchain with ONLY the VM missing:
    die/floss stubs on PATH (pefile is importable in the project venv),
    ghidra + sequential-thinking + x64dbg registered in the isolated MCP
    registry (decompiler supply via MCP → WARN, mcp items PASS), no
    KUNGLAO_VM_HOST. The VM channel is the sole HARD gap."""
    ws = _ws_with_sample(tmp_path)
    fb = _stub_bin(tmp_path)
    registry = _fake_registry(
        tmp_path, ["ghidra", "sequential-thinking", "x64dbg"])
    _hermetic_env(monkeypatch, fake_bin=fb, claude_json=registry)
    return ws


def test_init_static_only_does_not_refuse_on_vm(tmp_path, monkeypatch):
    """#449 evidence 2 (2026-08-17: task_spec unanswered while the VM chain
    was already up), inverted and fixed: static-only task_spec + complete
    toolchain + NO VM → init does NOT refuse on vm_reachable — it
    initializes (exit 0)."""
    ws = _complete_static_env(tmp_path, monkeypatch)
    _write_task_spec(ws, STATIC_ONLY_SPEC)
    mod = _load_init_module()
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root")
    assert rc == 0, \
        f"static-only task must not HARD-refuse on the VM: {rc}"
    assert (ws / "claim-register.yaml").exists(), \
        "static-only init must scaffold"


def test_init_static_only_control_without_task_spec_refuses(
        tmp_path, monkeypatch, capsys):
    """Control (status-quo anchor): the SAME otherwise-complete environment
    WITHOUT a task_spec still refuses exit 4 with [FAIL] vm_reachable —
    the conservative default; only an explicit static-only task_spec
    relaxes it."""
    ws = _complete_static_env(tmp_path, monkeypatch)
    mod = _load_init_module()
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root")
    err = capsys.readouterr().err
    assert rc == RC_TOOLCHAIN_REFUSE, \
        f"no task_spec must keep the VM refusal: {rc}: {err}"
    assert "[FAIL] vm_reachable" in err, err
    assert not (ws / "claim-register.yaml").exists(), \
        "refused init must not scaffold"


def test_init_assume_yes_reprobe_keeps_task_spec(tmp_path, monkeypatch,
                                                 capsys):
    """Review M1: static-only spec + --assume-yes + an installable HARD
    miss (die). The post-install RE-PROBE must derive its layers from the
    SAME task_spec as the gate — the VM stays WARN and init proceeds
    (exit 0). A spec-blind re-probe would re-harden vm_reachable to HARD,
    vm_reachable has no install plan, and init would refuse exit 4 on a VM
    the task does not need."""
    ws = _ws_with_sample(tmp_path)
    fb = _stub_bin(tmp_path, tools=("floss",))  # die deliberately missing
    registry = _fake_registry(
        tmp_path, ["ghidra", "sequential-thinking", "x64dbg"])
    _hermetic_env(monkeypatch, fake_bin=fb, claude_json=registry)
    _write_task_spec(ws, STATIC_ONLY_SPEC)
    mod = _load_init_module()

    def fake_install(name, plan, assume_yes, ws_arg):
        # a "successful" install: die lands in the stub PATH dir so the
        # re-probe's presence check finds it (mirrors _stub_bin).
        if os.name == "nt":
            (fb / "die.bat").write_text("@echo off\r\n", encoding="utf-8")
        else:
            p = fb / "die"
            p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            p.chmod(0o755)
        return (0, "install OK", "")

    monkeypatch.setattr(mod.toolchain_install, "_run_install_plan",
                        fake_install)
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root", assume_yes=True)
    captured = capsys.readouterr()
    log = captured.out + captured.err
    assert "re-probing toolchain" in log, \
        f"the ask-then-install path must run (install + re-probe): {log}"
    assert rc == 0, \
        f"re-probe must keep the static-only VM downgrade (no re-hardening," \
        f" no exit-4 refusal): rc={rc}: {log}"
    assert (ws / "claim-register.yaml").exists(), \
        "assume-yes static-only path must scaffold after a PASS re-probe"


# ---------- SKILL.md Flow: task-spec intake is step 0 ----------

def test_skill_flow_task_spec_intake_is_step_0():
    """Flow reorder: Task-spec intake (needs-first) is Flow step 0, target
    alignment follows at 1, scaffold drops to 2 — text and numbering
    consistent."""
    text = SKILL_INIT.read_text(encoding="utf-8")
    m0 = re.search(r"^0\. \*\*Task-spec intake", text, re.M)
    m1 = re.search(r"^1\. \*\*Target alignment", text, re.M)
    m2 = re.search(r"^2\. \*\*Scaffold", text, re.M)
    assert m0, "Flow step 0 must be Task-spec intake (needs-first)"
    assert m1, "Flow step 1 must be Target alignment"
    assert m2, "Flow step 2 must be Scaffold (demoted from 1)"
    assert m0.start() < m1.start() < m2.start()
    assert not re.search(r"^1\. \*\*Scaffold", text, re.M), \
        "old scaffold-first numbering must be gone"
    assert not re.search(r"^5\. \*\*Task-spec intake", text, re.M), \
        "task-spec intake must not remain at step 5"


def test_skill_flow_step0_names_the_requirements():
    text = SKILL_INIT.read_text(encoding="utf-8")
    m0 = re.search(r"^0\. \*\*Task-spec intake.*?(?=^1\. )", text,
                   re.M | re.S)
    assert m0, "Flow step 0 block not found"
    block = re.sub(r"\s+", " ", m0.group(0))  # unwrap markdown line breaks
    for field in ("primary questions", "scope", "constraints", "depth",
                  "success_criteria"):
        assert field in block, f"step 0 must confirm {field}: {block}"
    assert "env = f(task_spec)" in block or "f(task_spec)" in block, block


def test_skill_frontmatter_names_needs_first_intake():
    """Review L2: the SKILL frontmatter description carries the same
    needs-first contract as Flow step 0 — the command router matches on
    the frontmatter before any body text is read, so the intake-first
    keywords must live in the delimited block itself."""
    text = SKILL_INIT.read_text(encoding="utf-8")
    parts = text.split("---")
    assert len(parts) >= 3, "frontmatter block (--- delimited) missing"
    fm = parts[1]  # first delimited block, before the body
    assert "needs-first" in fm, fm
    assert "task_spec.yaml" in fm, fm
    assert re.search(r"\bFIRST\b", fm), \
        f"frontmatter must say task_spec is intaken FIRST: {fm}"


def test_init_worker_agent_collects_task_requirements():
    """agents/kunglao-init-worker.md references the needs-first intake
    order (task requirements before environment decisions)."""
    text = AGENT_INIT_WORKER.read_text(encoding="utf-8")
    assert "task_spec" in text and "needs-first" in text, \
        "init-worker must carry the #449 needs-first intake step"
