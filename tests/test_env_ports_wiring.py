# -*- coding: utf-8 -*-
"""Issue #362 follow-up — .env partial wiring for env_check.py ports.

Pre-#362 state (from the ACCEPT review of PR #361): .env.example lists 6
vars but env_check.py only rebinds KUNGLAO_VM_HOST + GHIDRA_HOME from the
workspace .env. VM_SHELL_PORT / FRIDA_PORT overrides were honored by the
toolchain (scripts/toolchain.py) but silently ignored by env_check's
reachability probe, which probed hardcoded VM_PORTS = [9876, 1337].

Contract pinned here:

  1. KUNGLAO_VM_SHELL_PORT + KUNGLAO_FRIDA_PORT flow through the same
     stdlib parser precedence (os.environ wins, .env fills gaps)
  2. env_check's resolved ports list derives from those values
  3. KUNGLAO_CLAUDE_JSON + KUNGLAO_DIE stay os.environ-only, documented
     as such in .env.example (one clarifying line each)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ENV_EXAMPLE = ROOT / ".env.example"

sys.path.insert(0, str(SCRIPTS))
import env_check  # noqa: E402


@pytest.fixture
def clean_ports(monkeypatch):
    """Isolated port resolution: no process env leakage into the test."""
    for var in ("KUNGLAO_VM_SHELL_PORT", "KUNGLAO_FRIDA_PORT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(env_check, "VM_PORTS", [9876, 1337], raising=False)


# ---------- resolution precedence ----------

def test_resolve_ports_defaults(clean_ports, monkeypatch, tmp_path):
    ports = env_check.resolve_ports(tmp_path)
    assert ports == [9876, 1337]


def test_resolve_ports_from_dotenv(clean_ports, monkeypatch, tmp_path):
    """Port overrides in the workspace .env feed the reachability probe."""
    (tmp_path / ".env").write_text(
        "KUNGLAO_VM_SHELL_PORT=11111\nKUNGLAO_FRIDA_PORT=22222\n",
        encoding="utf-8")
    assert env_check.resolve_ports(tmp_path) == [11111, 22222]


def test_resolve_ports_env_wins_over_dotenv(clean_ports, monkeypatch, tmp_path):
    """Same precedence as the host: os.environ wins, .env fills gaps."""
    (tmp_path / ".env").write_text(
        "KUNGLAO_VM_SHELL_PORT=11111\nKUNGLAO_FRIDA_PORT=22222\n",
        encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_VM_SHELL_PORT", "33333")
    assert env_check.resolve_ports(tmp_path) == [33333, 22222]


def test_resolve_ports_partial_override(clean_ports, monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("KUNGLAO_FRIDA_PORT=44444\n", encoding="utf-8")
    assert env_check.resolve_ports(tmp_path) == [9876, 44444]


def test_resolve_ports_garbage_falls_back(clean_ports, monkeypatch, tmp_path):
    """Defensive parse (same as toolchain._parse_port): garbage/out-of-range
    values fall back to defaults instead of crashing the check."""
    (tmp_path / ".env").write_text(
        "KUNGLAO_VM_SHELL_PORT=not-a-port\nKUNGLAO_FRIDA_PORT=99999\n",
        encoding="utf-8")
    assert env_check.resolve_ports(tmp_path) == [9876, 1337]


def test_resolve_ports_env_garbage_ignored(clean_ports, monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_VM_SHELL_PORT", "garbage")
    assert env_check.resolve_ports(tmp_path) == [9876, 1337]


# ---------- run() wires the resolved list into check_vm ----------

def test_run_rebinds_ports_from_dotenv(clean_ports, monkeypatch, tmp_path):
    """run() rebinds VM_PORTS from the resolved values (mirrors the
    VM_HOST/GHIDRA_HOME rebind), so check_vm probes the configured ports.
    No real sockets: socket.create_connection is captured — the assertion is
    exactly which (host, port) pairs the reachability probe dialed."""
    dialed: list[tuple[str, int]] = []

    class _FakeSocket:
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    def _fake_connect(addr, timeout=None):
        dialed.append(addr)
        raise OSError("unreachable (test stub)")  # deterministic FAIL path

    monkeypatch.setattr(env_check.socket, "create_connection", _fake_connect)

    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / ".env").write_text(
        "KUNGLAO_VM_HOST=10.255.255.1\n"
        "KUNGLAO_VM_SHELL_PORT=11111\n"
        "KUNGLAO_FRIDA_PORT=22222\n",
        encoding="utf-8")
    monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
    monkeypatch.setattr(env_check, "VM_HOST", "", raising=False)

    rc = env_check.run(ws)
    assert rc == 1  # overall FAIL (host unreachable stub) — expected
    assert env_check.VM_PORTS == [11111, 22222], \
        "run() must rebind VM_PORTS from the .env-configured ports"
    assert dialed == [("10.255.255.1", 11111), ("10.255.255.1", 22222)], \
        f"check_vm probed wrong endpoints: {dialed}"
    import json
    snap = json.loads((ws / "runs" / ".env-check.json")
                      .read_text(encoding="utf-8"))
    vm = snap["checks"]["vm_reachability"]
    assert vm["status"] == "FAIL"
    assert "11111" in vm["detail"] and "22222" in vm["detail"]


# ---------- .env.example documentation ----------

def test_env_example_documents_claude_json_shell_only():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "KUNGLAO_CLAUDE_JSON" in text
    assert "shell" in text.lower() and "not read from .env" in text, (
        ".env.example must state KUNGLAO_CLAUDE_JSON is shell-export-only "
        "(a .env entry for it silently does nothing)")


def test_env_example_documents_die_shell_only():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "KUNGLAO_DIE" in text
    # the annotation line directly above the KUNGLAO_DIE= entry
    lines = text.splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln.strip() == "KUNGLAO_DIE=")
    annotation = "\n".join(lines[max(0, idx - 2):idx])
    assert "shell" in annotation.lower(), (
        f".env.example must state KUNGLAO_DIE is shell-export-only, got: "
        f"{annotation!r}")
