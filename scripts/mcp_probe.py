#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_probe.py — MCP supply probe (#316).

Single source of truth for the RE MCP manifest: which MCP servers
the analysis pipeline needs, per project type, with tier (HARD blocks / WARN
informational) and a `claude mcp add ...` registration command per item.

Probes two registration surfaces (issue #316 task 1):
  1. user-level ~/.claude.json — global `mcpServers` + project-scoped
     `projects.<path>.mcpServers`
  2. workspace <ws>/.mcp.json — `mcpServers`
Name matching is case-insensitive (Claude Code normalizes server names).

Also builds the workspace .mcp.json scaffold content (task 2) consumed by
kunglao-init: a strictly valid JSON document (comments as `_comment` keys —
`//` comments are NOT portable across .mcp.json parsers) whose `mcpServers`
map is empty (a scaffold must never shadow a working user-level registration
with a broken command) and whose `mcp_manifest` carries the per-type list
with purpose/source/register-command-template per item.

Environment-side inventory (#515 acceptance 1): `--mcp-inventory` is a
distinct ENUMERATION face (vs the check faces below) — it lists every
REGISTERED server across the three registration surfaces with the harness
tool prefix `mcp__<server>__*` and the per-type required/optional status
annotated from MANIFEST (tier null = environment-extra). Read-only: reads
the JSON config files only, never connects, never spawns, zero network.
Secret hygiene: emits names/surfaces/tiers only — never command/args/env
values (an MCP config may carry API keys in `env`; the inventory must be
pasteable/committable). Consumed by `tools/ext-scan.py --with-mcp` to
derive describe-only ext catalog entries.

CLI: mcp_probe.py <workspace> [--type windows|linux|android|web] [--json]
                     [--reproduce] [--claude-json PATH]
                     [--mcp-inventory]
Exit codes (same contract as toolchain.py #304): 0 = all present,
1 = any HARD missing, 2 = only WARN missing. Inventory mode: 0 (it is a
listing, not a verdict) and is mutually exclusive with --json/--reproduce.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# NOTE: UTF-8 stdout unification is deferred to main() (NOT module level).
# kunglao-init.py imports this module for the .mcp.json scaffold — a
# module-level sys.stdout.reconfigure would silently flip the IMPORTER's
# stdout encoding (observed: test_kunglao_init subprocess decode breaks).

VALID_TYPES = ("windows", "linux", "android", "web")
ALL_TYPES = VALID_TYPES
# #728: the desktop triple, explicit. "web" (labs) deliberately carries NO
# desktop RE entry — web's sole manifest member is camoufox-reverse (WARN),
# so a browser workspace can never FAIL-HARD on binary-RE supply.
DESKTOP_TYPES = ("windows", "linux", "android")


@dataclass(frozen=True)
class MCPItem:
    """One manifest entry: a required/optional MCP server."""
    name: str                 # canonical lowercase server name
    tier: str                 # "HARD" (blocks analysis) | "WARN" (informational)
    purpose: str              # what the server is used for
    source: str               # where it comes from (package / bridge binary)
    register: str             # registration command template (`claude mcp add ...`)
    types: tuple[str, ...]    # applicable project types


# Per-type required/optional list (issue #316 task 1). Group order is part of the
# scaffold contract — tests/test_mcp_supply.py pins it.
MANIFEST_GROUPS: dict[str, list[str]] = {
    "required_all_types": ["ghidra", "sequential-thinking"],
    "windows_t3": ["x64dbg", "volatility"],
    "optional_ida": ["ida-pro-vm"],
    "android_graph": ["gitnexus"],
    "cti": ["virustotal"],
    # #698: supply-scaffold declaration (install guidance). WARN tier keeps
    # a missing ssh-mcp informational — the channel probe (toolchain.py)
    # never requires MCP liveness; CLI ssh is the fallback control plane.
    "channel_ssh": ["ssh-mcp"],
    # #728: web (labs) project type — sole manifest member camoufox-reverse
    # (WARN). No desktop RE entry: a browser workspace can never FAIL-HARD
    # on binary-RE supply.
    "web_labs": ["camoufox-reverse"],
}

MANIFEST: tuple[MCPItem, ...] = (
    MCPItem(
        name="ghidra", tier="HARD", types=DESKTOP_TYPES,
        purpose="Ghidra decompilation / static analysis",
        source="bridge-mcp-ghidra (stdio bridge)",
        register="claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe",
    ),
    MCPItem(
        name="sequential-thinking", tier="HARD", types=DESKTOP_TYPES,
        purpose="structured reasoning",
        source="@modelcontextprotocol/server-sequential-thinking",
        register="claude mcp add sequential-thinking -- "
                 "npx -y @modelcontextprotocol/server-sequential-thinking",
    ),
    MCPItem(
        name="x64dbg", tier="HARD", types=("windows",),
        purpose="Windows T3 dynamic debugging (VM remote)",
        source="x64dbg-automate-mcp",
        register="claude mcp add x64dbg -- x64dbg-automate-mcp",
    ),
    MCPItem(
        name="volatility", tier="WARN", types=("windows",),
        purpose="memory forensics",
        source="volatility_mcp_server.py",
        register="claude mcp add volatility -- python <path>/volatility_mcp_server.py",
    ),
    MCPItem(
        name="ida-pro-vm", tier="WARN", types=DESKTOP_TYPES,
        purpose="IDA remote analysis (when IDA is chosen)",
        source="IDA MCP (http transport)",
        register="claude mcp add --transport http ida-pro-vm <ida-mcp-url>",
    ),
    MCPItem(
        name="gitnexus", tier="HARD", types=("android",),
        purpose="Android graph building (post-decompile graph)",
        source="gitnexus mcp (npm i -g gitnexus first)",
        register="claude mcp add gitnexus -- gitnexus mcp",
    ),
    # #698 ssh channel execution control plane. STATIC declaration:
    # demanded by no MANIFEST_GROUPS entry (CLI ssh is the fallback
    # probe path); liveness is mcp_probe's own domain, not the channel
    # probe's. Upstream verified 2026-08-26: npm ssh-mcp, TOML
    # profiles, tools run-command/sftp-upload/sftp-download/sessions.
    MCPItem(
        name="ssh-mcp", tier="WARN", types=("windows", "linux"),
        purpose="SSH execution control plane (KUNGLAO_CHANNEL=ssh dynamics)",
        source="ssh-mcp (npm i -g ssh-mcp; TOML profiles under ~/.config/ssh-mcp)",
        register="claude mcp add ssh-mcp -- ssh-mcp",
    ),
    MCPItem(
        name="virustotal", tier="WARN", types=DESKTOP_TYPES,
        purpose="CTI intelligence (family-attribution hypothesis)",
        source="@burtthecoder/mcp-virustotal (needs VT_API_KEY)",
        register="claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal",
    ),
    # #728 web (labs): browser JS reverse engineering supply. Upstream-
    # verified registration (README 2026-08-26): python module entrypoint,
    # optional flags --proxy/--geoip/--humanize stay out of the register
    # template (placeholder-free rule). WARN — labs never FAIL-HARD.
    MCPItem(
        name="camoufox-reverse", tier="WARN", types=("web",),
        purpose="browser JS reverse engineering (anti-detection Firefox: "
                "hooks/trace/network capture; optional --proxy/--geoip/"
                "--humanize flags)",
        source="camoufox-reverse-mcp (git clone + pip install -e .)",
        register="claude mcp add camoufox-reverse -- "
                 "python -m camoufox_reverse_mcp",
    ),
)

_BY_NAME = {i.name: i for i in MANIFEST}


@dataclass
class MCPCheck:
    """One probe result."""
    name: str
    status: str   # PASS | FAIL | WARN
    tier: str     # HARD | WARN
    detail: str
    fix: str | None = None


# ---------- registration surface probing ----------

def _load_json(path: Path) -> dict:
    """Fail-open JSON read (missing/corrupt → {}), same policy as env_check.py."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def claude_json_path() -> Path:
    """User-level ~/.claude.json location (KUNGLAO_CLAUDE_JSON override for tests)."""
    override = os.environ.get("KUNGLAO_CLAUDE_JSON")
    if override:
        return Path(override)
    return Path(os.path.expanduser("~")) / ".claude.json"


def registered_names(claude_json: Path | None, ws: Path) -> dict[str, list[str]]:
    """Registered MCP server names (lowercased) → source labels.

    Sources: user-global ~/.claude.json mcpServers, project-scoped
    projects.*.mcpServers, workspace .mcp.json mcpServers. Case-insensitive.
    """
    found: dict[str, list[str]] = {}
    if claude_json is not None:
        data = _load_json(claude_json)
        for name in (data.get("mcpServers") or {}):
            found.setdefault(name.lower(), []).append("user-global")
        for proj, cfg in (data.get("projects") or {}).items():
            for name in ((cfg or {}).get("mcpServers") or {}):
                found.setdefault(name.lower(), []).append(f"user-project:{proj}")
    ws_mcp = _load_json(ws / ".mcp.json")
    for name in (ws_mcp.get("mcpServers") or {}):
        found.setdefault(name.lower(), []).append("workspace")
    return found


# ---------- check ----------

# #407: decompiler supply is MCP-first — a registered `ida-pro-vm` satisfies
# the HARD `ghidra` item (the decompiler need is met by IDA) and promotes
# ida-pro-vm to HARD when it is the sole decompiler provider (ghidra absent);
# otherwise ida-pro-vm keeps its WARN default.


def read_project_type(ws: Path) -> str | None:
    """Read project_type from analysis_state.txt (same contract as toolchain.py)."""
    state = ws / "analysis_state.txt"
    if not state.exists():
        return None
    for line in state.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("project_type="):
            return line.split("=", 1)[1].strip()
    return None


def check_mcp(ws: Path, project_type: str,
              claude_json: Path | None = None) -> list[MCPCheck]:
    """Probe the manifest items applicable to project_type.

    #407: decompiler supply is MCP-first — a registered `ida-pro-vm` satisfies
    the HARD `ghidra` item (detail names the provider), and `ida-pro-vm` is
    promoted to HARD when it is the sole decompiler provider (ghidra absent).
    """
    if project_type not in VALID_TYPES:
        raise ValueError(
            f"Invalid project type: {project_type!r}. "
            f"Must be one of: {', '.join(VALID_TYPES)}. "
            f"Set --type or add project_type=<type> to analysis_state.txt."
        )
    if claude_json is None:
        claude_json = claude_json_path()
    found = registered_names(claude_json, ws)
    ghidra_registered = "ghidra" in found
    ida_pro_vm_registered = "ida-pro-vm" in found
    checks: list[MCPCheck] = []
    for item in MANIFEST:
        if project_type not in item.types:
            continue
        sources = found.get(item.name)
        tier = item.tier
        if item.name == "ida-pro-vm" and not ghidra_registered:
            # #407: ida-pro-vm is the sole decompiler provider -> HARD.
            tier = "HARD"
        if item.name == "ghidra" and not sources and ida_pro_vm_registered:
            # #407: the HARD ghidra supply item is satisfied by the IDA MCP
            # decompiler provider — an operator with only ida-pro-vm must not
            # be reported "ghidra missing".
            checks.append(MCPCheck(
                name=item.name, status="PASS", tier=item.tier,
                detail="satisfied via ida-pro-vm (MCP decompiler provider)",
            ))
            continue
        if sources:
            checks.append(MCPCheck(
                name=item.name, status="PASS", tier=tier,
                detail=f"registered ({', '.join(sources)})",
            ))
            continue
        checks.append(MCPCheck(
            name=item.name,
            status="FAIL" if tier == "HARD" else "WARN",
            tier=tier,
            detail=f"not registered in ~/.claude.json or workspace .mcp.json "
                   f"({item.purpose})",
            fix=item.register,
        ))
    return checks


# ---------- environment-side inventory (#515) ----------

INVENTORY_SCHEMA = "mcp-inventory/1"


def mcp_inventory(ws: Path, claude_json: Path | None = None) -> dict:
    """Enumerate REGISTERED servers across all three registration surfaces.

    Distinct from check_mcp (the supply CHECK face): this lists what the
    environment actually HAS — every mcpServers key, manifest members and
    environment-extra alike — annotated with the harness tool prefix
    (`mcp__<server>__*`) and the per-type required/optional status from
    MANIFEST. Names are canonical lowercase (same case-insensitive
    matching semantic as registered_names).

    Secret hygiene: only names/surfaces/tiers are emitted — never the
    command/args/env/url VALUES from the config (they may carry API keys).
    """
    if claude_json is None:
        claude_json = claude_json_path()
    found = registered_names(claude_json, ws)
    servers = []
    for canonical in sorted(found):
        item = _BY_NAME.get(canonical)
        servers.append({
            "name": canonical,
            "prefix": f"mcp__{canonical}__*",
            "sources": list(found[canonical]),
            "in_manifest": item is not None,
            "manifest_tier": item.tier if item is not None else None,
            "required_for_types": list(item.types) if item is not None else [],
        })
    return {
        "schema": INVENTORY_SCHEMA,
        "claude_json": str(claude_json),
        "server_count": len(servers),
        "servers": servers,
    }


# ---------- scaffold (kunglao-init task 2) ----------

def build_scaffold_json() -> dict:
    """Workspace .mcp.json scaffold content — strictly valid JSON.

    `mcpServers` is empty on purpose: a scaffold must not register broken
    placeholder commands that would shadow a working user-level registration.
    `mcp_manifest` carries the per-type list (purpose/source/register template).
    """
    return {
        "_comment": (
            "kunglao MCP supply scaffold (#316). Do not hand-edit the manifest "
            "section — the single source of truth is scripts/mcp_probe.py MANIFEST. "
            "Register each item user-level by running its `register` command, or "
            "put a real entry under mcpServers (project scope overrides user scope). "
            "Check supply: python <skill>/scripts/mcp_probe.py <ws> --type <t>"
        ),
        "mcpServers": {},
        "mcp_manifest": {
            "_comment": (
                "Per-type required/optional MCP list. Kept in sync with "
                "scripts/mcp_probe.py MANIFEST (tests/test_mcp_supply.py pins equality)."
            ),
            **{
                group: [
                    {
                        "name": i.name,
                        "tier": i.tier,
                        "types": list(i.types),
                        "purpose": i.purpose,
                        "source": i.source,
                        "register": i.register,
                    }
                    for i in (_BY_NAME[n] for n in names)
                ]
                for group, names in MANIFEST_GROUPS.items()
            },
        },
    }


# ---------- report formatting ----------

def _overall(checks: list[MCPCheck]) -> str:
    if any(c.status == "FAIL" and c.tier == "HARD" for c in checks):
        return "FAIL"
    if any(c.status == "WARN" for c in checks):
        return "WARN"
    return "PASS"


def exit_code_for(checks: list[MCPCheck]) -> int:
    return {"FAIL": 1, "WARN": 2, "PASS": 0}[_overall(checks)]


def format_human(checks: list[MCPCheck], project_type: str) -> str:
    lines = [f"mcp supply check: type={project_type}"]
    for c in checks:
        lines.append(f"  [{c.status}] [{c.tier}] {c.name}: {c.detail}")
        if c.fix:
            lines.append(f"      fix: {c.fix}")
    lines.append(f"OVERALL: {_overall(checks)}")
    return "\n".join(lines)


def format_json(checks: list[MCPCheck], project_type: str) -> str:
    data = {
        "project_type": project_type,
        "overall": _overall(checks),
        "checks": [
            {"name": c.name, "status": c.status, "tier": c.tier,
             "detail": c.detail, "fix": c.fix}
            for c in checks
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def format_reproduce(checks: list[MCPCheck], project_type: str) -> str:
    parts = [f"type={project_type}", f"overall={_overall(checks)}"]
    parts += [f"{c.name}={c.status}" for c in checks]
    return " ".join(parts)


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    # UTF-8 stdout unification (same pattern as scripts/toolchain.py) — scoped
    # to CLI execution so importing this module never mutates the importer's
    # stdout (kunglao-init.py imports it for the .mcp.json scaffold).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(
        prog="mcp_probe",
        description="MCP supply probe — per-type required/optional MCP servers (#316)",
    )
    parser.add_argument("workspace", help="workspace root path")
    parser.add_argument("--type", choices=VALID_TYPES, default=None,
                        help="project type (default: read from analysis_state.txt)")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    parser.add_argument("--reproduce", action="store_true",
                        help="machine-parseable output for CI")
    parser.add_argument("--claude-json", metavar="PATH", default=None,
                        help="user-level claude.json path (default: ~/.claude.json)")
    parser.add_argument(
        "--mcp-inventory", action="store_true",
        help="enumeration face (#515): list every registered MCP server "
             "(name, mcp__<server>__* prefix, surfaces, manifest tier) as "
             "JSON; always exits 0; mutually exclusive with --json/--reproduce")
    args = parser.parse_args(argv)

    if args.mcp_inventory and (args.json or args.reproduce):
        parser.error("--mcp-inventory is the enumeration face — it cannot "
                     "combine with the check faces (--json/--reproduce)")

    ws = Path(args.workspace).resolve()

    if args.mcp_inventory:
        # Type-agnostic enumeration: no project_type needed (and no
        # check_mcp ValueError path) — the inventory lists the environment,
        # it does not gate on it.
        inv = mcp_inventory(
            ws, claude_json=Path(args.claude_json) if args.claude_json else None)
        print(json.dumps(inv, indent=2, ensure_ascii=False))
        return 0

    project_type = args.type or read_project_type(ws)
    try:
        checks = check_mcp(ws, project_type, claude_json=Path(args.claude_json)
                           if args.claude_json else None)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(format_json(checks, project_type))
    elif args.reproduce:
        print(format_reproduce(checks, project_type))
    else:
        print(format_human(checks, project_type))
    return exit_code_for(checks)


if __name__ == "__main__":
    sys.exit(main())
