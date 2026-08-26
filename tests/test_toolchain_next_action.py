# -*- coding: utf-8 -*-
"""Tests for issue #451 task ① — every toolchain FAIL carries a
machine-parseable next-action.

Contract (openspec/changes/issue-451-init-negotiation design.md D1/D2):
  * CheckResult gains item-level `fix` (dynamic, overrides the FIXES static
    text) and `next_action` (NextAction(action, command, options)).
  * Human output: after the `fix:` line, key-value lines
    `action: <verb>` / `command: <cmd>` / `option N: <opt>` extractable by
    anchored regex (never confused with detail prose).
  * JSON output: each check gains `next_action` (object on FAIL, null else).
  * The verb set is closed (NEXT_ACTION_VERBS); every FIXES-keyed FAIL name
    derives a non-None next_action (mcp:* derived from the manifest register
    command; root_cause VM falls back to vm-enumerate).
  * vm_reachable FAIL embeds a read-only discovered-VM inventory and derives
    the action from the candidate count (enumerate/start/reip); init never
    auto-selects among candidates (the OPERATOR picks).
  * kunglao-init's refusal block carries the same structured lines.

TDD RED phase: written BEFORE the implementation (NextAction /
CheckResult.fix / inventory do not exist yet).
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen in name blocks direct import)."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_next_action_under_test", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ACTION_LINE_RE = re.compile(r"^\s*action: ([a-z-]+)\s*$", re.MULTILINE)
_COMMAND_LINE_RE = re.compile(r"^\s*command: (.+?)\s*$", re.MULTILINE)
_OPTION_LINE_RE = re.compile(r"^\s*option (\d+): (.+?)\s*$", re.MULTILINE)


def _ws_with_sample(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    return ws


def _hermetic_env(monkeypatch, tmp_path: Path) -> Path:
    """Hostile toolchain env + isolated MCP registry + VM discovery OFF
    (deterministic inventory: no vmrun, no VBoxManage)."""
    import toolchain as tc
    monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(_fake_registry(tmp_path, [])))
    monkeypatch.setenv(FLAG_NAME, "0")
    monkeypatch.setattr(tc, "_vmrun_exe", lambda: None)
    monkeypatch.setattr(tc, "_vbox_exe", lambda: None)
    return tmp_path / "profile-root"


def _fake_registry(tmp_path: Path, servers: list[str]) -> Path:
    p = tmp_path / "fake-claude.json"
    p.write_text(json.dumps({"mcpServers": {n: {} for n in servers}}),
                 encoding="utf-8")
    return p


# ---------- D1: data model + dual-surface parsing ----------

def test_next_action_dataclass_shape():
    """NextAction(action, command, options) exists and is frozen."""
    import toolchain as tc
    na = tc.NextAction(action="vm-enumerate", command="vmrun list",
                       options=("work_env", "win10"))
    assert na.action == "vm-enumerate"
    assert na.command == "vmrun list"
    assert tuple(na.options) == ("work_env", "win10")
    with pytest.raises(Exception):
        na.action = "install"  # frozen — immutable dataclass


def test_fail_human_output_carries_parseable_action_lines():
    """format_human: a FAIL item with a dynamic next_action renders
    machine-extractable `action:` / `command:` / `option N:` lines."""
    import toolchain as tc
    report = tc.ToolchainReport(project_type="windows", items=[
        tc.CheckResult(
            name="vm_reachable", status=tc.Status.FAIL, tier=tc.Tier.HARD,
            detail="VM unreachable: KUNGLAO_VM_HOST unset",
            root_cause="VM",
            next_action=tc.NextAction("vm-enumerate", "vmrun list",
                                      ("work_env", "Windows 10 x64"))),
    ])
    text = tc.format_human(report)
    assert _ACTION_LINE_RE.findall(text) == ["vm-enumerate"], text
    assert "vmrun list" in _COMMAND_LINE_RE.findall(text), text
    opts = _OPTION_LINE_RE.findall(text)
    assert opts == [("1", "work_env"), ("2", "Windows 10 x64")], text


def test_pass_items_have_no_next_action_noise():
    """PASS items carry no next_action (same noise discipline as fix)."""
    import toolchain as tc
    report = tc.ToolchainReport(project_type="windows", items=[
        tc.CheckResult(name="docker", status=tc.Status.PASS,
                       tier=tc.Tier.WARN, detail="ok"),
    ])
    data = json.loads(tc.format_json(report))
    assert data["checks"][0]["next_action"] is None
    assert "action:" not in tc.format_human(report)


def test_json_output_carries_next_action_object():
    """--json: FAIL check carries next_action {action, command, options};
    the dynamic item-level fix overrides the FIXES static text."""
    import toolchain as tc
    report = tc.ToolchainReport(project_type="windows", items=[
        tc.CheckResult(
            name="vm_reachable", status=tc.Status.FAIL, tier=tc.Tier.HARD,
            detail="VM unreachable: KUNGLAO_VM_HOST unset", root_cause="VM",
            fix="multiple VM candidates listed above - the OPERATOR picks",
            next_action=tc.NextAction("vm-enumerate", "vmrun list",
                                      ("work_env",))),
    ])
    data = json.loads(tc.format_json(report))
    vm = data["checks"][0]
    assert vm["fix"] == "multiple VM candidates listed above - the OPERATOR picks"
    assert vm["next_action"] == {"action": "vm-enumerate",
                                 "command": "vmrun list",
                                 "options": ["work_env"]}


def test_checkresult_fix_field_overrides_static_fixes_text():
    """item.fix (dynamic) wins over FIXES[name] in both surfaces."""
    import toolchain as tc
    fix_text = "use the bundled die at tools/die"
    item = tc.CheckResult(name="die", status=tc.Status.FAIL,
                          tier=tc.Tier.HARD, detail="die not found in PATH",
                          fix=fix_text)
    report = tc.ToolchainReport(project_type="windows", items=[item])
    assert fix_text in tc.format_human(report)
    assert json.loads(tc.format_json(report))["checks"][0]["fix"] == fix_text


def test_next_action_verbs_form_closed_set():
    """NEXT_ACTION_VERBS is the closed verb vocabulary; every static table
    entry uses a verb from it (no free-text actions)."""
    import toolchain as tc
    verbs = tc.NEXT_ACTION_VERBS
    for verb in ("install", "set-env", "register-mcp", "vm-enumerate",
                 "vm-start", "vm-reip", "human-configure", "human-deploy"):
        assert verb in verbs, f"verb {verb!r} missing from NEXT_ACTION_VERBS"
    for name, na in tc._STATIC_NEXT_ACTIONS.items():
        assert na.action in verbs, f"{name}: verb {na.action!r} not in set"


def test_every_fixes_fail_name_derives_next_action():
    """Coverage: a FAIL item named by ANY FIXES key (incl. mcp:* derived
    entries) must derive a non-None next_action — 'every FAIL carries a
    parseable next-action' is mechanical, not aspirational."""
    import toolchain as tc
    for name in tc.FIXES:
        item = tc.CheckResult(name=name, status=tc.Status.FAIL,
                              tier=tc.Tier.HARD, detail="x",
                              root_cause="VM" if name in
                              ("vm_reachable", "remote_debugger") else None)
        na = tc.next_action_for(item)
        assert na is not None, f"FAIL {name!r} has no next_action"
        assert na.action in tc.NEXT_ACTION_VERBS


