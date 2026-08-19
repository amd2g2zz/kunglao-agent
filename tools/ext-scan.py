#!/usr/bin/env python3
"""ext-scan.py — deterministic ext-index generator over repo capabilities (#476).

Enumerates the repo-local "callable capability" face OUTSIDE the internal
tools/_INDEX.yaml execution registry (three sources, design D2):

  1. scripts/*.py  with an `if __name__ == "__main__"` entry point (CLI);
  2. hooks/*.py    with the same entry-point structure (gate hooks);
  3. references/re-library/*.md — capability-declaration domain docs
     (the #494 three-point check's third point).

Emits tools/_INDEX.ext.yaml — a DESCRIBE-ONLY catalog (zero new trust
mechanism, design D6): nothing consumes this index to EXECUTE anything.
Consumption is read/print (tools/tool-search.py --find) and citation
resolution (devkit/subagent_review._index_tool_names, #493 surface).

Capability tags come from the OPTIONAL tools/_INDEX.ext.map.yaml
(name -> "<domain>:<operation>"); unmapped entries surface as
capability: unknown — discovery never depends on map maintenance.

stdlib-only (ast/pathlib) — no yaml dependency, output is hand-serialized
for byte determinism; zero-LLM, zero-network.

Usage:
  python tools/ext-scan.py                 # regenerate tools/_INDEX.ext.yaml
  python tools/ext-scan.py --check         # exit 0 fresh / 1 stale or missing
  python tools/ext-scan.py --stdout        # print, never write
  python tools/ext-scan.py --root <dir>    # operate on another tree

Exit codes: 0 ok (written/checked/printed); 1 stale (--check) or
generator-level inconsistency (duplicate names, collision with an
internal registered name); 2 usage error.

The generator itself is NOT registered in any index (the querier does
not enter the queried registry — same discipline as tool-search.py).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# UTF-8 stdout contract (#317): --stdout emits docstring-derived text
# with non-ASCII; output must not crash a GBK console — stdout unified
# on UTF-8 with errors=replace (canonical guard shape, enforced by
# tests/test_utf8_stdout_convention.py). Subprocess callers decode UTF-8.
# The guard fires on the SCRIPT entry only — see the __main__ block.
# Import purity (#476 review L2): devkit/doc_sync.py executes this
# module's top level via importlib to reuse the entry-point predicates;
# an import must NOT reconfigure the importing (gate) process's stdout
# codec, or doc_sync._safe()'s sys.stdout.encoding-based GBK protection
# goes moot mid-run.

EXT_INDEX_REL = "tools/_INDEX.ext.yaml"
EXT_MAP_REL = "tools/_INDEX.ext.map.yaml"
INTERNAL_INDEX_REL = "tools/_INDEX.yaml"

# The three sources (design D2): (repo-relative dir, glob, kind label)
SOURCE_DIRS = (
    ("scripts", "*.py", "script"),
    ("hooks", "*.py", "hook"),
    ("references/re-library", "*.md", "reference"),
)

UNKNOWN_CAPABILITY = "unknown"

HOOK_USAGE_TEMPLATE = ("hook {source} (settings.json wiring; "
                       "JSON on stdin; exit code = verdict)")
REF_USAGE_TEMPLATE = "read {source} (capability reference)"

INDEX_HEADER = """schema: tools-ext-index/1
purpose: >-
  Descriptive catalog of callable repo capabilities OUTSIDE the internal
  tools/_INDEX.yaml execution registry: entry-point scripts/ CLIs,
  hooks/ gates, references/re-library/ capability docs (issue #476).
  DESCRIBE-ONLY, zero new trust mechanism — no code path executes an
  entry from this index. Consumption: tools/tool-search.py --find
  (read/print) and Gate 5 tools_used citation resolution (#493).
  GENERATED FILE — do not hand-edit; regenerate: python tools/ext-scan.py
"""


# ---- structural predicates (declaration over name lists / regex) ---------

def _parse_module(path: Path):
    """ast.parse with SyntaxWarning suppressed — pre-existing docstrings
    carry invalid escape sequences; we only need the tree, not the noise
    (compile still raises SyntaxError on real breakage)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(path.read_text(encoding="utf-8"))


def has_entry_point(path: Path) -> bool:
    """True iff the module has a top-level `if __name__ == "__main__":`
    node (AST-structural — the whitelist is a structural property, not a
    filename list; design D3). Unparseable files are conservatively NOT
    entry points (a syntax-broken script is a Gate 3 problem, not a
    catalog entry)."""
    try:
        tree = _parse_module(path)
    except (SyntaxError, OSError, ValueError):
        return False
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
                and t.left.id == "__name__"
                and any(isinstance(c, ast.Constant) and c.value == "__main__"
                        for c in t.comparators)):
            return True
    return False


def indexed_name_candidates(stem: str) -> tuple[str, ...]:
    """Every catalog name a file with this stem may legally carry: the
    raw stem, plus the cross-kind disambiguated forms (consumed by the
    Gate 7 consistency WARN — single source for the naming rule)."""
    return (stem, f"{stem}-script", f"{stem}-hook")


def iter_entry_sources(root: Path) -> list[tuple[str, str]]:
    """(repo-relative POSIX path, kind) for every entry-point file across
    the three source dirs, sorted for determinism."""
    out: list[tuple[str, str]] = []
    for rel_dir, pattern, kind in SOURCE_DIRS:
        d = root / rel_dir
        if not d.is_dir():
            continue
        for p in sorted(d.glob(pattern)):
            if kind == "reference" or has_entry_point(p):
                out.append((p.relative_to(root).as_posix(), kind))
    return sorted(out)


# ---- field derivation -----------------------------------------------------

def _module_docstring(path: Path) -> str:
    try:
        tree = _parse_module(path)
    except (SyntaxError, OSError, ValueError):
        return ""
    return ast.get_docstring(tree) or ""


def _first_doc_line(doc: str) -> str:
    for ln in doc.splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def _usage_from_docstring(doc: str, source: str) -> str:
    """First non-empty line following a 'Usage:' line in the module
    docstring; fallback `python <source>` (design D5)."""
    lines = doc.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "Usage:":
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()
    return f"python {source}"


def _frontmatter_field(text: str, field: str) -> str:
    """`<field>:` value from a leading --- frontmatter block, if any."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for ln in lines[1:]:
        if ln.strip() == "---":
            return ""
        if ln.startswith(f"{field}:"):
            return ln.partition(":")[2].strip()
    return ""


def derive_entry(source: str, kind: str, root: Path) -> dict:
    path = root / source
    stem = Path(source).stem
    name = stem  # raw-stem identity (#318 dead-name safety, design D5)
    if kind == "reference":
        text = path.read_text(encoding="utf-8", errors="replace")
        description = _frontmatter_field(text, "description")
        if not description:
            for ln in text.splitlines():
                if ln.startswith("# "):
                    description = ln[2:].strip()
                    break
        usage = REF_USAGE_TEMPLATE.format(source=source)
    else:
        doc = _module_docstring(path)
        description = _first_doc_line(doc) or f"{name} ({kind})"
        if kind == "hook":
            usage = HOOK_USAGE_TEMPLATE.format(source=source)
        else:
            usage = _usage_from_docstring(doc, source)
    return {"name": name, "kind": kind, "source": source,
            "usage": usage, "description": description}


# ---- capability map (optional; unmapped -> unknown) -----------------------

def load_capability_map(root: Path) -> dict[str, str]:
    """Line-level parse of tools/_INDEX.ext.map.yaml `map:` block
    (stdlib-only; `  <kebab-name>: <domain:op>` lines)."""
    mpath = root / EXT_MAP_REL
    if not mpath.is_file():
        return {}
    out: dict[str, str] = {}
    in_map = False
    for ln in mpath.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = ln.strip()
        if ln.startswith("map:"):
            in_map = True
            continue
        if not in_map or not stripped or stripped.startswith("#"):
            continue
        if ln.startswith("  ") and ":" in ln:
            k, _, v = stripped.partition(":")
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
        else:
            in_map = False
    return out


# ---- internal-registry collision guard ------------------------------------

def internal_registered_names(root: Path) -> set[str]:
    """Registered names from the internal tools/_INDEX.yaml (line-level,
    stdlib-only — mirrors devkit's no-yaml convention). Unreadable/absent
    index yields the empty set: the generator then cannot prove
    collision-freedom and still runs (the Gate 7 sub-check re-verifies
    against the real file)."""
    ipath = root / INTERNAL_INDEX_REL
    if not ipath.is_file():
        return set()
    names: set[str] = set()
    in_tools = False
    for ln in ipath.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("tools:"):
            in_tools = True
            continue
        if in_tools:
            if ln.startswith("  - name:"):
                names.add(ln.partition(":")[2].strip())
            elif ln.strip() and not ln.startswith((" ", "#")):
                in_tools = False
    return names


# ---- collection + rendering ----------------------------------------------

def collect_entries(root: Path) -> list[dict]:
    """All ext entries, capability-tagged and name-sorted (deterministic).

    Name identity rule (#318 dead-name safety): an entry's name is its
    RAW FILE STEM (underscores/hyphens exactly as on disk). No kebab
    transform — a transformed name can collide with a DEAD name (the
    deleted wrapper for scripts/kunglao_log.py is pinned by
    tests/test_dead_code_removal.py under its hyphen spelling, and a
    kebab transform of the live module would reproduce exactly that
    forbidden string) or with a sibling file it does not mean
    (kunglao-eval.py vs kunglao_eval.py).
    Stems are unique per directory, so the only disambiguation needed is
    the cross-kind suffix: scripts/completion_gate.py +
    hooks/completion_gate.py -> completion_gate-script +
    completion_gate-hook (symmetric, no source-dir priority).
    A collision with an INTERNAL registered name raises ValueError: the
    generator refuses to emit an ambiguous bare-name set."""
    cap_map = load_capability_map(root)
    internal = internal_registered_names(root)
    sourced = [(source, kind, derive_entry(source, kind, root))
               for source, kind in iter_entry_sources(root)]
    kinds_by_base: dict[str, set[str]] = {}
    for _, kind, entry in sourced:
        if entry["name"]:
            kinds_by_base.setdefault(entry["name"], set()).add(kind)
    by_name: dict[str, dict] = {}
    for source, kind, entry in sorted(sourced):
        base = entry["name"]
        if not base:
            continue
        name = f"{base}-{kind}" if len(kinds_by_base[base]) > 1 else base
        if name in by_name or name in internal:
            other = by_name.get(name, {}).get("source", "the internal registry")
            raise ValueError(
                f"ext name {name!r} ({source}) is ambiguous against "
                f"{other} — bare-name resolution must stay unambiguous")
        entry["name"] = name
        entry["capability"] = cap_map.get(name, UNKNOWN_CAPABILITY)
        by_name[name] = entry
    return [by_name[n] for n in sorted(by_name)]


def _q(text: str) -> str:
    """YAML-safe scalar: JSON double-quoted string (valid YAML 1.1/1.2)."""
    return json.dumps(str(text), ensure_ascii=False)


def render(entries: list[dict]) -> str:
    lines = [INDEX_HEADER.rstrip("\n"), "", "ext:"]
    for e in sorted(entries, key=lambda e: e["name"]):
        lines.append(f"  - name: {_q(e['name'])}")
        lines.append(f"    capability: {_q(e['capability'])}")
        lines.append(f"    source: {_q(e['source'])}")
        lines.append(f"    usage: {_q(e['usage'])}")
        lines.append(f"    description: {_q(e['description'])}")
    return "\n".join(lines) + "\n"


# ---- CLI ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="deterministic ext-index generator over repo "
                    "capabilities (issue #476)")
    ap.add_argument("--check", action="store_true",
                    help="compare the on-disk index against a fresh "
                         "regeneration (exit 1 on drift/absence)")
    ap.add_argument("--stdout", action="store_true",
                    help="print the generated index instead of writing")
    ap.add_argument("--root", default=None,
                    help="operate on another tree (default: this repo)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else REPO_ROOT
    try:
        text = render(collect_entries(root))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.stdout:
        sys.stdout.write(text)
        return 0

    target = root / EXT_INDEX_REL
    if args.check:
        if not target.is_file():
            print(f"stale: {EXT_INDEX_REL} missing — regenerate", file=sys.stderr)
            return 1
        # errors="replace" (#476 review L3): a non-UTF-8 tampered index
        # must land in this `stale` branch (clean exit 1), not raise a
        # UnicodeDecodeError traceback.
        on_disk = target.read_text(encoding="utf-8", errors="replace")
        if on_disk == text:
            return 0
        print(f"stale: {EXT_INDEX_REL} differs from a fresh regeneration — "
              f"run `python tools/ext-scan.py` and commit the result",
              file=sys.stderr)
        old, new = on_disk.splitlines(), text.splitlines()
        for i, (a, b) in enumerate(zip(old, new)):
            if a != b:
                print(f"  first diff at line {i + 1}:", file=sys.stderr)
                print(f"    on-disk: {a[:100]}", file=sys.stderr)
                print(f"    fresh:   {b[:100]}", file=sys.stderr)
                break
        return 1

    target.write_text(text, encoding="utf-8")
    count = len(text.splitlines())
    print(f"ok: wrote {target} ({count} line(s))")
    return 0


if __name__ == "__main__":
    # Canonical #317 UTF-8 stdout guard, CLI entry ONLY — moving it out
    # of module top level is the import-purity fix (#476 review L2).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # non-TTY / captured stream without reconfigure
    sys.exit(main())
