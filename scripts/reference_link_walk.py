#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reference_link_walk.py — relative-link integrity walker for references/.

Walks every .md file, extracts markdown links outside fenced code blocks,
and resolves each RELATIVE target against the linking file's directory
(markdown semantics). Web/pure-anchor targets are skipped.

The re-library tree move (re-library/_mapping.yaml) left bare-filename
links ([patterns.md](patterns.md#x)) that only resolve from the LINKED
file's old directory — the dominant #395 breakage class. `--fix`
path-corrects exactly that class: a broken link whose path part is a
BARE FILENAME that exists exactly once under the tree is rewritten to
the correct relative path (anchor preserved). Ambiguous or unresolvable
targets are reported and left untouched — the walker never invents.

CLI:
  python scripts/reference_link_walk.py references/            # report
  python scripts/reference_link_walk.py references/ --check    # rc1 on any broken
  python scripts/reference_link_walk.py references/ --fix      # rewrite, then report

Exit codes: 0 = zero broken, 1 = broken links exist (with --check) or fix
left residue, 2 = usage/root error.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE_RE = re.compile(r"```.*?```", re.S)
SKIP_PREFIXES = ("http://", "https://", "mailto:")


@dataclass(frozen=True)
class Broken:
    """One relative link that does not resolve from its referencing file."""
    file: Path   # referencing file (absolute)
    target: str  # raw link target incl. any #anchor


def _iter_md(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def _link_targets(text: str) -> list[str]:
    """Link targets outside fenced code blocks."""
    return [m.group(1) for m in LINK_RE.finditer(FENCE_RE.sub("", text))]


def _split_anchor(target: str) -> tuple[str, str]:
    path, _, anchor = target.partition("#")
    return path, anchor


def walk(root: Path) -> list[Broken]:
    """All relative links under `root` that do not resolve locally."""
    broken: list[Broken] = []
    for path in _iter_md(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for target in _link_targets(text):
            if target.startswith(SKIP_PREFIXES) or target.startswith("#"):
                continue
            rel, _anchor = _split_anchor(target)
            if not rel:
                continue  # pure-anchor link
            if not (path.parent / rel).resolve().exists():
                broken.append(Broken(file=path, target=target))
    return broken


def _name_index(root: Path) -> dict[str, list[Path]]:
    """Bare filename -> every location under root (for --fix resolution)."""
    index: dict[str, list[Path]] = {}
    for path in _iter_md(root):
        index.setdefault(path.name, []).append(path)
    return index


def _relative_link(source: Path, target: Path) -> str:
    """Posix-style relative path from source's directory to target."""
    rel = os.path.relpath(target.resolve(), start=source.parent.resolve())
    return PurePosixPath(rel).as_posix()


def fix(root: Path) -> list[Broken]:
    """Path-correct resolvable bare-filename links; return the remainder."""
    index = _name_index(root)
    fixed: list[Broken] = []
    for broken_link in walk(root):
        rel, anchor = _split_anchor(broken_link.target)
        if "/" in rel or not rel.endswith(".md"):
            fixed.append(broken_link)  # only the bare-filename class is auto-fixed
            continue
        candidates = index.get(Path(rel).name, [])
        if len(candidates) != 1:
            fixed.append(broken_link)  # ambiguous or unresolvable — report only
            continue
        new_rel = _relative_link(broken_link.file, candidates[0])
        new_target = f"{new_rel}#{anchor}" if anchor else new_rel
        text = broken_link.file.read_text(encoding="utf-8")
        replaced = text.replace(
            f"]({broken_link.target})", f"]({new_target})")
        if replaced != text:
            broken_link.file.write_text(replaced, encoding="utf-8")
        else:
            fixed.append(broken_link)
    return walk(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Walk and verify relative links under a markdown tree.")
    parser.add_argument("root", help="directory to walk (e.g. references/)")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 when any relative link is broken")
    parser.add_argument("--fix", action="store_true",
                        help="path-correct unique bare-filename links first")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"reference_link_walk: no such directory: {root}", file=sys.stderr)
        return 2

    if args.fix:
        remaining = fix(root)
        for b in remaining:
            print(f"unfixed: {b.file}: {b.target}")
    broken = walk(root)
    for b in broken:
        print(f"broken: {b.file}: {b.target}")
    total = len(broken)
    print(f"reference_link_walk: {total} broken relative link(s) under {root}")
    if args.check and total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