# ---------- #451 review L-1: fail-closed verb + FAIL-face coverage ----------

def test_next_action_constructor_rejects_out_of_vocab_verb():
    """Fail-closed: the constructor validates action against the closed
    NEXT_ACTION_VERBS vocabulary — a stray verb raises ValueError instead
    of silently rendering an unparseable `action:` line downstream."""
    import toolchain as tc
    with pytest.raises(ValueError, match="NEXT_ACTION_VERBS"):
        tc.NextAction("reinstall", "pip install x")  # not a verb
    with pytest.raises(ValueError, match="NEXT_ACTION_VERBS"):
        tc.NextAction("")  # empty is not a verb
    for verb in tc.NEXT_ACTION_VERBS:  # every closed-set verb constructs
        assert tc.NextAction(verb).action == verb


# Declared WARN-only checks — never FAIL-able, so no next_action is
# required of them. REVIEWED, not derived: a NEW check name that is
# neither in FIXES nor declared here fails the FAIL-face test below
# (a silent guidance gap is exactly what L-1 closes).
_WARN_ONLY_CHECK_NAMES = frozenset({
    "docker", "gdbserver", "ebpf", "ebpf_android", "unidbg",
    # #728 web (labs): docker channel presence — WARN by contract (labs
    # never FAIL-HARD; toolchain.py _check_web emits PASS/WARN only)
    "channel:docker",
})


