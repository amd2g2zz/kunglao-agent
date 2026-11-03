#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""supply_gate.py — every DECLARED face must resolve (issue #767).

The plugin declares MCP servers and agents/env tables declare tool and
supply faces. #767's defect: `.claude-plugin/plugin.json` declared
`python -m camoufox_reverse_mcp` while the distribution exists on no
public index and the module was not an in-tree artifact — a declared
face that cannot resolve on any fresh machine. Owner pre-authorized a
three-way ruling (vendor in-tree / re-point to a pinned installable
source / cut the face), executed by evidence.

Ruling executed here: RE-POINT. Evidence: the module's origin is the
public repo https://github.com/WhiteNightShadow/camoufox-reverse-mcp
(MIT; proven by the local clone at ~/projects/camoufox-reverse-mcp and
the editable install in ~/pentests/OneForAll/.venv). Vendoring was
rejected because the heavy dep closure (mcp, camoufox[geoip] which
downloads a browser, playwright, esprima) cannot ride in-tree anyway —
"self-contained" would be illusory; the pinned git source resolves the
dep closure transitively via uv.

This gate makes the defect class mechanical: it parses every declared
face and FAILS (non-zero) on any face that does not resolve to

  A. a PINNED INSTALLABLE SOURCE — a `git+URL@<ref>` spec whose ref is
     not a branch (main/master/head are not pins), or
  B. an IN-TREE ARTIFACT — a repo-relative script path that exists, or
     a `python -m <mod>` whose module is a package directory in one of
     the repo's source roots.

