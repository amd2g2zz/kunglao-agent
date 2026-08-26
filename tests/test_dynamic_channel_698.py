# -*- coding: utf-8 -*-
"""tests/test_dynamic_channel_698.py — five-channel dynamic control plane.

Issue #698, arbitration v6 (final): KUNGLAO_CHANNEL = vmr(default) | ssh |
docker | adb | local. The channel exists to give the agent an EXECUTION
CONTROL PLANE for dynamic debugging; static-only tasks skip all probes
(WARN contract); dynamic + local is a HARD policy reject; ssh/docker/adb
probe at capability level with tri-state failure details; vmr is
byte-identical to the pre-#698 probe.

All remote interactions are mocked — this suite never opens sockets or
spawns real ssh/docker/adb.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import toolchain as tc  # noqa: E402
import mcp_probe as mp  # noqa: E402


# ---------------------------------------------------------------- helpers

def _channel_env(monkeypatch, **kv):
    """Hermetic-ish channel env: clear all channel vars, then set given."""
    for var in ("KUNGLAO_CHANNEL", "KUNGLAO_VM_HOST", "KUNGLAO_DOCKER_CONTAINER"):
        monkeypatch.delenv(var, raising=False)
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


STATIC_ONLY_SPEC = {"constraints": {"dynamic_re": "forbidden"}}
DYNAMIC_SPEC = {"constraints": {"dynamic_re": "allowed"}}


class _Recorder:
    """Tracks every _run_cmd/_tcp_connect call; stubs their results."""

    def __init__(self, monkeypatch, cmd_results=None, tcp_results=None):
        self.cmd_calls: list[list[str]] = []
        self.tcp_calls: list[tuple[str, int]] = []
        # cmd_results: list of (rc, out, err) popped in order; default (0,"","")
        self._cmd_results = list(cmd_results or [])
        # tcp_results: dict port->(ok, err) or list of (ok, err) popped
        self._tcp_results = tcp_results or {}

    def cmd(self, args, timeout=10):
        self.cmd_calls.append(list(args))
        if self._cmd_results:
            return self._cmd_results.pop(0)
        return 0, "", ""

    def tcp(self, host, port, timeout=2):
        self.tcp_calls.append((host, port))
        if isinstance(self._tcp_results, dict):
            return self._tcp_results.get(port, (True, ""))
        if self._tcp_results:
            return self._tcp_results.pop(0)
        return True, ""


def _wire(monkeypatch, **recorder_kwargs) -> _Recorder:
    rec = _Recorder(monkeypatch, **recorder_kwargs)
    monkeypatch.setattr(tc, "_run_cmd", rec.cmd)
    monkeypatch.setattr(tc, "_tcp_connect", rec.tcp)
    return rec


def _vm_item(report):
    items = {i.name: i for i in report.items}
    return items["vm_reachable"], items.get("remote_debugger")


# ------------------------------------------------- 1. enum parsing

def test_channel_enum_unset_defaults_vmr(monkeypatch):
    _channel_env(monkeypatch)
    backend, note = tc._channel_backend()
    assert backend == "vmr" and note is None


@pytest.mark.parametrize("raw,expected", [
    ("vmr", "vmr"), ("ssh", "ssh"), ("docker", "docker"),
    ("adb", "adb"), ("local", "local"),
    ("  SSH ", "ssh"), ("Docker", "docker"),
])
def test_channel_enum_known_values(monkeypatch, raw, expected):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL=raw)
    backend, note = tc._channel_backend()
    assert backend == expected and note is None


def test_channel_enum_unknown_falls_back_vmr_with_note(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="carrier-pigeon")
    backend, note = tc._channel_backend()
    assert backend == "vmr"
    assert note is not None and "carrier-pigeon" in note


# ------------------------------------------------- 2. ssh backend

def test_ssh_probe_port_unreachable(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="10.0.0.9")
    rec = _wire(monkeypatch, tcp_results={tc.VM_SHELL_PORT: (False, "9876: timeout")})
    ok, _detail, err, tier = tc._vm_probe_ssh("10.0.0.9")
    assert not ok
    assert err.startswith("port unreachable")
    assert tier == tc.ProbeTier.CAPABILITY
    # TCP pre-check only — no ssh spawned on a dead port
    assert rec.cmd_calls == []


def test_ssh_probe_auth_failed(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="10.0.0.9")
    rec = _wire(monkeypatch, cmd_results=[(255, "", "user@10.0.0.9: Permission denied (publickey).")])
    ok, _detail, err, _tier = tc._vm_probe_ssh("10.0.0.9")
    assert not ok and "auth failed" in err
    cmd = rec.cmd_calls[0]
    assert cmd[0] == "ssh" and "10.0.0.9" in cmd and "true" in cmd
    assert "-o" in cmd and "BatchMode=yes" in cmd
    assert f"-p" in cmd and str(tc.VM_SHELL_PORT) in cmd


def test_ssh_probe_dialect_mismatch(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="10.0.0.9")
    _wire(monkeypatch, cmd_results=[(1, "HTTP/1.1 400 Bad Request", "")])
    ok, _detail, err, _tier = tc._vm_probe_ssh("10.0.0.9")
    assert not ok and "channel dialect mismatch" in err


def test_ssh_probe_pass_and_frida_liveness(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="10.0.0.9")
    _wire(monkeypatch, cmd_results=[(0, "", "")])
    ok, detail, err, tier = tc._vm_probe_ssh("10.0.0.9")
    assert ok and err == ""
    assert "via ssh backend" in detail
    assert tier == tc.ProbeTier.CAPABILITY


def test_ssh_probe_frida_port_closed(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="10.0.0.9")
    _wire(monkeypatch,
          tcp_results={tc.VM_SHELL_PORT: (True, ""), tc.FRIDA_PORT: (False, "1337: refused")},
          cmd_results=[(0, "", "")])
    ok, _detail, err, _tier = tc._vm_probe_ssh("10.0.0.9")
    assert not ok and "frida port closed" in err


# --------------------------------------- 3. docker-over-ssh (optional)

def test_ssh_docker_daemon_unreachable(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="h",
                 KUNGLAO_DOCKER_CONTAINER="box")
    _wire(monkeypatch, cmd_results=[(0, "", ""), (1, "", "Cannot connect to the Docker daemon")])
    ok, _detail, err, _tier = tc._vm_probe_ssh("h")
    assert not ok and "docker daemon unreachable" in err


def test_ssh_docker_container_missing(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="h",
                 KUNGLAO_DOCKER_CONTAINER="box")
    _wire(monkeypatch, cmd_results=[(0, "", ""), (0, "", ""),
                                    (1, "", "Error: No such container: box")])
    ok, _detail, err, _tier = tc._vm_probe_ssh("h")
    assert not ok and "container missing" in err


def test_ssh_docker_exec_rejected(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="h",
                 KUNGLAO_DOCKER_CONTAINER="box")
    _wire(monkeypatch, cmd_results=[(0, "", ""), (0, "", ""),
                                    (126, "", "operation not permitted")])
    ok, _detail, err, _tier = tc._vm_probe_ssh("h")
    assert not ok and "docker exec rejected" in err


def test_ssh_docker_ok_detail_mentions_container(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="h",
                 KUNGLAO_DOCKER_CONTAINER="box")
    _wire(monkeypatch, cmd_results=[(0, "", ""), (0, "", ""), (0, "", "")])
    ok, detail, err, _tier = tc._vm_probe_ssh("h")
    assert ok and "box" in detail and "docker" in detail


# --------------------------------------------- 4. docker direct channel

def test_docker_probe_daemon_unreachable(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="docker")
    rec = _wire(monkeypatch, cmd_results=[(1, "", "Cannot connect to the Docker daemon")])
    ok, _detail, err, tier = tc._vm_probe_docker()
    assert not ok and "docker daemon unreachable" in err
    assert tier == tc.ProbeTier.CAPABILITY
    assert rec.cmd_calls[0][:2] == ["docker", "version"]


def test_docker_probe_container_missing_and_ok(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="docker", KUNGLAO_DOCKER_CONTAINER="box")
    rec = _wire(monkeypatch, cmd_results=[(0, "", ""),
                                          (1, "", "Error response from daemon: No such object: box")])
    ok, _detail, err, _t = tc._vm_probe_docker()
    assert not ok and "container missing" in err
    assert rec.cmd_calls[1][:3] == ["docker", "exec", "box"]
    # reset for pass path
    rec2 = _wire(monkeypatch, cmd_results=[(0, "", ""), (0, "", "")])
    ok2, detail2, err2, _t = tc._vm_probe_docker()
    assert ok2 and err2 == "" and "via docker backend" in detail2


def test_docker_probe_exec_rejected(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="docker", KUNGLAO_DOCKER_CONTAINER="box")
    _wire(monkeypatch, cmd_results=[(0, "", ""), (126, "", "operation not permitted")])
    ok, _detail, err, _t = tc._vm_probe_docker()
    assert not ok and "docker exec rejected" in err


def test_docker_probe_needs_no_vm_host(monkeypatch):
    """docker direct: KUNGLAO_VM_HOST unset is fine (local/DOCKER_HOST daemon)."""
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="docker")
    _wire(monkeypatch, cmd_results=[(0, "", "")])
    ok, _detail, err, _t = tc._vm_probe_docker()
    assert ok and err == ""


# ------------------------------------------------- 5. adb backend

def test_adb_probe_no_device(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="adb")
    _wire(monkeypatch, cmd_results=[(0, "List of devices attached\n\n", "")])
    ok, _detail, err, tier = tc._vm_probe_adb()
    assert not ok and "no device" in err
    assert tier == tc.ProbeTier.CAPABILITY


def test_adb_probe_unauthorized(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="adb")
    _wire(monkeypatch, cmd_results=[(0, "List of devices attached\nZX1 abc\tunauthorized\n", "")])
    ok, _detail, err, _t = tc._vm_probe_adb()
    assert not ok and "unauthorized" in err


def test_adb_probe_pass_with_frida(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="adb", KUNGLAO_VM_HOST="127.0.0.1")
    _wire(monkeypatch, cmd_results=[(0, "List of devices attached\nemulator-5554\tdevice\n", "")])
    ok, detail, err, _t = tc._vm_probe_adb()
    assert ok and err == "" and "via adb backend" in detail and "emulator-5554" in detail


def test_adb_probe_frida_closed(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="adb", KUNGLAO_VM_HOST="127.0.0.1")
    _wire(monkeypatch,
          tcp_results={tc.FRIDA_PORT: (False, "1337: refused")},
          cmd_results=[(0, "List of devices attached\nemulator-5554\tdevice\n", "")])
    ok, _detail, err, _t = tc._vm_probe_adb()
    assert not ok and "frida port closed" in err


# -------------------------------------------- 6. vmr byte-identical

def test_vmr_probe_pass_byte_identical(monkeypatch):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="vmr", KUNGLAO_VM_HOST="192.168.1.50")
    _wire(monkeypatch)
    ok, detail, err, tier = tc._vm_probe_vmr("192.168.1.50")
    assert ok and err == ""
    assert detail == (f"VM 192.168.1.50 reachable on "
                      f"{tc.VM_SHELL_PORT}+{tc.FRIDA_PORT}")
    assert tier == tc.ProbeTier.LIVENESS


# ------------------------------ 7. static-only: zero probes, WARN contract

def test_static_only_skips_all_probes_any_channel(monkeypatch, tmp_path):
    """static-only task + ssh backend: NO ssh/tcp probe may run (mocks raise
    if touched); both items WARN with the pinned basis substring."""
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="10.0.0.9")
    rec = _wire(monkeypatch)
    reqs = tc.requirements_from_task_spec(STATIC_ONLY_SPEC)
    rep = tc.ToolchainReport(project_type="windows")
    tc._check_dynamic_channel(rep, reqs)
    vm, rd = _vm_item(rep)
    assert vm.status == tc.Status.WARN and vm.tier == tc.Tier.WARN
    assert "dynamic channel unchecked (static-only task)" in vm.detail
    assert "not required by task_spec" in vm.detail
    assert rd is not None and rd.tier == tc.Tier.WARN
    assert "not required by task_spec" in rd.detail
    assert rec.cmd_calls == [] and rec.tcp_calls == []


def test_static_only_local_channel_warns_static_only(monkeypatch, tmp_path):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="local")
    rec = _wire(monkeypatch)
    reqs = tc.requirements_from_task_spec(STATIC_ONLY_SPEC)
    rep = tc.ToolchainReport(project_type="windows")
    tc._check_dynamic_channel(rep, reqs)
    vm, rd = _vm_item(rep)
    assert vm.status == tc.Status.WARN and vm.tier == tc.Tier.WARN
    assert "local static-only channel" in vm.detail
    assert "not required by task_spec" in vm.detail
    assert rec.cmd_calls == [] and rec.tcp_calls == []


# ------------------------------ 8. dynamic + local: HARD policy reject

def test_dynamic_local_hard_reject_exact_detail(monkeypatch, tmp_path):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="local")
    rec = _wire(monkeypatch)
    reqs = tc.requirements_from_task_spec(DYNAMIC_SPEC)
    rep = tc.ToolchainReport(project_type="windows")
    tc._check_dynamic_channel(rep, reqs)
    vm, rd = _vm_item(rep)
    assert vm.status == tc.Status.FAIL and vm.tier == tc.Tier.HARD
    assert vm.detail == ("local channel forbids dynamic analysis — switch "
                         "KUNGLAO_CHANNEL to vmr/ssh/docker/adb")
    assert rd is not None and rd.status == tc.Status.FAIL
    assert rec.cmd_calls == [] and rec.tcp_calls == []


# ------------------------------ 9. dynamic + remote backend dispatch

def test_dynamic_ssh_unreachable_hard_fail(monkeypatch, tmp_path):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh", KUNGLAO_VM_HOST="10.0.0.9")
    _wire(monkeypatch, tcp_results={tc.VM_SHELL_PORT: (False, "9876: timeout")})
    reqs = tc.requirements_from_task_spec(DYNAMIC_SPEC)
    rep = tc.ToolchainReport(project_type="windows")
    tc._check_dynamic_channel(rep, reqs)
    vm, _rd = _vm_item(rep)
    assert vm.status == tc.Status.FAIL and vm.tier == tc.Tier.HARD
    assert "port unreachable" in vm.detail and "ssh" in vm.detail
    assert vm.probe == tc.ProbeTier.CAPABILITY


def test_dynamic_ssh_without_host_fails_with_named_env(monkeypatch, tmp_path):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="ssh")
    rec = _wire(monkeypatch)
    reqs = tc.requirements_from_task_spec(DYNAMIC_SPEC)
    rep = tc.ToolchainReport(project_type="windows")
    tc._check_dynamic_channel(rep, reqs)
    vm, _rd = _vm_item(rep)
    assert vm.status == tc.Status.FAIL and vm.tier == tc.Tier.HARD
    assert "KUNGLAO_VM_HOST" in vm.detail
    assert rec.cmd_calls == [] and rec.tcp_calls == []


def test_dynamic_unknown_channel_falls_back_vmr_behavior(monkeypatch, tmp_path):
    _channel_env(monkeypatch, KUNGLAO_CHANNEL="banana", KUNGLAO_VM_HOST="h")
    rec = _wire(monkeypatch)  # vmr path: two TCP liveness calls
    reqs = tc.requirements_from_task_spec(DYNAMIC_SPEC)
    rep = tc.ToolchainReport(project_type="windows")
    tc._check_dynamic_channel(rep, reqs)
    vm, _rd = _vm_item(rep)
    assert vm.status == tc.Status.PASS and vm.tier == tc.Tier.HARD
    assert "banana" in vm.detail  # fallback named in detail
    assert [p for _h, p in rec.tcp_calls] == [tc.VM_SHELL_PORT, tc.FRIDA_PORT]


# --------------------------------------------- 10. mcp manifest entry

def test_mcp_manifest_declares_ssh_mcp():
    entry = mp._BY_NAME.get("ssh-mcp")
    assert entry is not None, "ssh-mcp must be declared in the manifest"
    assert entry.tier == "WARN"
    assert set(entry.types) >= {"windows", "linux"}
    assert "ssh-mcp" in entry.register
    assert entry.purpose and "control plane" in entry.purpose.lower()


def test_ssh_mcp_supply_declaration_never_blocks():
    """Supply-group declared (install guidance) but WARN tier: a missing
    ssh-mcp can never FAIL the probe — CLI ssh is the fallback control
    plane; MCP liveness is not the channel probe's requirement (v5 D5)."""
    assert "ssh-mcp" in mp.MANIFEST_GROUPS.get("channel_ssh", ())
    entry = mp._BY_NAME["ssh-mcp"]
    assert entry.tier == "WARN"
    # exit_code_for: WARN-tier items alone never produce rc=1 (FAIL)
    missing = [mp.MCPCheck(name="ssh-mcp", status="WARN", tier="WARN",
                           detail="not registered", fix="x")]
    assert mp.exit_code_for(missing) == 2  # WARN, not FAIL
