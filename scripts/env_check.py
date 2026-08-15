#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_check.py — environment-init checklist for kunglao-agent workspaces.

Issue #233: Phase 0 "环境探测(先行,必做)" was narrative-only — no executable
checklist, no PASS/FAIL output, no "fail blocks analysis" gate. The 2026-08-12
incident ran a whole session with CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
(teammate-polluted dispatches, 400 [1210] everywhere) and zero hook registration;
nothing stopped it.

This script is the mechanical cure. Run BEFORE analysis starts (Phase 0), output
PASS/FAIL per check + exit code (0 = all pass, 1 = any FAIL). Writes
<ws>/runs/.env-check.json snapshot for gates to read.

Checks:
  1. AGENT_TEAMS flag — process/User/Machine scope (decides session teammate behavior)
  2. VM reachability   — TCP 9876 (vmr-shell) + 1337 (Frida), 2s timeout each
  3. Ghidra            — analyzeHeadless.bat exists (path from GHIDRA_HOME env; unset = FAIL with guidance)
  4. Hook deployment   — <ws>/.claude/settings.json has the kunglao hooks
                         wire_up_settings registers (PROJECT-level, #258/#269)
  5. venv + sample     — .venv python exists w/ cryptography+yaml; sample sha256

FAIL grading (gate logic lives in hooks/env_check_gate.py):
  - flag check is HARD — a polluted session must not dispatch at all
  - VM/Ghidra/hook FAIL are recoverable (static analysis can proceed) — gate
    injects guidance instead of aborting
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import init_state  # noqa: E402  # F6 (#304 review): shared init-completeness predicate
import wire_up_settings  # noqa: E402  # #372: hook registry single source

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
TRUTHY_VALUES = ("1", "true", "yes", "on")  # #276: truthy = FAIL; 0/false/off/empty = PASS
# Issue #228: NO machine-specific default. Unset = not configured — the check
# FAILs with guidance instead of silently pointing at one operator's lab VM /
# Ghidra install (a wrong default on any other machine is worse than a FAIL).
VM_HOST = os.environ.get("KUNGLAO_VM_HOST", "")
VM_PORTS = [9876, 1337]
# #362: default port pair (vmr-shell, frida) — overridden per-run by
# resolve_ports() from KUNGLAO_VM_SHELL_PORT / KUNGLAO_FRIDA_PORT (env first,
# workspace .env fallback; mirrors scripts/toolchain.py's defensive parse).
DEFAULT_SHELL_PORT = 9876
DEFAULT_FRIDA_PORT = 1337
_ghidra_home = os.environ.get("GHIDRA_HOME")
GHIDRA_DEFAULT = Path(_ghidra_home) / "support" / "analyzeHeadless.bat" if _ghidra_home else None


def _parse_port(raw: str | None, default: int) -> int:
    """Defensive port parse (same semantics as toolchain._parse_port):
    int(raw) in [1, 65535], else default — garbage never crashes the check."""
    try:
        value = int((raw or "").strip() or str(default))
    except ValueError:
        return default
    return value if 1 <= value <= 65535 else default


def resolve_ports(ws: Path) -> list[int]:
    """#362: [VM_SHELL_PORT, FRIDA_PORT] from env-first, .env-fallback
    resolution (same precedence as load_dotenv: os.environ wins, the
    workspace .env fills gaps)."""
    dotenv = load_dotenv(ws)
    shell = (os.environ.get("KUNGLAO_VM_SHELL_PORT")
             or dotenv.get("KUNGLAO_VM_SHELL_PORT"))
    frida = (os.environ.get("KUNGLAO_FRIDA_PORT")
             or dotenv.get("KUNGLAO_FRIDA_PORT"))
    return [
        _parse_port(shell, DEFAULT_SHELL_PORT),
        _parse_port(frida, DEFAULT_FRIDA_PORT),
    ]


def load_dotenv(ws: Path) -> dict:
    """#356 W4: stdlib .env parser (no python-dotenv dependency).

    Reads <ws>/.env KEY=VALUE lines (comments/blank lines skipped; lines
    without '=' skipped best-effort) and returns the EFFECTIVE view:
    real os.environ entries always win, .env only fills gaps.
    """
    envf = Path(ws) / ".env"
    if not envf.is_file():
        return {}
    merged: dict[str, str] = {}
    for raw in envf.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            merged[key] = value.strip()
    # os.environ wins — .env is the fallback, never an override
    return {**merged, **{k: v for k, v in os.environ.items() if k in merged}}
# #372: the deployed-hook set IS wire_up_settings' registry (the writer) —
# never a hand-mirrored list (the pre-#372 mirror listed 6 while 8 were
# registered, making a recall_inject/completion_gate silent drop invisible).
HOOK_FILES = wire_up_settings.WIRE_UP_HOOK_FILES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_truthy(value: str | None) -> bool:
    """Truthy check: 1/true/yes/on, case-insensitive (#276 default-to-0 semantics)."""
    return value is not None and value.strip().lower() in TRUTHY_VALUES


# ---------- checks ----------

def check_flag() -> tuple[bool, str]:
    """CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS must NOT be TRUTHY in process scope.

    #276: default-disabled — only truthy values (1/true/yes/on, case-insensitive)
    pollute the session (teammate channel); 0/false/off/empty are the clean
    default state and PASS with detail "disabled (<value>)".
    #88 isolation-first: flag is "REMOVED, SHALL NOT be re-enabled" (cold-start-
    contract.md:46-51). Process scope is the one that decides this session's
    teammate behavior; User/Machine scopes are checked via powershell when the
    workspace host is Windows (informational, same truthy semantics).
    """
    truthy = []
    process_val = os.environ.get(FLAG_NAME)
    if process_val is not None and is_truthy(process_val):
        truthy.append(f"process={process_val}")
    if os.name == "nt":
        for scope in ("User", "Machine"):
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"[Environment]::GetEnvironmentVariable('{FLAG_NAME}','{scope}')"],
                    capture_output=True, text=True, timeout=10,
                )
                val = r.stdout.strip()
                if val and is_truthy(val):
                    truthy.append(f"{scope.lower()}={val}")
            except Exception:
                pass  # powershell unavailable — process scope suffices
    if truthy:
        return (False,
                f"{FLAG_NAME} truthy ({', '.join(truthy)}). Fix: unset the "
                f"variable in the launching shell, then RESTART the session — "
                f"a polluted session dispatches through the teammate channel "
                f"(kunglao #88 forbids it; 2026-08-12: 400 [1210] cascade).")
    state = f"disabled ({process_val})" if process_val else "not set (default disabled)"
    return True, f"{FLAG_NAME} {state} — clean session"


