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

import datetime
import json
import os
import shutil
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

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
ANDROID_CAPS = ("adb", "frida_server", "jdwp_debug")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


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


def _probe_mcp_bridge(ws: Path, ptype: str) -> dict:
    try:
        checks = mcp_probe.check_mcp(ws, ptype)
    except Exception as exc:  # registry read failure is probe-honest, not fatal
        return _entry("skip", f"MCP registry unreadable ({exc})")
    if not checks:
        return _entry("skip", f"no MCP names registered for type {ptype}")
    failed = [c.name for c in checks if c.status != "PASS"]
    if failed:
        return _entry("fail", f"MCP unreachable: {', '.join(failed)}")
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
    return {"per_capability": caps, "written_by": WRITTEN_BY, "ts": _utc_now()}


def write(ws: Path, state: dict) -> Path:
    """Write runs/env-state.json atomically-enough for a tick step (best
    effort: write failure must not crash the tick)."""
    out = ws / ENV_STATE_REL
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    except OSError:
        pass
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
    sys.exit(main())
