# -*- coding: utf-8 -*-
"""Tests for #477 ③ — device-side deployment + one-off shim records
(scripts/deploy_shim.py).

Contract (openspec/changes/issue-477-deploy-completion design.md D4):
  * deploy face: idempotent adb deployment for the two services that
    previously lived only as FIX_TEXT — frida-server (push + RENAME +
    custom port, default toolchain.FRIDA_PORT) and android-server (push +
    run on ANDROID_SERVER_PORT). Idempotent: a PASSing port pre-probe is
    a no-op with ZERO device-side mutations — the probe itself still
    runs host-side adb forward (run-twice equivalence); after a real
    deploy the port re-probe must PASS before success is claimed.
  * the outcome lands in the env-facts installed ledger (manager
    "device-adb", reprobe PASS — the 3-field {manager, at, reprobe}
    shape, no port field).
  * new face (#462 normalization): materialize an annotated one-off shim
    record under scripts/shims/ — target/purpose/expiry fields, a
    discard-after-use contract line, a directory README declaring the
    discard semantics, field validation, overwrite refusal.

TDD RED phase: written BEFORE deploy_shim.py exists (function-level
imports so RED is test failure, not collection error).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_ds():
    import deploy_shim
    return deploy_shim


def _cp(argv, rc=0, out="", err=""):
    import subprocess
    return subprocess.CompletedProcess(args=argv, returncode=rc,
                                       stdout=out, stderr=err)


def _fake_adb_env(monkeypatch, ds, log, rc=0):
    """Seam wiring: adb on PATH, subprocess logged, probe flip-flops
    (first probe down = not deployed; second up = post-deploy PASS)."""
    monkeypatch.setattr(ds, "_shutil_which", lambda name: "/fake/adb")
    state = {"probes": 0}

    def probe(adb, port):
        state["probes"] += 1
        return (False, "down") if state["probes"] == 1 else (True, "up")

    monkeypatch.setattr(ds, "_probe_port", probe)
    monkeypatch.setattr(
        ds, "_subprocess_run",
        lambda argv, **kw: log.append(list(argv)) or _cp(argv, rc=rc))


# ---------- deploy: frida-server ----------

def test_deploy_frida_server_full_sequence(tmp_path, monkeypatch):
    ds = _load_ds()
    log: list[list[str]] = []
    _fake_adb_env(monkeypatch, ds, log)
    local = tmp_path / "frida-server-arm64"
    local.write_bytes(b"ELF\x02" + b"\x00" * 60)
    rc = ds.deploy("frida-server", local, port=1337, alias="sysmon")
    assert rc == ds.RC_OK, log
    pushed = [a for a in log if a[1:] == ["push", str(local),
                                          "/data/local/tmp/sysmon"]]
    assert pushed, f"renamed push must run: {log}"
    assert any(a[1:4] == ["shell", "chmod", "755"] for a in log), log
    started = [a for a in log if len(a) > 2 and a[1] == "shell"
               and "sysmon" in a[2] and "-l" in a[2] and "1337" in a[2]]
    assert started, f"background start on the custom port must run: {log}"


def test_deploy_frida_server_renamed_not_default_name(
        tmp_path, monkeypatch):
    """The #304 F3 convention: the on-device binary carries a NON-default
    name (default frida-server/27042 is detected by samples)."""
    ds = _load_ds()
    log: list[list[str]] = []
    _fake_adb_env(monkeypatch, ds, log)
    local = tmp_path / "fs"
    local.write_bytes(b"\x00")
    ds.deploy("frida-server", local, port=1337, alias="sysmon")
    flat = " ".join(" ".join(a) for a in log)
    assert "/data/local/tmp/sysmon" in flat
    assert "/data/local/tmp/frida-server" not in flat


def test_deploy_idempotent_two_runs_zero_mutations(tmp_path, monkeypatch):
    """Issue acceptance: run twice -> identical state. Second run's port
    pre-probe PASSes -> ZERO adb push/shell mutations."""
    ds = _load_ds()
    log: list[list[str]] = []
    monkeypatch.setattr(ds, "_shutil_which", lambda name: "/fake/adb")
    monkeypatch.setattr(ds, "_probe_port", lambda adb, port: (True, "up"))
    monkeypatch.setattr(
        ds, "_subprocess_run",
        lambda argv, **kw: log.append(list(argv)) or _cp(argv))
    local = tmp_path / "fs"
    local.write_bytes(b"\x00")
    rc1 = ds.deploy("frida-server", local, port=1337)
    rc2 = ds.deploy("frida-server", local, port=1337)
    assert rc1 == rc2 == ds.RC_OK
    assert log == [], f"already-deployed service must be a no-op: {log}"


def test_deploy_reprobe_gate_blocks_success(tmp_path, monkeypatch, capsys):
    """Deploy ran but the port re-probe still FAILs -> NOT success: the
    fix guidance prints and rc != 0 (#474 posture: never claim an
    unverified deployment)."""
    ds = _load_ds()
    log: list[list[str]] = []
    monkeypatch.setattr(ds, "_shutil_which", lambda name: "/fake/adb")
    # pre-probe down, post-probe still down
    monkeypatch.setattr(ds, "_probe_port", lambda adb, port: (False, "down"))
    monkeypatch.setattr(
        ds, "_subprocess_run",
        lambda argv, **kw: log.append(list(argv)) or _cp(argv))
    local = tmp_path / "fs"
    local.write_bytes(b"\x00")
    rc = ds.deploy("frida-server", local, port=1337)
    assert rc == ds.RC_DEPLOY_FAILED, rc
    out = capsys.readouterr()
    assert "frida-server" in (out.out + out.err)


def test_deploy_missing_local_binary(tmp_path, monkeypatch):
    ds = _load_ds()
    log: list[list[str]] = []
    _fake_adb_env(monkeypatch, ds, log)
    rc = ds.deploy("frida-server", tmp_path / "nonexistent", port=1337)
    assert rc == ds.RC_DEPLOY_FAILED
    assert log == [], "no adb call may run for a missing local binary"


def test_deploy_no_adb(tmp_path, monkeypatch):
    ds = _load_ds()
    monkeypatch.setattr(ds, "_shutil_which", lambda name: None)
    rc = ds.deploy("frida-server", tmp_path / "fs", port=1337)
    assert rc == ds.RC_DEPLOY_FAILED


# ---------- deploy: android-server ----------

def test_deploy_android_server_sequence_and_port(tmp_path, monkeypatch):
    import toolchain
    ds = _load_ds()
    log: list[list[str]] = []
    seen: dict[int, tuple[bool, str]] = {}

    def probe(adb, port):
        # pre-probe (first call) fails; post-probe succeeds
        first = seen.get(1) is None
        seen[1] = (True, "")
        return (False, "down") if first else (True, "up")

    monkeypatch.setattr(ds, "_shutil_which", lambda name: "/fake/adb")
    monkeypatch.setattr(ds, "_probe_port", probe)
    monkeypatch.setattr(
        ds, "_subprocess_run",
        lambda argv, **kw: log.append(list(argv)) or _cp(argv))
    local = tmp_path / "android_server"
    local.write_bytes(b"\x00")
    rc = ds.deploy("android-server", local)
    assert rc == ds.RC_OK, log
    assert any(a[1] == "push" and str(local) in a for a in log), log
    started = [a for a in log if len(a) > 2 and a[1] == "shell"
               and "android_server" in a[2]]
    assert started, log
    # default port = the toolchain ANDROID_SERVER_PORT convention
    assert toolchain.ANDROID_SERVER_PORT == 23946


# ---------- deploy: ledger (#450 installed face) ----------

def test_deploy_records_installed_ledger(tmp_path, monkeypatch):
    ds = _load_ds()
    log: list[list[str]] = []
    _fake_adb_env(monkeypatch, ds, log)
    recorded: dict = {}

    import env_manifest
    monkeypatch.setattr(
        env_manifest, "record_installed",
        lambda ws, name, manager, reprobe, at=None:
        recorded.update({"ws": ws, "name": name, "manager": manager,
                         "reprobe": reprobe}) or True)
    local = tmp_path / "fs"
    local.write_bytes(b"\x00")
    ws = tmp_path / "ws"
    rc = ds.deploy("frida-server", local, port=1337, ws=ws)
    assert rc == ds.RC_OK
    assert recorded["name"] == "frida_server", recorded
    assert recorded["manager"] == "device-adb", recorded
    assert recorded["reprobe"] == "PASS", recorded


# ---------- new face: #462 shim records ----------

def test_make_shim_writes_annotation_and_readme(tmp_path):
    ds = _load_ds()
    root = tmp_path / "shims"
    rc = ds.make_shim("vb-fixup", purpose="one-off VB registry fix for "
                      "engagement X", expiry="2026-08-31",
                      target="analysis VM registry", root=root)
    assert rc == ds.RC_OK
    note = root / "vb-fixup.md"
    assert note.is_file()
    text = note.read_text(encoding="utf-8")
    assert "- purpose: " in text and "engagement X" in text
    assert "- expiry: " in text and "2026-08-31" in text
    assert "- target: " in text and "registry" in text
    assert "DISCARD AFTER USE" in text, "discard contract must be in-file"
    readme = root / "README.md"
    assert readme.is_file()
    assert "discard" in readme.read_text(encoding="utf-8").lower()


def test_make_shim_requires_purpose_and_expiry(tmp_path):
    ds = _load_ds()
    rc = ds.make_shim("x", purpose="", expiry="2026-08-31",
                      root=tmp_path)
    assert rc == ds.RC_VALIDATION
    rc = ds.make_shim("x", purpose="p", expiry="",
                      root=tmp_path)
    assert rc == ds.RC_VALIDATION


def test_make_shim_validates_name_slug(tmp_path):
    ds = _load_ds()
    rc = ds.make_shim("../escape", purpose="p", expiry="e",
                      root=tmp_path)
    assert rc == ds.RC_VALIDATION


def test_make_shim_refuses_overwrite(tmp_path):
    ds = _load_ds()
    rc1 = ds.make_shim("dup", purpose="p1", expiry="e", root=tmp_path)
    assert rc1 == ds.RC_OK
    rc2 = ds.make_shim("dup", purpose="p2", expiry="e", root=tmp_path)
    assert rc2 == ds.RC_VALIDATION
    assert "p1" in (tmp_path / "dup.md").read_text(encoding="utf-8")