def check_vm() -> tuple[bool, str]:
    """VM reachability: TCP connect to vmr-shell + Frida ports, 2s timeout."""
    if not VM_HOST:
        return (False,
                "KUNGLAO_VM_HOST unset — set it to the live VM lease "
                "(vmr-shell discovery). Dynamic analysis (T3) blocked; static "
                "may proceed.")
    failed = []
    for port in VM_PORTS:
        try:
            with socket.create_connection((VM_HOST, port), timeout=2):
                pass
        except OSError as exc:
            failed.append(f"{port}:{exc}")
    if failed:
        return (False,
                f"VM {VM_HOST} unreachable — {', '.join(failed)}. "
                f"Dynamic analysis (T3) blocked; static may proceed.")
    return True, f"VM {VM_HOST} reachable on {', '.join(str(p) for p in VM_PORTS)}"


def check_ghidra() -> tuple[bool, str]:
    """Ghidra analyzeHeadless present (path from GHIDRA_HOME env; unset = FAIL)."""
    if GHIDRA_DEFAULT is None:
        return (False,
                "GHIDRA_HOME unset — set it to your Ghidra install root; "
                "decompilation degraded.")
    if GHIDRA_DEFAULT.exists():
        return True, f"analyzeHeadless at {GHIDRA_DEFAULT}"
    return (False,
            f"analyzeHeadless not found at {GHIDRA_DEFAULT}. "
            f"Set GHIDRA_HOME or install Ghidra — decompilation degraded.")


def check_hooks(ws: Path) -> tuple[bool, str]:
    """kunglao hooks registered in the PROJECT settings.json
    (<ws>/.claude/settings.json) — the deployment target since #258.

    #269: this previously read the user-global ~/.claude/settings.json, which
    is NOT a deployment target since #258 — a correctly wired PROJECT-level
    deployment was misreported as 'hooks missing'. The user-global file can
    still be checked by hooks_selfcheck (warning-only, migration guidance)."""
    settings = ws / ".claude" / "settings.json"
    if not settings.exists():
        return False, f"no settings.json at {settings} — run hook_activation.py --wire-up"
    s = _load_json(settings)
    pre = s.get("hooks", {}).get("PreToolUse", []) or []
    post = s.get("hooks", {}).get("PostToolUse", []) or []
    # #372: Stop must be scanned too — completion_gate.py is a Stop hook; a
    # Pre/Post-only scan can never verify it (the blind spot that hid the
    # 6-vs-8 mirror drift).
    stop = s.get("hooks", {}).get("Stop", []) or []
    cmds = []
    for entry in pre + post + stop:
        for h in entry.get("hooks", []) or []:
            cmds.append(str(h.get("command", "")))
    missing = [h for h in HOOK_FILES if not any(h in c for c in cmds)]
    if missing:
        return (False,
                f"hooks missing from settings.json: {', '.join(missing)}. "
                f"Fix: python <skill>/scripts/hook_activation.py <ws> --wire-up")
    # activation state (soft — 30-min TTL expected during a live loop)
    state = _load_json(ws / ".hook_state.json")
    active = state.get("active_hooks", []) or []
    act = f" — {len(active)} active hook(s)" if active else " (not activated — hooks sleep)"
    return True, f"{len(HOOK_FILES)} hooks registered{act}"


