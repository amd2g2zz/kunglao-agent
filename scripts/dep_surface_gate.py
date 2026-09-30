#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dep_surface_gate.py — manifest-vs-imports consistency gate (issue 467).

The framework env project (the `uv run --project <root>` prefix that
serves every deployed hook command) declares its dependency set in
pyproject.toml + uv.lock. The deployed code (hooks/, scripts/ incl.
package subdirectories, tools/) imports third-party distributions
directly. When the env root is older than the deployed code, every hard
import that arrived after the env's manifest dies with
ModuleNotFoundError at runtime and fails open per tick — the 218-warn
live incident class this gate closes.

Faces:
  hard_imports(surface_root)     unguarded third-party import surface
  guarded_imports(surface_root)  degrade-by-design import set (exempt)
  declared_deps(package_root)    normalized [project].dependency names
  check(surface_root, env_root)  coverage report (env defaults to the
                                 surface's own package: self-check)
  framework_env_root()           the hook env resolution, delegated
  main(argv)                     CLI; exit 1 on an uncovered hard import

Guard policy: an import inside a try block whose handlers catch
ImportError, ModuleNotFoundError, Exception (or bare except) has a
written degrade path — optional by construction, exempt from the hard
set and listed informationally instead. Stdlib (sys.stdlib_module_names)
and in-tree modules (file stems + subdirectory names under the surface
dirs) are exempt. Import-name vs distribution-name splits resolve via
PEP 503 normalization plus an explicit alias table.

Known limitation: dynamic imports (exec/importlib string forms) are not
resolved, and a source file the running interpreter cannot parse
contributes zero imports (a syntax error fails at import time anyway);
none of these exist on the third-party surface today.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The deployed Python surface: exactly the trees deploy_manifest mirrors
# and the hook commands execute under the framework env project.
SURFACE_DIRS = ("hooks", "scripts", "tools")

# Import module name -> distribution name where PEP 503 normalization
# alone cannot bridge the split.
IMPORT_DIST_ALIASES = {
    "yaml": "pyyaml",
    "z3": "z3-solver",
    "pil": "pillow",
}

_NORM_SPLIT_RE = re.compile(r"[-_.]+")
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()))


def norm_dist(name: str) -> str:
    """PEP 503 name normalization: casefold + [-_.] runs -> single '-'."""
    return _NORM_SPLIT_RE.sub("-", name.strip().lower())


def dist_for(module: str) -> str:
    """The distribution that serves an imported top-level module."""
    return IMPORT_DIST_ALIASES.get(module, norm_dist(module))


def _local_modules(surface_root: Path) -> set[str]:
    """In-tree module names: .py stems + subdirectory names under the
    surface dirs (covers regular and namespace packages alike)."""
    out: set[str] = set()
    for d in SURFACE_DIRS:
        base = Path(surface_root) / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix == ".py":
                out.add(p.stem)
            elif p.is_dir():
                out.add(p.name)
    return out


def _is_guarded(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """True when an import sits inside a try whose handlers catch an
    import failure (the degrade-by-design shape)."""
    cur = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, ast.Try):
            for h in cur.handlers:
                if h.type is None:
                    return True  # bare except: swallows ImportError too
                names: list[str] = []
                if isinstance(h.type, ast.Name):
                    names = [h.type.id]
                elif isinstance(h.type, ast.Attribute):
                    names = [h.type.attr]
                elif isinstance(h.type, ast.Tuple):
                    names = [e.id for e in h.type.elts
                             if isinstance(e, ast.Name)]
                if any(n in ("ImportError", "ModuleNotFoundError",
                             "Exception") for n in names):
                    return True
        cur = parents.get(id(cur))
    return False