def test_every_fail_face_name_derives_next_action():
    """L-1: the closed-set coverage domain is the FAIL FACE, not the FIXES
    keys — every check name toolchain.py can construct (source-scanned
    CheckResult literals) plus the mcp:<name> manifest surface (via
    FIXES). A future FAIL-able check without guidance fails HERE, not
    silently in production."""
    import inspect
    import toolchain as tc
    scanned = set(re.findall(
        r'CheckResult\(\s*name=["\']([A-Za-z0-9_:-]+)["\']',
        inspect.getsource(tc)))
    # scan-rot tripwire: the core FAIL-able names must still be found
    assert {"vm_reachable", "remote_debugger", "decompiler"} <= scanned
    # every scanned name outside FIXES must be a DECLARED WARN-only check
    assert scanned - set(tc.FIXES) <= _WARN_ONLY_CHECK_NAMES, (
        f"check names outside FIXES: {sorted(scanned - set(tc.FIXES))} — "
        f"give them a FIXES/next_action entry or declare them WARN-only")
    fail_face = (scanned | set(tc.FIXES)) - _WARN_ONLY_CHECK_NAMES
    for name in sorted(fail_face):
        item = tc.CheckResult(name=name, status=tc.Status.FAIL,
                              tier=tc.Tier.HARD, detail="x",
                              root_cause="VM" if name in
                              ("vm_reachable", "remote_debugger") else None)
        na = tc.next_action_for(item)
        assert na is not None, f"FAIL {name!r} carries no next_action"
        assert na.action in tc.NEXT_ACTION_VERBS, name


# ---------- D2: VM inventory enumeration ----------

def _vm_entry(name: str, vmx: str, running: bool, snaps: list[str] | None = None):
    import toolchain as tc
    return tc.VMInventoryEntry(name=name, vmx=vmx, running=running,
                               snapshots=list(snaps or []))


def test_vm_multi_candidate_enumerate_never_auto_selects(
        tmp_path, monkeypatch):
    """THE #451 case: multiple discovered VMs -> vm-enumerate with both
    names as options; the fix names the OPERATOR as the picker (init never
    auto-selects); the detail lists candidates numbered."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, tmp_path)
    entries = [
        _vm_entry("work_env", str(tmp_path / "vms" / "work_env.vmx"), False,
                  ["base", "idalib-mcp-ready-20260630"]),
        _vm_entry("Windows 10 x64", str(tmp_path / "vms" / "win10.vmx"),
                  False, ["hr-6.0"]),
    ]
    monkeypatch.setattr(tc, "_vm_inventory", lambda: (entries, True, False))
    report = tc.check(ws, "windows")
    vm = next(i for i in report.items if i.name == "vm_reachable")
    assert vm.status == tc.Status.FAIL and vm.tier == tc.Tier.HARD
    # numbered inventory in the detail (issue real-output format)
    assert "discovered VMs (vmrun=True, vbox=False):" in vm.detail
    assert "1. work_env [off] snapshots: 2 (latest: idalib-mcp-ready-20260630)" \
        in vm.detail
    assert "2. Windows 10 x64 [off] snapshots: 1 (latest: hr-6.0)" in vm.detail
    # dynamic next_action: enumerate + the command that enumerates + options
    na = tc.next_action_for(vm)
    assert na is not None and na.action == "vm-enumerate", vm
    assert na.command == "vmrun list"
    assert tuple(na.options) == ("work_env", "Windows 10 x64")
    # the operator picks — never an auto-selection
    assert vm.fix and "OPERATOR" in vm.fix and "never auto-select" in vm.fix
    # human surface stays machine-parseable end-to-end
    text = tc.format_human(report)
    assert _ACTION_LINE_RE.findall(text), text
    assert "vmrun list" in _COMMAND_LINE_RE.findall(text)
    assert ("1", "work_env") in _OPTION_LINE_RE.findall(text)


def test_vm_single_off_candidate_starts(tmp_path, monkeypatch):
    """Single off candidate -> vm-start naming the exact vmrun start command."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, tmp_path)
    vmx = str(tmp_path / "vms" / "work_env.vmx")
    entries = [_vm_entry("work_env", vmx, False)]
    monkeypatch.setattr(tc, "_vm_inventory", lambda: (entries, True, False))
    report = tc.check(ws, "windows")
    vm = next(i for i in report.items if i.name == "vm_reachable")
    na = tc.next_action_for(vm)
    assert na.action == "vm-start", vm
    assert 'vmrun -T ws start' in (na.command or "")
    assert vmx in (na.command or "")


