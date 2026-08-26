#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""init_channel_default.py — init-time channel resolution (#727).

User directive 2026-08-26: init must not dead-end on the environment. When
no remote channel (vmr/ssh/docker/adb) is reachable and no explicit
KUNGLAO_CHANNEL is set, init resolves the workspace channel to `local`
(static-only first-class citizen, #698 v6 matrix) and records a WARN event —
honest degradation with an explicit trail instead of a HARD dead-end.

Adaptation layer (#698-decoupled design D1): probes are local
implementations against the FINALIZED contract (KUNGLAO_CHANNEL =
ssh|docker|vmr|adb|local). The dynamic-task + local HARD REJECT belongs to
#698 and is deliberately absent here. Fail-open everywhere: this module must
be the last thing in init that raises.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import kunglao_log

REMOTE_CHANNELS = ("vmr", "ssh", "docker", "adb")
LOCAL = "local"
_PROBE_ORDER = ("vmr", "ssh", "docker", "adb")  # vmr first: current default

WARN_TEXT_DEFAULT = ("dynamic channel unavailable — defaulted to local "
                     "static-only channel")
WARN_TEXT_EXPLICIT = ("explicit KUNGLAO_CHANNEL={name} unavailable — fix the "
                      "environment or change KUNGLAO_CHANNEL")


@dataclass
class ChannelDecision:
    selected: str
    defaulted_to_local: bool = False
    probes: dict[str, str] = field(default_factory=dict)
    warn_reason: str = ""


def report_block(dec: ChannelDecision) -> dict:
    """The .init-report.json top-level `channel` block (design D5)."""
    return {
        "selected": dec.selected,
        "defaulted_to_local": dec.defaulted_to_local,
        "probes": dict(dec.probes),
    }


# ---------- capability probes (fail-open; design D3) ----------

def _env_get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _parse_port(raw: str, default: int) -> int:
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        return default


def _tcp_connect(host: str, port: int, timeout: int = 2) -> tuple[bool, str]:
    """LIVENESS pair member — mirrors toolchain._check_vm_channel semantics.

    Prefers the toolchain helper when importable (single source); the local
    fallback keeps this module importable in isolation (tests monkeypatch
    THIS name — see design D1 contract point 1).
    """
    try:
        from toolchain import _tcp_connect as _tc
        return _tc(host, port, timeout=timeout)
    except Exception:  # noqa: BLE001 — probe fail-open, never raise
        return False, f"no route {host}:{port}"


def _probe_vmr() -> tuple[bool, str]:
    host = _env_get("KUNGLAO_VM_HOST")
    if not host:
        return False, "KUNGLAO_VM_HOST unset"
    shell_port = _parse_port(_env_get("KUNGLAO_VM_SHELL_PORT"), 9876)
    frida_port = _parse_port(_env_get("KUNGLAO_FRIDA_PORT"), 1337)
    ok1, err1 = _tcp_connect(host, shell_port)
    ok2, err2 = _tcp_connect(host, frida_port)
    if ok1 and ok2:
        return True, f"vmr {host} reachable on {shell_port}+{frida_port}"
    return False, "; ".join(e for e in (err1, err2) if e) or "tcp fail"


def _probe_ssh(host: str | None = None, port: int | None = None) -> tuple[bool, str]:
    host = host if host is not None else _env_get("KUNGLAO_VM_HOST", "localhost")
    port = port if port is not None else _parse_port(
        _env_get("KUNGLAO_VM_SHELL_PORT"), 9876)
    cmd = ["ssh", "-p", str(port), "-o", "BatchMode=yes",
           "-o", "ConnectTimeout=5", host, "true"]
    try:
        r = subprocess.run(cmd, timeout=10, capture_output=True, text=True)
    except FileNotFoundError:
        return False, "ssh binary not found"
    except subprocess.TimeoutExpired:
        return False, "ssh connect timeout"
    except OSError as exc:  # noqa: BLE001 — probe fail-open
        return False, f"ssh probe error: {exc}"
    if r.returncode == 0:
        return True, f"ssh {host}:{port} exec ok"
    return False, f"ssh rc={r.returncode} (auth/dialect/unreachable)"


def _probe_docker() -> tuple[bool, str]:
    try:
        r = subprocess.run(["docker", "version"], timeout=10,
                           capture_output=True, text=True)
    except FileNotFoundError:
        return False, "docker binary not found"
    except subprocess.TimeoutExpired:
        return False, "docker daemon timeout"
    except OSError as exc:  # noqa: BLE001 — probe fail-open
        return False, f"docker probe error: {exc}"
    if r.returncode == 0:
        return True, "docker daemon reachable"
    return False, "docker daemon unreachable"


def _probe_adb() -> tuple[bool, str]:
    try:
        r = subprocess.run(["adb", "devices"], timeout=10,
                           capture_output=True, text=True)
    except FileNotFoundError:
        return False, "adb binary not found"
    except subprocess.TimeoutExpired:
        return False, "adb timeout"
    except OSError as exc:  # noqa: BLE001 — probe fail-open
        return False, f"adb probe error: {exc}"
    for line in (r.stdout or "").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip() in ("device", "emulator"):
            return True, f"adb device present ({parts[0].strip()})"
    return False, "no adb device attached/authorized"


def _probe_local() -> tuple[bool, str]:
    """Local channel — static-only first-class per #698 v6 matrix.

    No dynamic_re, no external toolchain, no subprocess, no socket.
    Returns (True, "...") so the probe is always available; carries the
    static-only / #698 v6 matrix alignment in the reason string. Adding
    this entry makes `local` a first-class dispatch row alongside
    vmr/ssh/docker/adb (uniform dispatch contract; see C-1 RED pin).
    """
    return (
        True,
        "local static-only channel per #698 v6 matrix; "
        "dynamic_re=False; tools_required=[]; "
        "no subprocess, no socket (in-process capability)"
    )


_PROBES = {"vmr": _probe_vmr, "ssh": _probe_ssh,
           "docker": _probe_docker, "adb": _probe_adb}
_PROBES[LOCAL] = _probe_local  # C-1: register local dispatch row (uniform contract)


# ---------- resolution (design D2) ----------

def resolve_init_channel(ws: Path) -> ChannelDecision:  # noqa: ARG001 — ws for symmetry/future emit-site
    """Probe + decide. Never raises; fail-open on every path."""
    probes: dict[str, str] = {}
    explicit = _env_get("KUNGLAO_CHANNEL").lower()

    if explicit:
        if explicit == LOCAL:
            # local is a first-class explicit choice — no probe, no warn
            return ChannelDecision(selected=LOCAL, defaulted_to_local=False,
                                   probes={}, warn_reason="")
        ok, reason = _probe_dispatch(explicit, probes)
        if ok:
            return ChannelDecision(selected=explicit, probes=probes)
        # explicit choice respected — never auto-switch (design D2)
        return ChannelDecision(
            selected=explicit, defaulted_to_local=False, probes=probes,
            warn_reason=WARN_TEXT_EXPLICIT.format(name=explicit))

    for name in _PROBE_ORDER:
        ok, _reason = _probe_dispatch(name, probes)
        if ok:
            return ChannelDecision(selected=name, probes=probes)
    return ChannelDecision(
        selected=LOCAL, defaulted_to_local=True, probes=probes,
        warn_reason=WARN_TEXT_DEFAULT)


def _probe_dispatch(name: str, probes: dict[str, str]) -> tuple[bool, str]:
    try:
        ok, reason = _PROBES[name]()
    except Exception as exc:  # noqa: BLE001 — a probe crash is unavailability
        ok, reason = False, f"probe crashed: {exc}"
    probes[name] = reason
    return ok, reason


# ---------- WARN event (fail-open; design D4) ----------

def emit_channel_decision(ws: Path, dec: ChannelDecision) -> None:
    """Record the degradation/guidance WARN. Logging never breaks init."""
    if not dec.warn_reason:
        return
    try:
        kunglao_log.emit(ws, actor="init", action="channel_default",
                         detail=dec.warn_reason)
    except Exception:  # noqa: BLE001 — emit contract, recursive here
        pass


def resolve_and_emit(ws: Path) -> ChannelDecision:
    dec = resolve_init_channel(ws)
    emit_channel_decision(ws, dec)
    return dec
