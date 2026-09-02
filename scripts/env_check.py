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
  3. Ghidra            — analyzeHeadless(.bat) exists (path from GHIDRA_HOME env;
                         platform-correct name, #409; unset = FAIL with guidance)
  4. Hook deployment   — kunglao hooks registered in EITHER project-level target:
                         <ws>/.claude/settings.json (the #258 --wire-up target)
                         OR <ws-parent>/.claude/settings.json (the #410
                         external_kicker D2 target). TRI-STATE: PASS (all
                         registry hooks in either target) / WARN (no target
                         wired — per-workspace optional, static analysis
                         proceeds) / FAIL (partial deployment — some registry
                         hooks dropped, the #258/#372 silent-drop class).
                         Deployment targets resolve from the wire_up_settings
                         registry (hook_deployment_targets) — never a mirror.
  5. venv + sample     — SKILL-root venv python exists w/ cryptography+yaml
                         (#409: uv run --project <skill_root> is authoritative,
                         not ws/.venv); sample sha256
  6. python_version   — running interpreter matches the 3.11 pin (.python-version,
                         #758); drift is WARN-only (CI pins its own interpreter)

#757 type/channel shaping: rows 2 (vm_reachability) and 3 (ghidra/decompiler)
are CONDITIONAL on workspace context —
  - windows/linux: vm row per KUNGLAO_CHANNEL backend (vmr legacy sockets |
    ssh/docker/adb reuse toolchain probes | local static-only FAIL; mcp -> no
    row), ghidra stays the analyzeHeadless face;
  - android: no vm row (NEVER_CHECKS, #455); ghidra row becomes jadx/baksmali
    primary + native-.so-conditional decompiler requirement (_probe_native_so,
    #756);
  - web: no vm row and NO ghidra row ("decompiler trials meaningless for
    web", #728 design D5); the dynamic surface is MCP/browser (mcp_registered
    row, #757 T2).
KUNGLAO_VM_HOST is only read on the vmr branch and as ssh's remote host name
(user ruling 2026-08-27: 只适用于 windows 的 VM 租约语义).

FAIL grading (gate logic lives in hooks/env_check_gate.py):
  - flag check is HARD — a polluted session must not dispatch at all
  - VM/Ghidra/hook FAIL are recoverable (static analysis can proceed) — gate
    injects guidance instead of aborting
  - hook WARN (unwired) is NOT a failure — hooks are per-workspace optional
    (#410); the report says WARN and overall stays PASS unless another check
    FAILs
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="env_check", action="verify",
                       detail="module wired")
except NameError:
    pass

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import init_state  # noqa: E402  # F6 (#304 review): shared init-completeness predicate
import wire_up_settings  # noqa: E402  # #372: hook registry single source
# #536: template version stamp verify (init writes, env_check verifies —
# same shape as state_hash; hard row in the checklist below).
import template_version  # noqa: E402
# #409: platform-correct analyzeHeadless name + venv python location.
import platform_paths  # noqa: E402
# #757 T1: channel probes delegate to the toolchain implementations rather
# than being rewritten here (single source of probe semantics, #698 D4).
import toolchain as tc  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/ skill root
FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
TRUTHY_VALUES = ("1", "true", "yes", "on")  # #276: truthy = FAIL; 0/false/off/empty = PASS

# #758 G1a/G1b: the repo pins its runtime via .python-version (=3.11, the
# series CI exercises through UV_PYTHON=python3.11). pyproject's
# requires-python floor stays >=3.10 (tomli-backfill contract,
# tests/test_python_floor.py) — the pin is the DEFAULT interpreter, the
# floor is the supported INSTALL range; they answer different questions.
PINNED_PYTHON = (3, 11)
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
GHIDRA_DEFAULT = platform_paths.analyze_headless(_ghidra_home) if _ghidra_home else None


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


from harness_common import utc_now_z as utc_now  # #863 Family F: single source (was a local def)


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
                    capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
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


# ---------- #757 T1: type/channel-aware check bodies ----------

def check_vm_channel(ctx: dict) -> tuple[str, str] | None:
    """vm_reachability rewritten channel-aware (#757 T1/F6).

    - vmr      : the legacy dual-socket semantics verbatim (KUNGLAO_VM_HOST +
                 TCP shell/frida) — #698 byte-parity.
    - ssh      : delegates to toolchain._vm_probe_ssh (BatchMode capability;
                 KUNGLAO_VM_HOST is the remote HOST NAME per D4 — F6 ruling
                 narrows the "VM lease" reading, not ssh's host argument).
    - docker   : toolchain._vm_probe_docker — `docker version`; docker reads
                 NO KUNGLAO_VM_HOST ("no KUNGLAO_VM_HOST required", #698 D4).
    - adb      : toolchain._vm_probe_adb (adb devices + frida liveness).
    - local    : FAIL with fixed static-only detail; zero probes.
    - mcp      : row NOT APPLICABLE -> returns None (web never reaches this
                 function anyway; mcp carries no command control plane).

    Probe exceptions fail-open to a FAIL detail (a crashed probe is an
    unavailable probe), never a raised error out of Phase 0.
    """
    channel = ctx.get("channel", "")
    if channel == "mcp":
        return None
    if channel == "local":
        return ("FAIL",
                "local static-only channel — dynamic analysis unavailable "
                "here (static analysis proceeds); set KUNGLAO_CHANNEL or "
                "run /kunglao-agent:upgrade for infra-backed channels")
    if channel == "vmr":
        ok, msg = check_vm()
        return ("PASS" if ok else "FAIL"), msg

    # remote backends reuse the toolchain probes — sync its import-time port
    # globals to THIS run's env+​.env resolution first (toolchain parses
    # os.environ only, at import).
    tc.VM_SHELL_PORT, tc.FRIDA_PORT = VM_PORTS[0], VM_PORTS[1]
    host = VM_HOST  # ssh backend's remote host name; docker/adb ignore it
    try:
        if channel == "ssh":
            if not host:
                return ("FAIL",
                        "KUNGLAO_VM_HOST unset (ssh backend needs the remote "
                        "host name) — dynamic channel unverified")
            ok, pass_detail, err, _tier = tc._vm_probe_ssh(host)
        elif channel == "docker":
            ok, pass_detail, err, _tier = tc._vm_probe_docker()
        elif channel == "adb":
            ok, pass_detail, err, _tier = tc._vm_probe_adb(host or None)
        else:
            return ("FAIL",
                    f"unknown channel {channel!r} after normalization — "
                    "dynamic channel unverified")
    except Exception as exc:  # noqa: BLE001 — crashed probe == unavailable
        return ("FAIL",
                f"dynamic channel probe crashed via {channel} backend: {exc}")
    if ok:
        return "PASS", (pass_detail
                        or f"dynamic channel {channel} reachable")
    return ("FAIL",
            f"dynamic channel failed via {channel} backend: {err}")


def _mcp_decompiler_supply(ws: Path) -> bool:
    """MCP-first decompiler supply face (#407 口径): ghidra OR ida-pro-vm in
    any registration surface. Fail-open on config read errors."""
    try:
        import mcp_probe
        registered = mcp_probe.registered_names(mcp_probe.claude_json_path(), ws)
        return "ghidra" in registered or "ida-pro-vm" in registered
    except Exception:  # noqa: BLE001 — supply info must never crash Phase 0
        return False


def check_mcp_registered(ws: Path, project_type: str | None) -> tuple[str, str]:
    """MCP registration row (#757 T2 / issue F2) — mcp_probe 口径.

    Three registration surfaces via mcp_probe.registered_names (user-level
    ~/.claude.json global + project-scoped, workspace <ws>/.mcp.json;
    KUNGLAO_CLAUDE_JSON injects the user surface for tests):

    - web           : camoufox-reverse expected — the ONLY manifest member for
                      labs (#728). Missing -> FAIL (+ register command; T3
                      grades it degraded, never blocking).
    - android       : NO hard MCP expectation -> PASS with info (gitnexus is
                      verified by the toolchain face).
    - windows/linux : ghidra/ida-pro-vm either registered -> WARN "capability
                      unverified" (#474 same口径: a registry read cannot reach
                      into the MCP session; tools verify post-connect).
                      Neither -> FAIL naming Ghidra install / ida-pro-vm MCP.
    """
    ptype = project_type if project_type in init_state.VALID_TYPES else "windows"
    try:
        import mcp_probe
        found = mcp_probe.registered_names(mcp_probe.claude_json_path(), ws)
    except Exception as exc:  # noqa: BLE001 — registry unreadable ≠ crash
        return ("FAIL", f"MCP registry probe failed ({exc}) — supply unverified")
    if ptype == "web":
        if "camoufox-reverse" in found:
            return ("PASS",
                    "camoufox-reverse registered (registry read; tools verify "
                    "at session connect)")
        return ("FAIL",
                "camoufox-reverse not registered — browser JS RE supply "
                "degraded. Fix: claude mcp add camoufox-reverse -- "
                "python -m camoufox_reverse_mcp")
    if ptype == "android":
        registered = ", ".join(sorted(found)[:8]) or "none"
        return ("PASS",
                f"no hard MCP requirement for android (gitnexus verified on "
                f"the toolchain face); registered: {registered}")
    desktop = sorted(n for n in ("ghidra", "ida-pro-vm") if n in found)
    if desktop:
        return ("WARN",
                f"{', '.join(desktop)} registered — capability unverified "
                "(#474口径: registry-only; tools verify post-connect)")
    return ("FAIL",
            "neither ghidra nor ida-pro-vm MCP registered — decompiler supply "
            "unverified. Install Ghidra OR IDA, or register the ghidra/"
            "ida-pro-vm MCP (#408 installer)")


def check_ghidra_typed(ws: Path, project_type: str | None) -> tuple[str, str]:
    """ghidra/decompiler row typed per project type (#757 T1).

    - windows/linux : legacy GHIDRA_HOME semantics unchanged.
    - android       : jadx/baksmali paths are the PRIMARY verdict; a native
                      .so sample (toolchain._probe_native_so — the #756
                      central-directory version) additionally requires SOME
                      decompiler supply (analyzeHeadless | idat64 | MCP
                      ghidra/ida-pro-vm). Pure-DEX stays PASS.
    - web           : not applicable — callers omit the row entirely
                      ("decompiler trials meaningless for web", #728 D5);
                      defensively handled as PASS-info here.
    """
    if project_type == "web":
        return ("PASS", "ghidra n/a for web (browser dynamic surface)")
    if project_type in ("windows", "linux", "macos"):
        # macos (#760): Mach-O decompiler expectation rides the same legacy
        # GHIDRA_HOME semantics; a FAIL stays DEGRADED (non-blocking, T3).
        ok, msg = check_ghidra()
        return ("PASS" if ok else "FAIL"), msg

    jadx = shutil.which("jadx")
    baksmali = shutil.which("baksmali")
    present = [n for n, p in (("jadx", jadx), ("baksmali", baksmali)) if p]
    native = tc._probe_native_so(ws)
    ida = shutil.which("idat64")
    supply_items = [
        face for face in (
            f"analyzeHeadless at {GHIDRA_DEFAULT}" if GHIDRA_DEFAULT and GHIDRA_DEFAULT.exists() else "",
            f"idat64 at {ida}" if ida else "",
            "MCP ghidra/ida-pro-vm" if _mcp_decompiler_supply(ws) else "",
        ) if face
    ]
    has_supply = bool(supply_items)
    supply_face = ("decompiler supply: " + "; ".join(supply_items)) \
        if supply_items else "decompiler supply: none"
    if not present:
        return ("FAIL",
                f"jadx/baksmali not found in PATH — android static verdict "
                f"degraded. ({supply_face})")
    loci = "; ".join(f"{n} at {p}" for n, p in
                     (("jadx", jadx), ("baksmali", baksmali)) if p)
    if native and not has_supply:
        return ("FAIL",
                f"{loci}. Sample has native .so — decompiler REQUIRED for "
                f"native code ({supply_face})")
    detail = loci
    if native:
        detail += f". Native .so detected — {supply_face}"
    return "PASS", detail


def check_hooks(ws: Path) -> tuple[str, str]:
    """kunglao hooks registered in a PROJECT-level settings.json — TRI-STATE.

    #410: hooks may live in EITHER project-level target — <ws>/.claude/
    settings.json (the #258/#269 --wire-up deployment target) OR the
    workspace-parent <ws-parent>/.claude/settings.json (the external_kicker
    D2 read/write target). Pre-#410 only the ws-level file was scanned, so a
    parent-wired workspace was misreported as 'hooks missing' (FAIL) with
    'leave unwired' guidance — a self-contradiction.

    Returns (status, detail) with status in PASS|WARN|FAIL:
      - PASS: every registry hook is present in one of the two targets.
      - WARN: no target is wired (neither file exists, or neither carries any
        registry hook). Hooks are per-workspace OPTIONAL (#410) — static
        analysis proceeds; the report records the --wire-up guidance but
        never FAILs.
      - FAIL: a PARTIAL deployment — a target file exists and carries SOME
        registry hook but is missing others. A dropped hook inside a wired
        set is the #258/#372 silent-drop class (a settings rewrite that
        silently dropped hooks), NOT 'unwired' — the FAIL stays loud.

    #269: the user-global ~/.claude/settings.json is NOT a deployment target
    (checked by hooks_selfcheck, warning-only) and can never satisfy this
    check. #372: Stop is scanned too — completion_gate.py is a Stop hook; a
    Pre/Post-only scan can never verify it. Targets derive from the
    wire_up_settings registry (hook_deployment_targets) — never a mirror.
    """
    settings_paths = wire_up_settings.hook_deployment_targets(ws)
    found: list[str] = []
    shape_problems: list[str] = []
    for sp in settings_paths:
        if not sp.exists():
            continue
        s = _load_json(sp)
        # #810: shape contract — pseudo-event keys are the bug shape that
        # made this very checker blind; a violated shape is a loud FAIL.
        shape_problems.extend(
            f"{sp}: {line}" for line in
            wire_up_settings.registration_shape_issues(s))
        cmds = []
        for event in ("PreToolUse", "PostToolUse", "Stop"):
            for entry in s.get("hooks", {}).get(event, []) or []:
                for h in entry.get("hooks", []) or []:
                    cmds.append(str(h.get("command", "")))
        found.extend(h for h in HOOK_FILES if any(h in c for c in cmds))
    present = set(found)
    if shape_problems:
        return ("FAIL",
                "registration shape contract violated (#810): "
                + "; ".join(shape_problems)
                + " — deployed hooks never fire in this shape; re-run "
                "python <skill>/scripts/hook_activation.py <ws> --deploy-local")
    if present == set(HOOK_FILES):
        # activation state (soft — 30-min TTL expected during a live loop)
        state = _load_json(ws / ".hook_state.json")
        active = state.get("active_hooks", []) or []
        act = f" — {len(active)} active hook(s)" if active else " (not activated — hooks sleep)"
        return "PASS", f"{len(HOOK_FILES)} hooks registered{act}"
    if not present:
        # no target wired at all — hooks are per-workspace optional (#410)
        return ("WARN",
                "no kunglao hooks wired in either project target "
                "(<ws>/.claude/settings.json or <ws-parent>/.claude/settings.json) — "
                "per-workspace optional; run python <skill>/scripts/hook_activation.py "
                "<ws> --wire-up to deploy")
    missing = sorted(set(HOOK_FILES) - present)
    return ("FAIL",
            f"hooks missing from settings.json: {', '.join(missing)}. "
            f"Fix: python <skill>/scripts/hook_activation.py <ws> --wire-up")


def check_venv_sample(ws: Path, sample_sha256: str | None) -> tuple[bool, str]:
    """SKILL-root venv python with cryptography+yaml; sample sha256 vs
    task_spec if present.

    #409: the authoritative interpreter is the SKILL-root venv (uv run
    --project <skill_root>) resolved by sys.platform (Scripts/python.exe |
    bin/python) — NOT the workspace .venv (which may not exist; the old
    ws/.venv/Scripts/python.exe constant always FAILed on macOS)."""
    problems = []
    venv_py = platform_paths.venv_python(SKILL_DIR / ".venv")
    if venv_py.exists():
        try:
            r = subprocess.run([str(venv_py), "-c", "import cryptography, yaml"],
                               capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                problems.append(f"venv missing deps (cryptography/yaml): {r.stderr.strip()[:80]}")
        except Exception as exc:
            problems.append(f"venv probe failed: {exc}")
    else:
        problems.append(f"no venv python at {venv_py} (skill root: {SKILL_DIR})")
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


def check_python_version() -> tuple[str, str]:
    """#758 G1b: interpreter-version drift — ADVISORY (WARN), never FAIL.

    Local interpreters drift off the repo pin (.python-version); CI is the
    blocking authority (UV_PYTHON=python3.11), so a drifted local run must
    not abort a workspace checklist — it gets a loud WARN row instead
    (same WARN-does-not-fail-overall semantics as hooks_deployed/#410).
    """
    vi = tuple(sys.version_info[:3])
    got = ".".join(str(x) for x in vi)
    if vi[:2] == PINNED_PYTHON:
        return ("PASS",
                f"python {got} matches the "
                f"{PINNED_PYTHON[0]}.{PINNED_PYTHON[1]}.x pin")
    return ("WARN",
            f"python {got} is not the pinned "
            f"{PINNED_PYTHON[0]}.{PINNED_PYTHON[1]}.x (.python-version / CI "
            f"UV_PYTHON) — advisory drift, CI stays authoritative")


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


def check_template_version(ws: Path) -> tuple[str, str]:
    """#536: three-carrier template version stamp, TRI-STATE.

    PASS  — every present carrier carries the active skill version.
    WARN  — one or more carriers lack the stamp line entirely (a pre-#536
            legacy workspace; init never stamped it). Not a hard failure:
            the workspace predates the stamp, not diverged from it. The
            fix is one re-init away.
    FAIL  — a carrier carries a DIFFERENT version (true drift: stamped at
            0.1.x, running skill 0.2.y — semantics may have changed).
    """
    try:
        faults = template_version.verify_stamps(ws)
    except RuntimeError as exc:  # no skill version anywhere — release defect
        return "FAIL", f"skill version unreadable: {exc}"
    missing = sorted(k for k, v in faults.items() if v == "missing")
    mismatched = sorted(k for k, v in faults.items()
                        if v.startswith("mismatch:"))
    if mismatched:
        return "FAIL", (f"stamp mismatch on {', '.join(mismatched)} "
                        f"({faults[mismatched[0]]} vs expected "
                        f"{template_version.read_skill_version()}) — re-run "
                        f"kunglao-init to align the workspace template")
    if missing:
        return "WARN", (f"stamp missing on {', '.join(missing)} — "
                        "workspace predates the template version stamp "
                        "(re-run kunglao-init to add it)")
    return "PASS", f"stamped {template_version.read_skill_version()} on all carriers"


# ---------- #757: workspace context (type x channel) ----------

# #757/T5: channel values (#698 enum + mcp). Kept as a literal tuple —
# init_channel_default.ALL_CHANNELS is re-exported by value on import and a
# lazy cross-module import inside run() would hide drift from the pins.
CHANNEL_VALUES = ("vmr", "ssh", "docker", "adb", "local", "mcp")


def _normalize_channel(raw: str | None) -> tuple[str, str]:
    """(#698 D2 parity) strip/lower; unknown non-empty -> vmr fallback with
    a note naming the offending value; unset/blank -> ("", "")."""
    if raw is None:
        return "", ""
    stripped = raw.strip().lower()
    if not stripped:
        return "", ""
    if stripped in CHANNEL_VALUES:
        return stripped, ""
    return "vmr", f"unknown KUNGLAO_CHANNEL={stripped!r} — falling back to vmr"


def read_project_type_context(ws: Path) -> str | None:
    """project_type for checklist shaping: .kunglao-init.json marker first
    (#625 primary truth), then analysis_state.txt (init_state.read_project_type).
    Invalid/absent -> None (untyped workspaces get the legacy global face)."""
    marker = _load_json(Path(ws) / init_state.STATE_FILE)
    ptype = marker.get("project_type")
    if isinstance(ptype, str) and ptype in init_state.VALID_TYPES:
        return ptype
    return init_state.read_project_type(ws)


def _explicit_channel_setting(ws: Path) -> str | None:
    """Live explicit KUNGLAO_CHANNEL: os.environ first, <ws>/.env fills gaps.
    Separate from load_dotenv's merged view because that view only overlays
    environ keys already present in the .env file."""
    val = os.environ.get("KUNGLAO_CHANNEL")
    if val is None:
        val = load_dotenv(ws).get("KUNGLAO_CHANNEL")
    return val


def _channel_from_init_report(ws: Path) -> str | None:
    """#727 channel block in runs/.init-report.json (top-level `channel.selected`)."""
    report = _load_json(Path(ws) / "runs" / ".init-report.json")
    block = report.get("channel")
    if isinstance(block, dict):
        selected = block.get("selected")
        if isinstance(selected, str) and selected.strip():
            return selected
    return None


def _channel_from_state_file(ws: Path) -> str | None:
    """`KUNGLAO_CHANNEL=<value>` line in analysis_state.txt (#728 web-default
    writer's carrier)."""
    state = Path(ws) / "analysis_state.txt"
    if not state.exists():
        return None
    for line in state.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("KUNGLAO_CHANNEL="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    return None


def resolve_runtime_channel(ws: Path):
    """Indirection over init_channel_default.resolve_init_channel (probe-only,
    READ-ONLY). Injectable so tests never spawn real ssh/docker/adb probes.

    Fail-open contract: resolution errors degrade to the local static-only
    decision — this must never be the code path that breaks Phase 0."""
    try:
        import init_channel_default
        return init_channel_default.resolve_init_channel(ws)
    except Exception as exc:  # noqa: BLE001 — derivation is advisory
        import init_channel_default as _icd
        return _icd.ChannelDecision(
            selected="local", defaulted_to_local=True, probes={},
            warn_reason=f"resolver unavailable: {exc}")


def read_channel_record(ws: Path) -> tuple[str | None, str]:
    """Channel record chain (first hit wins): live env/.env setting ->
    .init-report.json channel block -> analysis_state.txt line. Returns
    (raw_value_or_None, source_label)."""
    raw = _explicit_channel_setting(ws)
    if raw is not None and raw.strip():
        source = "env" if os.environ.get("KUNGLAO_CHANNEL") else ".env"
        return raw, source
    raw = _channel_from_init_report(ws)
    if raw is not None:
        return raw, ".init-report.json"
    raw = _channel_from_state_file(ws)
    if raw is not None:
        return raw, "analysis_state.txt"
    return None, ""


def _workspace_context(ws: Path) -> dict:
    """Type x channel context the checklist branches on (#757 T1/T4).

    - project_type via #625 marker, analysis_state fallback.
    - channel: recorded chain (env/.env wins — 变量跟通道走), then runtime
      derivation. Derivation NEVER writes disk: persisting the resolved
      channel is #755's upgrade item; the report marks it derived.
    - web forces the mcp face (user ruling 2026-08-27: web needs NO command
      control channel — the dynamic surface is MCP/browser). Any recorded
      command channel is named in channel_note as ignored-for-web.
    """
    ptype = read_project_type_context(ws)

    if ptype == "web":
        rec_raw, rec_src = read_channel_record(ws)
        _rec_ch, note = _normalize_channel(rec_raw)
        ignored = f"recorded command channel '{rec_raw}' ignored-for-web ({rec_src})" \
            if rec_raw else ""
        note = " ".join(x for x in (note, ignored) if x)
        return {
            "project_type": ptype,
            "channel": "mcp",
            "channel_source": "web-type (mcp normal-state, #757 ruling)",
            "channel_note": note,
        }

    raw, source = read_channel_record(ws)
    if raw is not None:
        channel, note = _normalize_channel(raw)
        return {"project_type": ptype, "channel": channel,
                "channel_source": source, "channel_note": note}

    dec = resolve_runtime_channel(ws)
    channel, dnote = _normalize_channel(dec.selected)
    suffix = " (defaulted)" if getattr(dec, "defaulted_to_local", False) else ""
    note = "; ".join(x for x in (dnote, getattr(dec, "warn_reason", "") or "") if x)
    return {
        "project_type": ptype,
        "channel": channel,
        "channel_source": f"derived{suffix} — run /kunglao-agent:upgrade to persist",
        "channel_note": note,
    }


# ---------- main ----------

def _norm(ok: bool, msg: str) -> tuple[str, str]:
    """Normalize a binary (ok, msg) check to the (status, msg) tri-state
    shape — PASS|FAIL, never WARN (only check_hooks produces WARN, #410)."""
    return ("PASS" if ok else "FAIL"), msg


# #757 T3: mechanical FAIL grading. BLOCKING rows keep the legacy overall=FAIL
# semantics; DEGRADED rows report FAIL but never flip overall/exit — they ride
# into the loop flagged ("T3-restricted: ..." detail + top-level degraded list).
BLOCKING_CHECKS = frozenset({
    "init_complete", "agent_teams_flag", "hooks_deployed",
    "venv_sample", "template_version",
})
DEGRADED_CHECKS = frozenset({"vm_reachability", "ghidra", "mcp_registered"})
GATE_REPORT_TTL_SECONDS = 600  # mirrors hooks/env_check_gate.py third check


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
        GHIDRA_DEFAULT = platform_paths.analyze_headless(_home)
    # #362: reachability probe ports derive from env/.env (toolchain parity)
    VM_PORTS = resolve_ports(ws)
    # #757: workspace context (project_type x channel) shapes the checklist
    ctx = _workspace_context(ws)
    checks = {
        "init_complete": _norm(*check_init_complete(ws)),
        "agent_teams_flag": _norm(*check_flag()),
        "hooks_deployed": check_hooks(ws),  # TRI-STATE: PASS|WARN|FAIL (#410)
        "venv_sample": _norm(*check_venv_sample(ws, read_sample_sha256(ws))),
        # #536: TRI-STATE like hooks — WARN on stamp-less legacy workspace,
        # FAIL on genuine version drift (see check_template_version).
        "template_version": check_template_version(ws),
        # #758 G1b: TRI-STATE like hooks — WARN-only version-drift row.
        "python_version": check_python_version(),
    }
    # #757 T1: type/channel conditional rows.
    ptype = ctx.get("project_type")
    if ptype == "web":
        # no vm row, no ghidra row ("decompiler trials meaningless for web",
        # #728 design D5); the dynamic surface is the browser/MCP.
        pass
    elif ptype == "android":
        checks["ghidra"] = check_ghidra_typed(ws, ptype)
        # no vm_reachability row (android dynamics are ADB/device-side,
        # NEVER_CHECKS precedent #455)
    else:
        vm_row = check_vm_channel(ctx)  # None when channel=mcp
        if vm_row is not None:
            # already tri-state shaped (status, detail) — NO _norm re-wrap:
            # _norm treats a truthy status string as boolean success (#757)
            checks["vm_reachability"] = vm_row
        checks["ghidra"] = check_ghidra_typed(ws, ptype)
    # #757 T2: MCP registration row for every type (per-type 口径 above)
    checks["mcp_registered"] = check_mcp_registered(ws, ptype)
    # #757 T3: mechanical grading — every row gets `blocking`; degradable FAILs
    # get the "T3-restricted:" detail prefix and never flip overall.
    graded: dict[str, dict] = {}
    degraded: list[str] = []
    for name, (status, detail) in checks.items():
        blocking = name not in DEGRADED_CHECKS
        if status == "FAIL" and not blocking:
            detail = f"T3-restricted: {detail}"
            degraded.append(name)
        graded[name] = {"status": status, "detail": detail,
                        "blocking": blocking}
    overall_fail = any(v["status"] == "FAIL" and v["blocking"]
                       for v in graded.values())
    report = {
        "ts": utc_now(),
        "workspace": str(ws.resolve()),
        "context": {k: ctx.get(k) for k in
                    ("project_type", "channel", "channel_source",
                     "channel_note")},
        "checks": graded,
        # #410: WARN is NOT a failure — unwired hooks are per-workspace
        # optional. #757: neither are DEGRADED_CHECKS FAILs — the loop enters
        # flagged (T3-restricted), the gate only polices blocking FAILs.
        "overall": "FAIL" if overall_fail else "PASS",
    }
    if degraded:
        report["degraded"] = degraded
    out = ws / "runs" / ".env-check.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        print(f"WARN: cannot write {out}: {exc}", file=sys.stderr)
    for name, row in graded.items():
        print(f"[{row['status']}] {name}: {row['detail']}")
    if degraded:
        print(f"DEGRADED (T3-restricted, non-blocking): {', '.join(degraded)}")
    print(f"OVERALL: {report['overall']}  (snapshot: {out})")
    return 0 if report["overall"] == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="kunglao-agent environment-init checklist")
    ap.add_argument("workspace", nargs="?", default=".",
                    help="workspace root (default: cwd)")
    args = ap.parse_args()
    return run(Path(args.workspace))


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