def check_venv_sample(ws: Path, sample_sha256: str | None) -> tuple[bool, str]:
    """venv python with cryptography+yaml; sample sha256 vs task_spec if present."""
    problems = []
    venv_py = ws / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        try:
            r = subprocess.run([str(venv_py), "-c", "import cryptography, yaml"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                problems.append(f"venv missing deps (cryptography/yaml): {r.stderr.strip()[:80]}")
        except Exception as exc:
            problems.append(f"venv probe failed: {exc}")
    else:
        problems.append(f"no .venv at {venv_py}")
    if sample_sha256 and sample_sha256 != "UNSET":
        for cand in (ws / "bins").glob("*"):
            if cand.is_file():
                h = hashlib.sha256(cand.read_bytes()).hexdigest()
                if h != sample_sha256:
                    problems.append(f"sample {cand.name} sha256 mismatch ({h[:12]}...)")
                break
        else:
            problems.append("no sample under bins/")
    if problems:
        return False, "; ".join(problems)
    return True, "venv deps OK" + ("; sample sha256 OK" if sample_sha256 else "")


def check_init_complete(ws: Path) -> tuple[bool, str]:
    """#304: init completeness check (HARD).

    Requires BOTH:
    - [initialized] marker in claim-register.yaml
    - project_type=<type> in analysis_state.txt (where type in windows/linux/android)

    Missing either -> FAIL with guidance to run kunglao-init.py --type.
    F6 (#304 review): the predicate lives in scripts/init_state.py — single
    source of truth shared with kunglao-init and env_check_gate.
    """
    return init_state.init_complete(ws)


def read_sample_sha256(ws: Path) -> str | None:
    """Sample sha256 from task_spec.yaml (best-effort; not a hard requirement)."""
    tspec = ws / "task_spec.yaml"
    if not tspec.exists():
        return None
    for line in tspec.read_text(encoding="utf-8", errors="replace").splitlines():
        if "sha256" in line.lower() and ":" in line:
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


# ---------- main ----------

def run(ws: Path) -> tuple[int, dict]:
    # #356 W4: workspace .env fallback — real environment wins, then <ws>/.env.
    # Module-level VM_HOST/GHIDRA_DEFAULT re-bound here (tests monkeypatch
    # them directly, so the lookup stays attribute-based).
    dotenv = load_dotenv(ws)
    global VM_HOST, GHIDRA_DEFAULT, VM_PORTS  # noqa: PLW0603 — rebind per-run
    if not os.environ.get("KUNGLAO_VM_HOST") and dotenv.get("KUNGLAO_VM_HOST"):
        VM_HOST = dotenv["KUNGLAO_VM_HOST"]
    if not os.environ.get("GHIDRA_HOME") and dotenv.get("GHIDRA_HOME"):
        _home = dotenv["GHIDRA_HOME"]
        GHIDRA_DEFAULT = Path(_home) / "support" / "analyzeHeadless.bat"
    # #362: reachability probe ports derive from env/.env (toolchain parity)
    VM_PORTS = resolve_ports(ws)
    checks = {
        "init_complete": check_init_complete(ws),
        "agent_teams_flag": check_flag(),
        "vm_reachability": check_vm(),
        "ghidra": check_ghidra(),
        "hooks_deployed": check_hooks(ws),
        "venv_sample": check_venv_sample(ws, read_sample_sha256(ws)),
    }
    report = {
        "ts": utc_now(),
        "workspace": str(ws.resolve()),
        "checks": {name: {"status": "PASS" if ok else "FAIL", "detail": msg}
                   for name, (ok, msg) in checks.items()},
        "overall": "PASS" if all(ok for ok, _ in checks.values()) else "FAIL",
    }
    out = ws / "runs" / ".env-check.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        print(f"WARN: cannot write {out}: {exc}", file=sys.stderr)
    for name, (ok, msg) in checks.items():
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {msg}")
    print(f"OVERALL: {report['overall']}  (snapshot: {out})")
    return 0 if report["overall"] == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="kunglao-agent environment-init checklist")
    ap.add_argument("workspace", nargs="?", default=".",
                    help="workspace root (default: cwd)")
    args = ap.parse_args()
    return run(Path(args.workspace))


if __name__ == "__main__":
    sys.exit(main())
