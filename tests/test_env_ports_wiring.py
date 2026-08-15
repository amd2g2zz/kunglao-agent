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
    No real sockets: an unreachable host makes check_vm FAIL, and the
    failure detail names the .env-configured port numbers."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / ".env").write_text(
        "KUNGLAO_VM_HOST=10.255.255.1\n"
        "KUNGLAO_VM_SHELL_PORT=11111\n"
        "KUNGLAO_FRIDA_PORT=22222\n",
        encoding="utf-8")
    monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
    monkeypatch.setattr(env_check, "VM_HOST", "", raising=False)

    rc, report = env_check.run(ws)
    vm = report["checks"]["vm_reachability"]
    assert vm["status"] == "FAIL"
    assert "11111" in vm["detail"], \
        "check_vm must probe the .env-configured shell port"
    assert "22222" in vm["detail"], \
        "check_vm must probe the .env-configured frida port"


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
    die_line = next(ln for ln in text.splitlines()
                    if ln.startswith("#") and "KUNGLAO_DIE" not in ln
                    and "DIE" in ln)
    assert "shell" in die_line.lower()
