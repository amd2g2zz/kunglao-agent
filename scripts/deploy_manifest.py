#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_manifest.py — deployment manifest single source (#783).

Builds/verifies the manifest of framework files that init deploys INTO the
workspace and upgrade refreshes (overwrite semantics):

  <manifest> entries: {src, dest, kind}    kind ∈ hook | agent | scaffold

The `scaffold` set is NOT hand-maintained: it is the TRANSITIVE import
closure of everything the deployed hooks need from scripts/, computed here
by an AST walk to a fixpoint — correct-by-construction instead of a drifting
hand list.

CLI:
  python scripts/deploy_manifest.py --write     # regenerate + fill sha256
  python scripts/deploy_manifest.py --verify    # rc0 when sha all match
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "deploy-manifest.yaml"
SKILL_SCRIPTS = ROOT / "scripts"
IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", re.MULTILINE)


def _sha(p: Path) -> str:
    # Normalize newlines before hashing: CI checks out LF while Windows
    # working trees are often CRLF; byte-exact hashing would flag every
    # entry stale across environments.
    data = p.read_bytes()
    CRLF = bytes((13, 10))
    CR = bytes((13,))
    LF = bytes((10,))
    if CR in data:
        data = data.replace(CRLF, LF).replace(CR, LF)
    return hashlib.sha256(data).hexdigest()

def _module_imports(py: Path) -> set[str]:
    src = py.read_text(encoding="utf-8", errors="replace")
    return {m.group(1) for m in IMPORT_RE.finditer(src)}


def scaffold_closure() -> list[str]:
    """Transitive scripts/ dependency closure of the hooks directory."""
    available = {p.stem: p for p in SKILL_SCRIPTS.glob("*.py")}
    seen: dict[str, Path] = {}
    frontier: list[str] = []
    for h in sorted((ROOT / "hooks").glob("*.py")):
        frontier.extend(_module_imports(h))
    while frontier:
        name = frontier.pop()
        if name in seen or name not in available:
            continue
        seen[name] = available[name]
        frontier.extend(_module_imports(available[name]))
    return sorted(seen)


def build_entries() -> list[dict]:
    ents: list[dict] = []
    for p in sorted((ROOT / "hooks").glob("*.py")):
        ents.append({"src": f"hooks/{p.name}", "kind": "hook"})
    for p in sorted((ROOT / "agents").glob("*.md")):
        ents.append({"src": f"agents/{p.name}", "kind": "agent"})
    for stem in scaffold_closure():
        ents.append({"src": f"scripts/{stem}.py", "kind": "scaffold"})
    for e in ents:
        parts = e["src"].split("/", 1)
        e["dest"] = f".claude/{parts[0]}/{parts[1]}"
        e["sha256"] = _sha(ROOT / e["src"])
    return ents


def render_yaml(entries: list[dict]) -> str:
    lines = ["schema_version: '1'", "files:"]
    for e in entries:
        lines.append(f"  - src: {e['src']}")
        lines.append(f"    dest: {e['dest']}")
        lines.append(f"    kind: {e['kind']}")
        lines.append(f"    sha256: {e['sha256']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="#783 deployment manifest single source")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true",
                   help="regenerate the manifest (fills sha256)")
    g.add_argument("--verify", action="store_true",
                   help="check every entry's sha256 against the tree")
    args = ap.parse_args(argv)

    if args.write:
        MANIFEST.write_text(render_yaml(build_entries()), encoding="utf-8")
        print(f"OK: wrote {MANIFEST.name}")
        return 0

    text = MANIFEST.read_text(encoding="utf-8")
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: manifest unreadable: {exc}", file=sys.stderr)
        return 1
    bad = []
    for e in data.get("files") or []:
        p = ROOT / str(e["src"])
        if not p.is_file() or _sha(p) != e.get("sha256"):
            bad.append(e["src"])
    if bad:
        print("FAIL: stale entries — run --write:", file=sys.stderr)
        print("\n".join(sorted(bad)), file=sys.stderr)
        return 1
    print(f"OK: {len(data.get('files') or [])} entries verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
