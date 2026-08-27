# -*- coding: utf-8 -*-
"""tests/test_init_channel_default_727.py — init auto-defaults channel to
local when no dynamic environment (#727).

Contract basis: the #698 v6 matrix (KUNGLAO_CHANNEL = ssh|docker|vmr|adb|local,
local = static-only first-class). Every probe is mocked — zero real network,
zero real subprocess. RED on the missing module; GREEN after
scripts/init_channel_default.py lands.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import init_channel_default as icd  # noqa: E402


def _logs(ws: Path) -> list[dict]:
    out = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


class _Proc:
    """Fake subprocess.run result."""

    def __init__(self, rc: int = 0, out: str = ""):
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


def _mock_all_unavailable(monkeypatch):
    monkeypatch.setattr(icd, "_tcp_connect", lambda h, p, timeout=2: (False, f"no route {h}:{p}"))

    def fake_run(cmd, **kw):
        return _Proc(rc=1, out="")

    monkeypatch.setattr(icd.subprocess, "run", fake_run)


# ---------- 1. all remote unavailable -> local + WARN ----------

def test_all_unavailable_defaults_to_local(tmp_path, monkeypatch):
    _mock_all_unavailable(monkeypatch)
    ws = _mk_ws(tmp_path)
    monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
    dec = icd.resolve_init_channel(ws)
    assert dec.selected == "local"
    assert dec.defaulted_to_local is True
    assert set(dec.probes) == {"vmr", "ssh", "docker", "adb"}
    # every probe must carry an unavailable reason
    assert all(v for v in dec.probes.values())


def test_all_unavailable_emits_warn_event(tmp_path, monkeypatch):
    _mock_all_unavailable(monkeypatch)
    ws = _mk_ws(tmp_path)
    monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
    dec = icd.resolve_init_channel(ws)
    icd.emit_channel_decision(ws, dec)
    events = [e for e in _logs(ws) if e.get("action") == "channel_default"]
    assert events, "channel_default WARN event must land in runs/logs"
    assert "local" in events[0]["detail"]


# ---------- 2. a reachable remote channel -> no degrade ----------

def test_ssh_available_no_default(tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)

    def fake_run(cmd, **kw):
        if cmd and cmd[0] == "ssh":
            return _Proc(rc=0)
        return _Proc(rc=1)

    monkeypatch.setattr(icd.subprocess, "run", fake_run)
    monkeypatch.setattr(icd, "_tcp_connect", lambda h, p, timeout=2: (False, "down"))
    dec = icd.resolve_init_channel(_mk_ws(tmp_path))
    assert dec.selected == "ssh"
    assert dec.defaulted_to_local is False


def test_ssh_probe_command_shape(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        seen["kw"] = kw
        return _Proc(rc=0)

    monkeypatch.setattr(icd.subprocess, "run", fake_run)
    ok, reason = icd._probe_ssh("h", 2222)
    assert ok and "h" in seen["cmd"] and "-o" in seen["cmd"]
    assert "BatchMode=yes" in seen["cmd"] and "-p" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("-p") + 1] == "2222"
    assert kw_ok(seen["kw"])


def kw_ok(kw) -> bool:
    return kw.get("timeout", 0) <= 15 and kw.get("capture_output") is True


# ---------- 3. explicit channel: never auto-switch ----------

def test_explicit_unavailable_keeps_choice_with_guidance(tmp_path, monkeypatch):
    _mock_all_unavailable(monkeypatch)
    ws = _mk_ws(tmp_path)
    monkeypatch.setenv("KUNGLAO_CHANNEL", "ssh")
    dec = icd.resolve_init_channel(ws)
    assert dec.selected == "ssh"          # kept, not switched
    assert dec.defaulted_to_local is False
    assert "ssh" in dec.warn_reason       # guidance names the situation
    icd.emit_channel_decision(ws, dec)
    events = [e for e in _logs(ws) if e.get("action") == "channel_default"]
    assert events and "KUNGLAO_CHANNEL" in events[0]["detail"]


def test_explicit_local_stays_local_no_warn(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path)
    monkeypatch.setenv("KUNGLAO_CHANNEL", "local")
    dec = icd.resolve_init_channel(ws)
    assert dec.selected == "local"
    assert dec.defaulted_to_local is False
    assert dec.warn_reason == ""


# ---------- 4. fail-open ----------

def test_emit_failure_never_breaks(tmp_path, monkeypatch):
    _mock_all_unavailable(monkeypatch)
    ws = _mk_ws(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("log disk full")

    monkeypatch.setattr(icd.kunglao_log, "emit", boom)
    dec = icd.resolve_init_channel(ws)   # emit inside resolve must be swallowed
    icd.emit_channel_decision(ws, dec)   # direct call must also be fail-open
    assert dec.selected == "local"


# ---------- 5. init-report channel block ----------

def _load_ki():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_mod", REPO / "scripts" / "kunglao-init.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_init_report_carries_channel_block(tmp_path):
    ki = _load_ki()
    ws = _mk_ws(tmp_path)
    dec = icd.ChannelDecision(
        selected="local", defaulted_to_local=True,
        probes={"vmr": "host unset"}, warn_reason="all remote unavailable")
    p = ki.write_init_report(ws, [], "PASS", 0, channel=icd.report_block(dec))
    doc = json.loads((ws / "runs" / ".init-report.json").read_text(encoding="utf-8"))
    assert doc["channel"]["selected"] == "local"
    assert doc["channel"]["defaulted_to_local"] is True


def test_init_report_omits_channel_without_decision(tmp_path):
    ki = _load_ki()
    ws = _mk_ws(tmp_path)
    ki.write_init_report(ws, [], "PASS", 0)
    doc = json.loads((ws / "runs" / ".init-report.json").read_text(encoding="utf-8"))
    assert "channel" not in doc


# ---------- 6. docker/adb probe shapes ----------

def test_adb_probe_detects_device(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        return _Proc(rc=0, out="List of devices attached\n emulator-5554\tdevice\n")
    monkeypatch.setattr(icd.subprocess, "run", fake_run)
    ok, _ = icd._probe_adb()
    assert ok is True


def test_adb_probe_no_device(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        return _Proc(rc=0, out="List of devices attached\n\n")
    monkeypatch.setattr(icd.subprocess, "run", fake_run)
    ok, reason = icd._probe_adb()
    assert ok is False and reason


def test_docker_probe_missing_binary(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        raise FileNotFoundError("docker not installed")
    monkeypatch.setattr(icd.subprocess, "run", fake_run)
    ok, reason = icd._probe_docker()
    assert ok is False and "docker" in reason.lower()


# ---------- 7. event vocabulary registration ----------

def test_channel_default_in_emit_actions():
    import event_taxonomy as et
    assert "channel_default" in et.EMIT_ACTIONS
    assert list(et.EMIT_ACTIONS) == sorted(et.EMIT_ACTIONS)


# ---------- 8. C-group: #698 D1 contract reconcile (RED pins) ----------

def test_probe_dispatch_table_has_local_row():
    """#698 D1 point (1) — the probe dispatch table MUST contain a `local`
    row alongside vmr/ssh/docker/adb (local is a first-class dispatchable,
    not a special-case branch). RED against impls that short-circuit local
    outside `_PROBES`; GREEN once `_PROBES['local']` is registered.
    """
    probes = getattr(icd, "_PROBES", None)
    assert isinstance(probes, dict) and probes, (
        "_PROBES must be a non-empty dispatch dict")
    assert "local" in probes, (
        f"_PROBES must contain 'local' row; got {sorted(probes)}")
    assert callable(probes["local"]), (
        "_PROBES['local'] must be a probe callable")


def test_local_probe_is_static_only_no_dynamic_calls():
    """#698 D1 point (3) — `_PROBES['local']` is a static-only probe: it
    must NOT invoke subprocess.run nor _tcp_connect (no dynamic_re, no
    network). Locks the static-only invariant against #698 matrix v6.
    """
    sub_calls = []
    tcp_calls = []

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            icd.subprocess, "run",
            lambda *a, **k: sub_calls.append(list(a)) or _Proc(rc=1))
        monkeypatch.setattr(
            icd, "_tcp_connect",
            lambda h, p, timeout=2: tcp_calls.append((h, p)) or (False, ""))
        fn = icd._PROBES["local"]
        ok, reason = fn()
    finally:
        monkeypatch.undo()

    assert ok is True, "local probe must report available"
    assert reason, "local probe must carry a non-empty reason"
    assert sub_calls == [], (
        f"local probe must not spawn subprocess; saw {sub_calls}")
    assert tcp_calls == [], (
        f"local probe must not open tcp; saw {tcp_calls}")


def test_kunglao_channel_env_recognizes_local_value(tmp_path, monkeypatch):
    """#698 D1 point (2) — KUNGLAO_CHANNEL accepts `local` as a first-class
    value (env name + value set contract). RED if impl rejects/ignores the
    local value; GREEN when resolve honours the explicit local choice.
    """
    ws = _mk_ws(tmp_path)
    monkeypatch.setenv("KUNGLAO_CHANNEL", "local")
    dec = icd.resolve_init_channel(ws)
    # env name recognized + value honoured — no warn, no defaulted flag
    assert dec.selected == "local"
    assert dec.defaulted_to_local is False
    assert dec.warn_reason == ""
    assert "local" in {icd.LOCAL, *getattr(icd, "REMOTE_CHANNELS", ())}
