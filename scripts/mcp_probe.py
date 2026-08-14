#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_probe.py — MCP supply probe (#316).

单一事实源 (single source of truth) for the RE MCP manifest: which MCP servers
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
with 用途/来源/注册命令模板 per item.

CLI: mcp_probe.py <workspace> [--type windows|linux|android] [--json]
                     [--reproduce] [--claude-json PATH]
Exit codes (same contract as toolchain.py #304): 0 = all present,
1 = any HARD missing, 2 = only WARN missing.
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

VALID_TYPES = ("windows", "linux", "android")
ALL_TYPES = VALID_TYPES


@dataclass(frozen=True)
class MCPItem:
    """One manifest entry: a required/optional MCP server."""
    name: str                 # canonical lowercase server name
    tier: str                 # "HARD" (blocks analysis) | "WARN" (informational)
    purpose: str              # 用途
    source: str               # 来源 (package / bridge binary)
    register: str             # 注册命令模板 (`claude mcp add ...`)
    types: tuple[str, ...]    # applicable project types


# Per-type 必配/可选清单 (issue #316 task 1). Group order is part of the
# scaffold contract — tests/test_mcp_supply.py pins it.
MANIFEST_GROUPS: dict[str, list[str]] = {
    "required_all_types": ["ghidra", "sequential-thinking"],
    "windows_t3": ["x64dbg", "volatility"],
    "optional_ida": ["ida-pro-vm"],
    "android_graph": ["gitnexus"],
    "cti": ["virustotal"],
}

MANIFEST: tuple[MCPItem, ...] = (
    MCPItem(
        name="ghidra", tier="HARD", types=ALL_TYPES,
        purpose="Ghidra 反编译/静态分析",
        source="bridge-mcp-ghidra (stdio 桥接)",
        register="claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe",
    ),
    MCPItem(
        name="sequential-thinking", tier="HARD", types=ALL_TYPES,
        purpose="结构化推理",
        source="@modelcontextprotocol/server-sequential-thinking",
        register="claude mcp add sequential-thinking -- "
                 "npx -y @modelcontextprotocol/server-sequential-thinking",
    ),
    MCPItem(
        name="x64dbg", tier="HARD", types=("windows",),
        purpose="Windows T3 动态调试 (VM 远程)",
        source="x64dbg-automate-mcp",
        register="claude mcp add x64dbg -- x64dbg-automate-mcp",
    ),
    MCPItem(
        name="volatility", tier="WARN", types=("windows",),
        purpose="内存取证 (memory forensics)",
        source="volatility_mcp_server.py",
        register="claude mcp add volatility -- python <path>/volatility_mcp_server.py",
    ),
    MCPItem(
        name="ida-pro-vm", tier="WARN", types=ALL_TYPES,
        purpose="IDA 远程分析 (选 IDA 时)",
        source="IDA MCP (http transport)",
        register="claude mcp add --transport http ida-pro-vm <ida-mcp-url>",
    ),
    MCPItem(
        name="gitnexus", tier="HARD", types=("android",),
        purpose="Android 建图流程 (post-decompile graph)",
        source="gitnexus mcp (先 npm i -g gitnexus)",
        register="claude mcp add gitnexus -- gitnexus mcp",
    ),
    MCPItem(
        name="virustotal", tier="WARN", types=ALL_TYPES,
        purpose="CTI 情报 (家族归属假设)",
        source="@burtthecoder/mcp-virustotal (需 VT_API_KEY)",
        register="claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal",
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
    """Probe the manifest items applicable to project_type."""
    if project_type not in VALID_TYPES:
        raise ValueError(
            f"Invalid project type: {project_type!r}. "
            f"Must be one of: {', '.join(VALID_TYPES)}. "
            f"Set --type or add project_type=<type> to analysis_state.txt."
        )
    if claude_json is None:
        claude_json = claude_json_path()
    found = registered_names(claude_json, ws)
    checks: list[MCPCheck] = []
    for item in MANIFEST:
        if project_type not in item.types:
            continue
        sources = found.get(item.name)
        if sources:
            checks.append(MCPCheck(
                name=item.name, status="PASS", tier=item.tier,
                detail=f"registered ({', '.join(sources)})",
            ))
        else:
            checks.append(MCPCheck(
                name=item.name,
                status="FAIL" if item.tier == "HARD" else "WARN",
                tier=item.tier,
                detail=f"not registered in ~/.claude.json or workspace .mcp.json "
                       f"({item.purpose})",
                fix=item.register,
            ))
    return checks


# ---------- scaffold (kunglao-init task 2) ----------

def build_scaffold_json() -> dict:
    """Workspace .mcp.json scaffold content — strictly valid JSON.

    `mcpServers` is empty on purpose: a scaffold must not register broken
    placeholder commands that would shadow a working user-level registration.
    `mcp_manifest` carries the per-type list (用途/来源/注册命令模板).
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
                "Per-type 必配/可选 MCP 清单. 与 scripts/mcp_probe.py MANIFEST "
                "保持一致 (tests/test_mcp_supply.py pins equality)."
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
    args = parser.parse_args(argv)

    ws = Path(args.workspace).resolve()
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
