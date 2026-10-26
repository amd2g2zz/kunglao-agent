#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_state_probe.py — env-state single source of truth writer (#475).

The toolchain matrix is verified ONCE at init; between init and the T2/T3
dynamic phases the environment drifts silently (VM lease rotates, adb drops
the device, the frida forward dies, the MCP bridge restarts). This probe
refreshes a liveness-subset snapshot into runs/env-state.json — bound to the
heartbeat tick (step 9), the only mechanically-enforced periodic (#475
design argument: monitor is advisory-only (#88), external_kicker is one-shot
manual, per-dispatch probing violates the env_check_gate narrow+low-IO
contract).

#474 contract: presence/liveness probes ONLY on the periodic path — capability
trials (decompiler import etc.) are init-only/on-demand and never run here.

Schema (fact epistemology, simplified per issue #475 + evidence semantics):
    {
      "per_capability": {
        "<name>": {"status": "pass|fail|skip",
                   "last_probe_ts": "<ISO-8601-Z>",
                   "detail": "<probe output summary (evidence)>"},
        ...
      },
      "written_by": "env_state_probe",
      "ts": "<ISO-8601-Z>"
    }

Fail-open by design: a probe failure records status "fail" with honest
detail but never raises; a workspace with no declared project_type (or no
VM host / no adb) yields "skip" entries with the reason — never fabricated
failures. Exit code is always 0: env drift is monitor-visible
(kunglao-monitor env_drift_watch) and gate-visible (worker_budget
check_env_fresh), but must not crash the tick that hosts it.

CLI: env_state_probe.py <workspace> [--json]
"""
from __future__ import annotations
# issue 275 batch-3: fail-open handlers leave ONE rate-limited trace — the canonical kunglao_log.warn.
from kunglao_log import warn  # canonical warn: ONE implementation (process-wide dedupe + ledger face)
import json
import os
import shutil
import sys
from pathlib import Path

from _common import scripts_bootstrap  # noqa: E402  (leaf prologue; sibling imports below)

_SCRIPT_DIR = scripts_bootstrap()

# Reuse the #474 probe primitives — do not reimplement (single source).
import toolchain as tc  # noqa: E402  (_tcp_connect, _run_cmd, ports)
from init_state import read_project_type  # noqa: E402  (single source, #304 F6)
import mcp_probe  # noqa: E402  (#316 registry single source)

ENV_STATE_REL = Path("runs") / "env-state.json"
WRITTEN_BY = "env_state_probe"

# Capability sets per project type (liveness subset only). These are the
# names consumers (check_env_fresh / env_drift_watch / env_repair_l1)
# key on — aligned with the toolchain check-item vocabulary.
VM_CAPS = ("vm_reachable", "mcp_bridge")
# #474 follow-up (2026-08-19): jdwp_debug joins the snapshot — the toolchain
# WARN (capability-absence) is the orchestrator-facing signal this file
# mechanizes (probe miss → env-state entry → monitor ENV_DRIFT + gate view).
# #812: device_root joins (acceptance 3 — dispatch consults it, killing the
# "no root" misattribution class at the source) and host_frida joins (the
# 9x dynamic-trace incident: host frida missing was narrated as a device
# verdict because no host-side fact existed to separate it).
ANDROID_CAPS = ("adb", "frida_server", "jdwp_debug", "device_root",
                "host_frida")

# the web analysis chain's liveness subset: the MCP bridge (the camoufox
# L4 face's registration), the docker daemon (the jsir image face) and
# the iv8 module (the offline-execution face) — same probe-honesty
# contract as the android set (channel-absent is a SKIP, never fabricated)
WEB_CAPS = ("mcp_bridge", "host_docker", "iv8_module")


from harness_common import utc_now_z as _utc_now  # #863 Family F: single source (was a local def)

# #812: the dispatch-gate capability probes (host_frida / device_root)
# are THE single source for those two faces — this module only adapts
# their (status, detail) into snapshot entries.
import capability_probe as _cp  # noqa: E402


def _entry(status: str, detail: str) -> dict:
    return {"status": status, "last_probe_ts": _utc_now(), "detail": detail}


def _probe_vm_reachable() -> dict:
    host = os.environ.get("KUNGLAO_VM_HOST")
    if not host:
        return _entry("skip", "KUNGLAO_VM_HOST unset — no VM channel configured")
    ok_shell, err_shell = tc._tcp_connect(host, tc.VM_SHELL_PORT)
    ok_frida, err_frida = tc._tcp_connect(host, tc.FRIDA_PORT)
    if ok_shell and ok_frida:
        return _entry("pass", f"VM {host} reachable on {tc.VM_SHELL_PORT}+{tc.FRIDA_PORT}")
    err = "; ".join(e for e in (err_shell, err_frida) if e)
    return _entry("fail", f"VM unreachable: {err}")


def _adb_path() -> str | None:
    return shutil.which("adb")


def _adb_device_attached(adb: str) -> tuple[bool, str]:
    """True when `adb devices` lists at least one device."""
    rc, out, err = tc._run_cmd([adb, "devices"], timeout=10)
    if rc != 0:
        return False, f"adb devices failed: {err or out[:80]}"
    lines = [ln.strip() for ln in out.splitlines()
             if ln.strip() and not ln.startswith("List of devices")]
    devices = [ln for ln in lines if not ln.endswith("offline")]
    return (bool(devices), f"adb devices: {len(devices)} attached")


def _probe_adb() -> dict:
    adb = _adb_path()
    if not adb:
        return _entry("skip", "adb not on PATH — no android channel configured")
    attached, detail = _adb_device_attached(adb)
    return _entry("pass" if attached else "fail", detail)


def _probe_frida_server() -> dict:
    adb = _adb_path()
    if not adb:
        return _entry("skip", "adb not on PATH — frida-server not probeable")
    attached, _ = _adb_device_attached(adb)
    if not attached:
        return _entry("skip", "no adb device attached — frida-server not probeable")
    ok, detail = tc._adb_forward_probe(adb, tc.FRIDA_PORT)
    return _entry("pass" if ok else "fail",
                  f"frida-server on custom port {tc.FRIDA_PORT}: {detail}")


def _probe_jdwp_debug() -> dict:
    """#421 seam closed: ANDROID_CAPS declared jdwp_debug since the #474
    follow-up, but probe() never emitted it for android — the classifier
    vocabulary had no producer. Wiring reuses the #474 primitive
    (`_adb_jdwp_probe`) — never reimplemented (single source)."""
    adb = _adb_path()
    if not adb:
        return _entry("skip", "adb not on PATH — jdwp not probeable")
    attached, _ = _adb_device_attached(adb)
    if not attached:
        return _entry("skip", "no adb device attached — jdwp not probeable")
    ok, detail = tc._adb_jdwp_probe(adb)
    return _entry("pass" if ok else "fail", detail)


def _probe_device_root() -> dict:
    """#812 acceptance 3: the canonical root check joins the snapshot.
    Channel-absent stays a SKIP — a host without adb cannot produce a
    device-state verdict (the misattribution trap is structural)."""
    adb = _adb_path()
    if not adb:
        return _entry("skip", "adb not on PATH — device root UNVERIFIED "
                              "(channel absent, not device-unrooted)")
    attached, _ = _adb_device_attached(adb)
    if not attached:
        return _entry("skip", "no adb device attached — device root not "
                              "probeable")
    status, detail = _cp.probe_device_root(adb=adb)
    return _entry(status, detail)


def _probe_host_frida() -> dict:
    """#812 acceptance 1: the HOST-side face is its own fact — independent
    of any adb channel (frida --version runs with no device attached)."""
    status, detail = _cp.probe_host_frida()
    return _entry(status, detail)


def _probe_host_docker() -> dict:
    """The web chain's docker daemon face (the jsir image supply) — the
    probe face is the capability module's; this adapter only shapes the
    snapshot entry."""
    status, detail = _cp.probe_host_docker()
    return _entry(status, detail)


def _probe_iv8_module() -> dict:
    """The web chain's module face (the offline-execution supply) — an
    import probe in the workspace interpreter, honest negative included."""
    status, detail = _cp.probe_iv8_module()
    return _entry(status, detail)


def _probe_mcp_bridge(ws: Path, ptype: str) -> dict:
    try:
        checks = mcp_probe.check_mcp(ws, ptype)
    except Exception as exc:  # registry read failure is probe-honest, not fatal
        return _entry("skip", f"MCP registry unreadable ({exc})")
    if not checks:
        return _entry("skip", f"no MCP names registered for type {ptype}")
    failed = [c.name for c in checks if c.status != "PASS"]
    if failed:
        return _entry("fail", f"MCP not registered: {', '.join(failed)} (registry read only; capability unverified per #474)")
    return _entry("pass", f"{len(checks)} MCP name(s) registered and reachable")


def probe(ws: Path) -> dict:
    """Run the liveness-subset probes; return the env-state dict (not written)."""
    ptype = read_project_type(ws)
    caps: dict[str, dict] = {}
    if ptype is None:
        # no declared type → nothing to probe against; honest skips only
        for name in (*VM_CAPS, *ANDROID_CAPS):
            caps[name] = _entry(
                "skip", "project_type undeclared — run kunglao-init --type")
    elif ptype in ("windows", "linux"):
        caps["vm_reachable"] = _probe_vm_reachable()
        caps["mcp_bridge"] = _probe_mcp_bridge(ws, ptype)
    elif ptype == "android":
        caps["adb"] = _probe_adb()
        caps["frida_server"] = _probe_frida_server()
        caps["jdwp_debug"] = _probe_jdwp_debug()
        caps["device_root"] = _probe_device_root()
        caps["host_frida"] = _probe_host_frida()
    elif ptype == "web":
        caps["mcp_bridge"] = _probe_mcp_bridge(ws, ptype)
        caps["host_docker"] = _probe_host_docker()
        caps["iv8_module"] = _probe_iv8_module()
    return {"per_capability": caps, "written_by": WRITTEN_BY, "ts": _utc_now()}


def write(ws: Path, state: dict) -> Path:
    """Write runs/env-state.json atomically-enough for a tick step (best
    effort: write failure must not crash the tick)."""
    out = ws / ENV_STATE_REL
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    except OSError as exc:
        warn("write", f"{type(exc).__name__}: {exc}")
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: env_state_probe.py <workspace> [--json]", file=sys.stderr)
        return 2
    ws = Path(args[0]).resolve()
    as_json = "--json" in args[1:]
    state = probe(ws)
    out = write(ws, state)
    if as_json:
        print(json.dumps(state, ensure_ascii=False))
    else:
        parts = [f"{k}={v['status']}" for k, v in state["per_capability"].items()]
        print(f"env_state_probe: {' '.join(parts) or '(no capabilities)'}")
        print(f"written: {out}")
    return 0  # always — drift is advisory-visible, never tick-fatal


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
