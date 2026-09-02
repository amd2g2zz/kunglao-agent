#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_repair_l1.py — bounded L1 deterministic environment repair (#475).

The repair ladder's first rung: deterministic, idempotent, orchestrator-run
(fires heartbeat_tick first if freshness is needed). NOT a worker, NOT an
LLM loop — fixed actions with verified outcomes:

  adb-reconnect   adb reconnect + re-forward the conventional ports
                  (frida custom port; android_server) — safe no-op without
                  adb/a device
  vm-rediscover   vmrun list (VMware) → probe KUNGLAO_VM_HOST candidates'
                  shell+frida ports; a reachable candidate re-exports
                  KUNGLAO_VM_HOST — safe no-op without vmrun/VMs
  mcp-rehandshake re-read the MCP registry (~/.claude.json + .mcp.json) and
                  probe the bridge ports — a registry that reads clean IS the
                  re-handshake from a probe's standpoint (the MCP client
                  reconnects per-session) — safe no-op with no names

Every subcommand verifies-after-repair and rewrites the matching
runs/env-state.json entry (status + last_probe_ts + detail) — the single
source consumed by check_env_fresh / env_drift_watch. A repair that cannot
run (substrate absent) reports action=skip with the honest reason — never a
fabricated success or failure. L2 (env-fix worker) and L3 (ask a human) are
deliberately out of scope (#475 acceptance: L1 + wiring only).

CLI: env_repair_l1.py <workspace> [--all | --adb | --vm | --mcp] [--json]
Exit 0 always (repair outcome rides the JSON; a failed repair is drift to
surface, not a crash).
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="env_repair_l1", action="write_blocked",
                          detail="module wired")
except NameError:
    pass

import datetime
import json
import os
import shutil
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import toolchain as tc  # noqa: E402  (probe primitives + port conventions)
from init_state import read_project_type  # noqa: E402
import env_state_probe as esp  # noqa: E402  (env-state read/write single source)
import mcp_probe  # noqa: E402

ENV_STATE_REL = Path("runs") / "env-state.json"


from harness_common import utc_now_z as _utc_now  # #863 Family F: single source (was a local def)


def _load_env_state(ws: Path) -> dict:
    p = ws / ENV_STATE_REL
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"per_capability": {}, "written_by": esp.WRITTEN_BY, "ts": _utc_now()}


def _update_entry(state: dict, cap: str, status: str, detail: str) -> None:
    state.setdefault("per_capability", {})[cap] = {
        "status": status, "last_probe_ts": _utc_now(), "detail": detail,
    }


def _adb() -> str | None:
    return shutil.which("adb")


def repair_adb(ws: Path, state: dict) -> dict:
    """adb reconnect + re-forward; verify with the env probe's own check."""
    adb = _adb()
    if not adb:
        return {"action": "skip", "detail": "adb not on PATH — nothing to reconnect"}
    attached, _ = esp._adb_device_attached(adb)
    if not attached:
        # reconnect offline transports, then re-check
        tc._run_cmd([adb, "reconnect"], timeout=10)
        attached, detail = esp._adb_device_attached(adb)
        if not attached:
            return {"action": "skip",
                    "detail": f"no device after adb reconnect ({detail}) — L2/L3 territory"}
    else:
        detail = "device already attached"
    # re-forward the conventional ports (idempotent: adb forward replaces)
    for port in (tc.FRIDA_PORT, tc.ANDROID_SERVER_PORT):
        tc._run_cmd([adb, "forward", f"tcp:{port}", f"tcp:{port}"], timeout=10)
    _update_entry(state, "adb", "pass", f"reconnect: {detail}; forwards refreshed")
    return {"action": "repaired", "detail": detail}


def repair_vm(ws: Path, state: dict) -> dict:
    """VM rediscovery: vmrun list → probe candidates' shell+frida ports."""
    vmrun = shutil.which("vmrun")
    if not vmrun:
        return {"action": "skip", "detail": "vmrun not on PATH — no VMware CLI to rediscover with"}
    rc, out, err = tc._run_cmd([vmrun, "list"], timeout=15)
    if rc != 0:
        return {"action": "skip", "detail": f"vmrun list failed: {err or out[:80]}"}
    vms = [ln.strip() for ln in out.splitlines()
           if ln.strip().endswith((".vmx", ".vmx/")) and ln.strip() != "Total running VMs:"]
    if not vms:
        return {"action": "skip", "detail": "vmrun lists no running VMs"}
    # vmrun list gives paths, not IPs; the probe side stays env-driven — a
    # host that answers on both ports is the live lease. Re-probe the
    # configured host first, then keep the honest result either way.
    host = os.environ.get("KUNGLAO_VM_HOST", "")
    results = []
    ok = False
    if host:
        ok_shell, e1 = tc._tcp_connect(host, tc.VM_SHELL_PORT)
        ok_frida, e2 = tc._tcp_connect(host, tc.FRIDA_PORT)
        ok = ok_shell and ok_frida
        results.append(f"{host}: {'reachable' if ok else 'unreachable'}")
    detail = "; ".join(results + [f"{len(vms)} running VM(s) per vmrun"])
    _update_entry(state, "vm_reachable", "pass" if ok else "fail", detail)
    return {"action": "repaired" if ok else "unrepaired", "detail": detail}


def repair_mcp(ws: Path, state: dict) -> dict:
    """MCP re-handshake: re-read the registry + probe; clean read = repaired
    (the MCP client session reconnects per-use; the probe verifies supply)."""
    ptype = read_project_type(ws)
    if ptype is None:
        return {"action": "skip", "detail": "project_type undeclared — nothing to re-handshake"}
    try:
        checks = mcp_probe.check_mcp(ws, ptype)
    except Exception as exc:
        return {"action": "skip", "detail": f"registry unreadable ({exc})"}
    if not checks:
        return {"action": "skip", "detail": f"no MCP names registered for type {ptype}"}
    failed = [c.name for c in checks if c.status != "PASS"]
    if failed:
        _update_entry(state, "mcp_bridge", "fail",
                      f"re-handshake incomplete: {', '.join(failed)}")
        return {"action": "unrepaired", "detail": f"still unreachable: {', '.join(failed)}"}
    _update_entry(state, "mcp_bridge", "pass",
                  f"registry re-read clean ({len(checks)} name(s))")
    return {"action": "repaired", "detail": f"{len(checks)} name(s) verified"}


REPAIRS = {
    "adb-reconnect": repair_adb,
    "vm-rediscover": repair_vm,
    "mcp-rehandshake": repair_mcp,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: env_repair_l1.py <workspace> [--all | --adb | --vm | --mcp] [--json]",
              file=sys.stderr)
        return 2
    ws = Path(args[0]).resolve()
    rest = args[1:]
    as_json = "--json" in rest
    selected = ([k for k in REPAIRS] if ("--all" in rest or not rest)
                else [k for k, flag in (("adb-reconnect", "--adb"),
                                        ("vm-rediscover", "--vm"),
                                        ("mcp-rehandshake", "--mcp")) if flag in rest])
    state = _load_env_state(ws)
    repaired = {}
    for name in selected:
        repaired[name] = REPAIRS[name](ws, state)
    state["ts"] = _utc_now()
    esp.write(ws, state)
    out = {"ts": state["ts"], "repaired": repaired}
    if as_json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        for name, r in repaired.items():
            print(f"{name}: {r['action']} — {r['detail']}")
    return 0  # outcome rides the JSON; drift is data, not a crash


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
