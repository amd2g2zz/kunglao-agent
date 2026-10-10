#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_repair.py — MCP liveness probe + bounded self-repair (owner ruling 2026-10-10).

Why: mcp_probe.py reads JSON configs only ("never connects, never spawns" —
by design), so a registered-but-dead server (missing dep; a PATH-resolved
launcher poisoned by a foreign VIRTUAL_ENV) passed every pre-dispatch check
while every worker hit the same failure live. Init must TEST every declared
MCP server (connect-level) and repair what fails.

Layers (state-layered — diagnose AT the failing layer):
  registered?  declared in plugin.json mcpServers / workspace .mcp.json
  launched?    `command` resolves (absolute path exists / shutil.which hit)
  connects?    spawn + MCP initialize handshake completes within --timeout
  capable?     (out of scope here — connects? carries the initialize result)

Repair actions (bounded; NEVER installs into an unidentified environment):
  R1 non-absolute command -> resolve via which() and rewrite the entry to
     the absolute path (the entry survives PATH drift/VIRTUAL_ENV pollution).
  R2 spawn fails (ModuleNotFoundError / early exit) -> bounded family-candidate
     search (~/.local/bin, ~/projects|src|repos/*/.venv/bin — depth 1) for a
     console script that handshakes; rewrite the entry to the winner.
  R3 otherwise -> report the exact fix command (e.g. pip install …). The tool
     does NOT guess an install target: installing into the wrong env is the
     failure class this tool exists to stop.

CLI: mcp_repair.py <workspace> [--json] [--no-repair] [--timeout S]
Exit: 0 all declared servers connect / 1 some failed / 2 usage
"""
from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON = SKILL_ROOT / ".claude-plugin" / "plugin.json"
MCP_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT_S = 8.0


def _load_json(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def declared_servers(ws: Path) -> dict[str, dict]:
    """name -> {command, args, declared_in, entry_path} across the two
    registration surfaces (plugin-carried first; a workspace entry with the
    same name wins — it is the closer scope)."""
    out: dict[str, dict] = {}
    plugin = _load_json(PLUGIN_JSON) or {}
    for name, entry in (plugin.get("mcpServers") or {}).items():
        if isinstance(entry, dict) and entry.get("command"):
            out[name] = {**entry, "declared_in": "plugin",
                         "entry_path": str(PLUGIN_JSON)}
    ws_mcp = _load_json(ws / ".mcp.json") or {}
    servers = ws_mcp.get("mcpServers") or {}
    for name, entry in servers.items():
        if isinstance(entry, dict) and entry.get("command"):
            out[name] = {**entry, "declared_in": "workspace",
                         "entry_path": str(ws / ".mcp.json")}
    return out


def _resolve_command(command: str) -> tuple[str | None, str]:
    """(abs_path_or_None, detail). Absolute -> must exist; bare -> which()."""
    if os.sep in command:
        p = Path(command)
        return (str(p), "absolute") if p.is_file() else (None, "absolute path missing")
    hit = shutil.which(command)
    if hit:
        detail = "PATH-resolved"
        venv = os.environ.get("VIRTUAL_ENV")
        if venv and hit.startswith(venv + os.sep):
            detail += f" (inside foreign VIRTUAL_ENV={venv} — pollution-suspect)"
        return hit, detail
    return None, "not on PATH"


def mcp_handshake(argv: list[str], timeout: float = DEFAULT_TIMEOUT_S) -> tuple[bool, str]:
    """Spawn + MCP initialize handshake. True only on a JSON-RPC result for id=1."""
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1)
    except (OSError, ValueError) as exc:
        return False, f"spawn failed: {type(exc).__name__}: {exc}"
    init = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
                   "clientInfo": {"name": "mcp_repair", "version": "0.1"}}})
    try:
        proc.stdin.write(init + "\n")
        proc.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        from kunglao_log import warn
        # server died before reading stdin — the read loop below reports it
        warn("mcp_repair_stdin_write", f"{type(exc).__name__}: {exc}")
    deadline = time.time() + max(1.0, timeout)
    buf: list[str] = []
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                _, err = proc.communicate(timeout=3)
                tail = (err or "").strip()[-300:]
                return False, (f"exited rc={proc.returncode} before handshake; "
                               f"stderr: {tail or '(empty)'}")
            remaining = max(0.05, deadline - time.time())
            ready, _, _ = select.select([proc.stdout], [], [], min(0.5, remaining))
            if not ready:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                buf.append(line)
                continue
            if obj.get("id") == 1 and ("result" in obj or "error" in obj):
                if "result" in obj:
                    info = (obj["result"] or {}).get("serverInfo") or {}
                    name = info.get("name") or "?"
                    ver = info.get("version") or "?"
                    return True, f"initialize OK ({name} {ver})"
                return False, f"initialize error: {obj.get('error')}"
        _, err = proc.communicate(timeout=3)
        tail = (err or "").strip()[-200:]
        return False, (f"no initialize response within {timeout}s "
                       f"(rc={proc.returncode}); stderr: {tail or '(empty)'}")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


def _family_candidates(name: str) -> list[str]:
    """Bounded console-script candidates for a bare/poisoned entry (depth 1)."""
    home = Path.home()
    cands: list[Path] = [home / ".local" / "bin" / name]
    for top in ("projects", "src", "repos", "work"):
        cands += sorted((home / top).glob(f"*/.venv/bin/{name}"))
    return [str(p) for p in cands
            if p.is_file() and os.access(p, os.X_OK)]


def _rewrite_entry(entry_path: str, name: str, new_command: str) -> str | None:
    """Rewrite one server's command in its entry file. Returns old command or None."""
    path = Path(entry_path)
    doc = _load_json(path)
    if doc is None or name not in (doc.get("mcpServers") or {}):
        return None
    old = str((doc["mcpServers"][name] or {}).get("command") or "")
    doc["mcpServers"][name]["command"] = new_command
    try:
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    except OSError:
        return None
    return old


def repair_server(name: str, entry: dict, timeout: float) -> dict:
    """Probe one server; on failure run the bounded repair ladder R1/R2.
    Returns the per-server report row."""
    command = str(entry.get("command"))
    args = [str(a) for a in (entry.get("args") or [])]
    row: dict = {"name": name, "declared_in": entry.get("declared_in"),
                 "entry_path": entry.get("entry_path"),
                 "command": command, "args": args}
    resolved, res_detail = _resolve_command(command)
    row["launch"] = {"resolved": resolved, "detail": res_detail}
    if resolved is None:
        row["probe"] = {"ok": False, "detail": res_detail}
        row["repair"] = {"action": "none",
                         "detail": "command does not resolve; fix the entry by hand"}
        return row
    ok, detail = mcp_handshake([resolved] + args, timeout=timeout)
    row["probe"] = {"ok": ok, "detail": detail}
    if ok:
        if command != resolved and os.sep not in command:
            # R1: pin the entry to the resolved absolute path (survives PATH drift).
            old = _rewrite_entry(str(entry.get("entry_path")), name, resolved)
            if old is not None:
                ok2, detail2 = mcp_handshake([resolved] + args, timeout=timeout)
                row["repair"] = {"action": "R1-abs-pin", "old_command": old,
                                 "new_command": resolved}
                row["probe"] = {"ok": ok2, "detail": detail2}
        else:
            row["repair"] = None
        return row
    # R2: bounded family search for a working console script of the same name.
    for cand in _family_candidates(name):
        if cand == resolved:
            continue
        ok2, detail2 = mcp_handshake([cand], timeout=timeout)
        if ok2:
            old = _rewrite_entry(str(entry.get("entry_path")), name, cand)
            row["repair"] = {"action": "R2-candidate", "old_command": old,
                             "new_command": cand}
            row["probe"] = {"ok": True, "detail": f"repaired -> {detail2}"}
            return row
    hints = []
    if "No module named" in detail or "ModuleNotFoundError" in detail:
        hints.append("missing dependency — install it into the venv the "
                     "command actually names (never a PATH-resolved guess)")
    row["repair"] = {"action": "none", "detail": "; ".join(hints) or
                     "no bounded repair available; inspect stderr above"}
    return row


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.split("CLI:")[1].split("Exit:")[0].strip(), file=sys.stderr)
        return 2
    ws = Path(argv[0])
    as_json = "--json" in argv
    no_repair = "--no-repair" in argv
    timeout = DEFAULT_TIMEOUT_S
    if "--timeout" in argv:
        try:
            timeout = float(argv[argv.index("--timeout") + 1])
        except (IndexError, ValueError):
            return 2
    servers = declared_servers(ws)
    if not servers:
        payload = {"schema": "mcp-repair/1", "workspace": str(ws),
                   "servers": [], "note": "no declared servers"}
        print(json.dumps(payload, ensure_ascii=False) if as_json
              else "mcp_repair: no declared MCP servers")
        return 0
    rows = []
    for name, entry in sorted(servers.items()):
        if no_repair:
            resolved, res_detail = _resolve_command(str(entry.get("command")))
            ok = bool(resolved)
            detail = res_detail
            if ok:
                ok, detail = mcp_handshake(
                    [resolved] + [str(a) for a in (entry.get("args") or [])],
                    timeout=timeout)
            row = {"name": name, "declared_in": entry.get("declared_in"),
                   "probe": {"ok": ok, "detail": detail}, "repair": None}
        else:
            row = repair_server(name, entry, timeout)
        rows.append(row)
    payload = {"schema": "mcp-repair/1", "workspace": str(ws), "servers": rows}
    failed = [r for r in rows if not (r.get("probe") or {}).get("ok")]
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            p = r.get("probe") or {}
            mark = "PASS" if p.get("ok") else "FAIL"
            print(f"[{mark}] {r['name']} ({r.get('declared_in')}): {p.get('detail')}")
            rep = r.get("repair")
            if rep and rep.get("action") not in (None, "none"):
                print(f"       repaired via {rep['action']}: {rep.get('old_command')} -> {rep.get('new_command')}")
            elif rep and rep.get("detail"):
                print(f"       repair: {rep['detail']}")
        print(f"mcp_repair: {len(rows) - len(failed)}/{len(rows)} servers connect")
    return 1 if failed else 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