Anything else is VAPOR. Families parsed:

  1. plugin-mcp — .claude-plugin/plugin.json mcpServers commands
  2. agents     — agents/*.md frontmatter tool entries: `Bash(...)`
                  items citing a concrete repo-relative .py path
                  (parameterized placeholders like `<skill_root>/...`
                  are templates, not concrete faces; `mcp__server__*`
                  entries are harness permission grants, not launch
                  commands — server supply is gated by families 1+3)
  3. env-table  — scripts/mcp_probe.py MANIFEST rows: a row claiming
                  plugin carriage must have that carriage face RESOLVE
                  (the claim is only as good as the face behind it);
                  any git+ URL cited must carry a non-branch pin

Face families covered elsewhere (not duplicated here): environment
platform tools are gated by scripts/toolchain.py probes at init;
workspace .mcp.json registrations are gated by scripts/mcp_probe.py.

CLI:
  uv run python devkit/supply_gate.py [--root PATH] [--json]

Exit codes: 0 = every face resolves; 1 = vapor faces found;
2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import mcp_probe  # noqa: E402  (repo's MCP env table — single source)

# refs that are NOT pins (a moving branch cannot be a supply pin)
UNPINNED_REFS = {"main", "master", "head", ""}
GIT_PIN_RE = re.compile(r"^git\+(?:https?|ssh)://\S+@(?P<ref>[^/\s]+)$")
# `-m <mod>` interpreter faces
MODULE_ARGS_RE = re.compile(r"^-m$")
# repo source roots searched for `-m <mod>` in-tree artifacts
SOURCE_ROOTS = ("", "scripts", "tools", "devkit", "src", "lib", "hooks")
# frontmatter keys whose list items are agent tool declarations
_TOOL_KEY = "tool"
# concrete repo-relative script citations inside `Bash(...)` faces
_AGENT_PATH_RE = re.compile(
    r"(?:python3?|uv run python3?)\s+"
    r"((?:scripts|tools|devkit|hooks)/[A-Za-z0-9_./-]+\.py)")


def _is_pinned_git(spec: str) -> tuple[bool, str]:
    """True iff spec is a git+URL@<ref> with a non-branch ref."""
    m = GIT_PIN_RE.match(spec)
    if not m:
        return False, f"malformed or unpinned git source: {spec}"
    if m.group("ref").lower() in UNPINNED_REFS:
        return False, f"branch ref is not a pin: {spec}"
    return True, f"pinned installable source ({spec})"


def _module_in_tree(root: Path, mod: str) -> bool:
    return any(
        (root / base / mod / "__init__.py").is_file()
        for base in SOURCE_ROOTS if base
    ) or (root / mod / "__init__.py").is_file()


def resolve_face(name: str, cfg: dict, root: Path) -> tuple[bool, str]:
    """Resolve one launch face {command, args}. (ok, reason)."""
    command = str(cfg.get("command", "")).strip()
    args = [str(a) for a in (cfg.get("args") or [])]
    if not command:
        return False, "vapor: face declares no command"
    # class A first: a pin dominates (the module need not be in tree)
    pins = [a for a in args if a.startswith("git+")]
    if pins:
        for p in pins:
            ok, why = _is_pinned_git(p)
            if not ok:
                return False, why
        return True, f"pinned installable source ({', '.join(pins)})"
    # class B: in-tree artifact
    if "/" in command and (root / command).is_file():
        return True, f"in-tree artifact ({command})"
    for a in args:
        if (a.endswith(".py") and not a.startswith("-")
                and (root / a).is_file()):
            return True, f"in-tree artifact ({a})"
    if args and MODULE_ARGS_RE.match(args[0]) and len(args) >= 2:
        mod = args[1]
        if _module_in_tree(root, mod):
            return True, f"in-tree artifact (module {mod})"
        return False, (
            f"vapor: `{command} -m {mod}` — module is not an in-tree "
            "artifact and the face carries no pinned installable source")
    return False, (
        f"vapor: `{command}` — no pinned installable source and no "
        "in-tree artifact behind the face")


def _frontmatter_tool_items(md_path: Path) -> list[str]:
    """List items under frontmatter keys containing 'tool' (line-based
    parser — agent frontmatter is flat key/list YAML)."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.startswith("---"):
        return []
    lines = text.splitlines()
    items: list[str] = []
    current: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):(.*)$", line)
        if m:
            current = m.group(1).lower() if _TOOL_KEY in m.group(1).lower() \
                else None
            continue
        li = re.match(r"^\s*-\s+(.+)$", line)
        if li and current:
            items.append(li.group(1).strip())
    return items


def _check_agents(root: Path, out: list) -> None:
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return
    for md in sorted(agents_dir.glob("*.md")):
        for item in _frontmatter_tool_items(md):
            if "<" in item:  # parameterized template, not a concrete face
                continue
            m = _AGENT_PATH_RE.search(item)
            if not m:
                continue  # not a launch face (permission grants, etc.)
            path = m.group(1)
            if not (root / path).is_file():
                out.append({
                    "family": "agents", "name": f"{md.name}:{item}",
                    "status": "VAPOR",
                    "reason": f"vapor: cited script does not exist: {path}",
                })


def _check_env_table(root: Path, out: list) -> None:
    known = {n for grp in mcp_probe.MANIFEST_GROUPS.values() for n in grp}
    for item in mcp_probe.MANIFEST:
        blob = f"{item.source} {item.register}"
        for spec in re.findall(r"git\+\S+", blob):
            ok, why = _is_pinned_git(spec)
            if not ok:
                out.append({"family": "env-table", "name": item.name,
                            "status": "VAPOR", "reason": why})
        if "ships with the kunglao-agent plugin" not in blob:
            continue
        servers = mcp_probe.plugin_declared_servers(root)
        if item.name not in servers:
            out.append({
                "family": "env-table", "name": item.name, "status": "VAPOR",
                "reason": "vapor: row claims plugin carriage but the "
                          "plugin declares no such server",
            })
            continue
        ok, why = resolve_face(item.name, servers[item.name], root)
        if not ok:
            out.append({
                "family": "env-table", "name": item.name, "status": "VAPOR",
                "reason": f"carriage claim behind an unresolved face: {why}",
            })
        if item.name not in known:
            out.append({
                "family": "env-table", "name": item.name, "status": "VAPOR",
                "reason": "env-table row absent from MANIFEST_GROUPS",
            })


def violations(root: Path | str = REPO_ROOT) -> list[dict]:
    """All vapor faces under root (empty list = everything resolves)."""
    root = Path(root)
    out: list[dict] = []

    servers = mcp_probe.plugin_declared_servers(root)
    for name in sorted(servers):
        ok, why = resolve_face(name, servers[name] or {}, root)
        if not ok:
            out.append({"family": "plugin-mcp", "name": name,
                        "status": "VAPOR", "reason": "vapor: " + why
                        if not why.startswith("vapor") else why})

    _check_agents(root, out)
    _check_env_table(root, out)
    return out


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(
        description="supply gate: every declared face must resolve (#767)")
    p.add_argument("--root", default=str(REPO_ROOT),
                   help="plugin/repo root (default: this repo)")
    p.add_argument("--json", action="store_true", dest="json_out",
                   help="emit a JSON verdict document")
    args = p.parse_args(argv)

    root = Path(args.root)
    if not (root / ".claude-plugin" / "plugin.json").is_file():
        print(f"supply-gate: no plugin manifest under {root}", file=sys.stderr)
        return 2

    servers = mcp_probe.plugin_declared_servers(root)
    faces = []
    for name in sorted(servers):
        ok, why = resolve_face(name, servers[name] or {}, root)
        faces.append({"family": "plugin-mcp", "name": name,
                      "status": "ok" if ok else "VAPOR", "reason": why})
    bad = violations(root)
    for v in bad:
        if all(not (f["family"] == v["family"] and f["name"] == v["name"])
               for f in faces):
            faces.append(v)

    if args.json_out:
        print(json.dumps({"violations": bad, "faces": faces}, indent=2))
        return 1 if bad else 0
    for f in faces:
        mark = "[ok]" if f["status"] == "ok" else "[VAPOR]"
        print(f"{mark} {f['family']}/{f['name']}: {f['reason']}")
    if bad:
        print(f"supply-gate: {len(bad)} vapor face(s)", file=sys.stderr)
        return 1
    print(f"supply-gate: all declared faces resolve ({len(faces)} face(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