def test_vm_running_candidate_reip(tmp_path, monkeypatch):
    """A running VM (host unset) or a set-but-dead host -> vm-reip: resolve
    the live IP (vmrun getGuestIPAddress), never a cached lease."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, tmp_path)
    vmx = str(tmp_path / "vms" / "work_env.vmx")
    entries = [_vm_entry("work_env", vmx, True)]
    monkeypatch.setattr(tc, "_vm_inventory", lambda: (entries, True, False))
    report = tc.check(ws, "windows")
    vm = next(i for i in report.items if i.name == "vm_reachable")
    na = tc.next_action_for(vm)
    assert na.action == "vm-reip", vm
    assert "getGuestIPAddress" in (na.command or "")

    # host SET but ports closed (DHCP lease drifted) -> still vm-reip on the
    # RUNNING candidate, with the lease-change note in the detail
    monkeypatch.setenv("KUNGLAO_VM_HOST", "192.168.1.128")
    monkeypatch.setattr(tc, "_tcp_connect",
                        lambda host, port, timeout=2: (False, f"{port}: down"))
    report2 = tc.check(ws, "windows")
    vm2 = next(i for i in report2.items if i.name == "vm_reachable")
    assert vm2.status == tc.Status.FAIL
    na2 = tc.next_action_for(vm2)
    assert na2.action == "vm-reip", vm2
    assert "lease" in vm2.detail.lower(), vm2.detail


def test_vm_no_candidates_action_is_enumerate(tmp_path, monkeypatch):
    """No VM discovered -> still vm-enumerate (register/boot one); the
    detail honestly says none were found."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, tmp_path)
    monkeypatch.setattr(tc, "_vm_inventory", lambda: ([], False, False))
    report = tc.check(ws, "windows")
    vm = next(i for i in report.items if i.name == "vm_reachable")
    assert vm.status == tc.Status.FAIL
    assert "discovered VMs (vmrun=False, vbox=False):" in vm.detail
    assert "(none)" in vm.detail
    na = tc.next_action_for(vm)
    assert na is not None and na.action == "vm-enumerate"
    assert na.command is None  # no enumerator on this host — honest, not fake


def test_remote_debugger_cascade_shares_vm_next_action(tmp_path, monkeypatch):
    """The remote_debugger cascade FAIL reuses the VM's next_action — its
    root cause is the VM channel (fix the root cause first)."""
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, tmp_path)
    vmx = str(tmp_path / "vms" / "work_env.vmx")
    entries = [_vm_entry("work_env", vmx, False)]
    monkeypatch.setattr(tc, "_vm_inventory", lambda: (entries, True, False))
    report = tc.check(ws, "windows")
    vm = next(i for i in report.items if i.name == "vm_reachable")
    rd = next(i for i in report.items if i.name == "remote_debugger")
    assert rd.status == tc.Status.FAIL and rd.root_cause == "VM"
    assert tc.next_action_for(rd) is not None
    assert tc.next_action_for(rd).action == tc.next_action_for(vm).action


def test_static_only_warn_vm_keeps_plain_detail(tmp_path, monkeypatch):
    """#449 lock: static-only task_spec keeps the WARN downgrade surface
    WITHOUT the inventory block (the VM is not required — no discovery run)."""
    import yaml
    import toolchain as tc
    ws = _ws_with_sample(tmp_path)
    _hermetic_env(monkeypatch, tmp_path)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"constraints": {"dynamic_re": "forbidden"}}),
        encoding="utf-8")
    vmx = str(tmp_path / "vms" / "work_env.vmx")
    entries = [_vm_entry("work_env", vmx, False)]
    monkeypatch.setattr(tc, "_vm_inventory", lambda: (entries, True, False))
    report = tc.check(ws, "windows", task_spec={"constraints":
                                                {"dynamic_re": "forbidden"}})
    vm = next(i for i in report.items if i.name == "vm_reachable")
    assert vm.status == tc.Status.WARN and vm.tier == tc.Tier.WARN
    assert "discovered VMs" not in vm.detail
    assert "not required by task_spec" in vm.detail


# ---------- refusal surface carries the structured lines ----------

def test_refuse_output_carries_next_action_lines(tmp_path, monkeypatch, capsys):
    """kunglao-init's exit-4 refusal prints the structured action/command/
    option lines for each FAIL item (the negotiation-consumable channel)."""
    import toolchain as tc
    mod = _load_init_module()
    ws = _ws_with_sample(tmp_path)
    monkeypatch.setenv(FLAG_NAME, "0")
    report = tc.ToolchainReport(project_type="windows", items=[
        tc.CheckResult(
            name="vm_reachable", status=tc.Status.FAIL, tier=tc.Tier.HARD,
            detail="VM unreachable: KUNGLAO_VM_HOST unset", root_cause="VM",
            fix="multiple candidates - the OPERATOR picks",
            next_action=tc.NextAction("vm-enumerate", "vmrun list",
                                      ("work_env", "win10"))),
    ])
    rc = mod.refuse_toolchain(ws, report)
    captured = capsys.readouterr()
    assert rc == mod.RC_TOOLCHAIN_REFUSE
    err = captured.err
    assert _ACTION_LINE_RE.findall(err) == ["vm-enumerate"], err
    assert "vmrun list" in _COMMAND_LINE_RE.findall(err), err
    assert ("1", "work_env") in _OPTION_LINE_RE.findall(err), err