def _file_imports(path: Path, local: set[str]) -> list[tuple[str, bool]]:
    """(top-level module, guarded) pairs for one file — guarded meaning
    inside a try whose handlers catch an import failure."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return []
    parents: dict[int, ast.AST] = {}
    for n in ast.walk(tree):
        for child in ast.iter_child_nodes(n):
            parents[id(child)] = n
    out: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif (isinstance(node, ast.ImportFrom)
                and node.module and node.level == 0):
            mods = [node.module.split(".")[0]]
        for m in mods:
            if (not m or m in _STDLIB or m in local
                    or m.startswith("_")):
                continue
            out.append((m, _is_guarded(node, parents)))
    return out


def _scan_tree(surface_root: Path) -> tuple[dict[str, list[str]],
                                            dict[str, list[str]]]:
    """(hard, guarded) module -> relative file list over the surface."""
    local = _local_modules(surface_root)
    hard: dict[str, list[str]] = {}
    guarded: dict[str, list[str]] = {}
    for d in SURFACE_DIRS:
        base = Path(surface_root) / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(surface_root).as_posix()
            for module, is_guarded in _file_imports(path, local):
                sink = guarded if is_guarded else hard
                sink.setdefault(module, []).append(rel)
    return hard, guarded


def hard_imports(surface_root: Path) -> dict[str, list[str]]:
    hard, _guarded = _scan_tree(surface_root)
    return hard


def guarded_imports(surface_root: Path) -> dict[str, list[str]]:
    _hard, guarded = _scan_tree(surface_root)
    return guarded


def declared_deps(package_root: Path) -> list[str]:
    """[project].dependency names, declaration order — the
    instrument_menu parse (stdlib toml reader first with a tolerant
    line fallback),
    reused so the manifest read stays single-sourced."""
    try:
        import instrument_menu
        return list(instrument_menu.declared_deps(Path(package_root)))
    except Exception:  # noqa: BLE001 — a broken reader must not fake coverage
        return []


def check(surface_root: Path | None = None,
          env_root: Path | None = None) -> dict:
    """Coverage report: every HARD third-party import of the surface must
    be served by the env project's declared dependencies.

    env_root=None -> the surface's own package (self-check face; the CI
    leg runs it with both roots at the repository root). An unreadable
    env pyproject declares nothing — refusal-grade, matching the
    ephemeral-env posture (an env that cannot be read cannot serve).
    """
    surface_root = Path(surface_root) if surface_root is not None else ROOT
    env_root = Path(env_root) if env_root is not None else surface_root
    hard, guarded = _scan_tree(surface_root)
    declared = {norm_dist(d) for d in declared_deps(env_root)}
    missing = [
        {"module": m, "dist": dist_for(m), "needed_by": sorted(files)}
        for m, files in sorted(hard.items())
        if dist_for(m) not in declared
    ]
    return {
        "ok": not missing,
        "surface_root": str(surface_root),
        "env_root": str(env_root),
        "missing": missing,
        "guarded_undeclared": sorted(
            m for m in guarded if dist_for(m) not in declared),
    }


def framework_env_root() -> Path | None:
    """The env project the hook commands will run under — the
    hook_activation resolution, delegated (single source)."""
    import hook_activation
    return hook_activation._framework_project_root()


def _human(report: dict) -> str:
    if report["ok"]:
        return (f"OK: env {report['env_root']} covers the hard import "
                f"surface of {report['surface_root']}")
    surface = report["surface_root"]
    lines = [f"FAIL: env project {report['env_root']} does not declare "
             f"hard imports of {surface}:"]
    for m in report["missing"]:
        lines.append(f"  {m['module']} (dist {m['dist']}) needed by "
                     f"{', '.join(m['needed_by'][:3])}"
                     + (f" (+{len(m['needed_by']) - 3} more)"
                        if len(m['needed_by']) > 3 else ""))
    lines.append("fix: declare the dependency in the env project's "
                 "pyproject (or update the stale install), then re-run.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dep-surface-gate",
        description="manifest-vs-imports consistency gate (issue 467)")
    ap.add_argument("--surface", default=None,
                    help="package root whose hooks/scripts/tools are "
                         "scanned (default: this package)")
    ap.add_argument("--env", default=None,
                    help="package root whose pyproject declares the "
                         "serving env (default: same as --surface)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable report on stdout")
    args = ap.parse_args(argv)

    surface = Path(args.surface) if args.surface else ROOT
    env = Path(args.env) if args.env else surface
    report = check(surface_root=surface, env_root=env)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_human(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
