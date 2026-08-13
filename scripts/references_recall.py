#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""references_recall — progressive-disclosure recall over references/INDEX.md (#229).

The agent-side entry point into the #227 layered reference index. Consumes the
two table kinds in references/INDEX.md:

  - scenario -> file map  ("## Scenario -> file (progressive disclosure triggers)")
  - file index rows       ("## Top-level references" / "## re-library/ ...",
                           columns: file | category | purpose | when-to-read)

Recall precedence (issue #229): scenario keyword -> scene map -> files;
else category word -> category column; else file-name word -> path column.
Output is INDEX rows only (path + one-line purpose + when-to-read) — the
progressive-disclosure contract: never dump reference file contents.

Usage:
  python references_recall.py <query>            # scene keyword / category / file name
  python references_recall.py --list-categories  # all categories + file counts
  python references_recall.py --scene-map        # scenario map as parsed from INDEX.md
  python references_recall.py --help

Exit codes: 0 = matches found; 1 = no match (closest categories listed);
2 = usage error or INDEX.md unreadable.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

SECTION_SCENE = "## Scenario"
SECTION_TOP = "## Top-level"
SECTION_RELIB = "## re-library"

# Cells used to skip table header rows (data rows always start with a file path).
_HEADER_CELLS = {"文件", "场景"}

USAGE = (
    "Usage: references_recall.py <query>\n"
    "       references_recall.py --list-categories\n"
    "       references_recall.py --scene-map\n"
    "Matching: scenario keyword -> scene map -> files; category word -> category\n"
    "column; file-name word -> path column. Output = INDEX rows only (no file dumps)."
)


@dataclass(frozen=True)
class Entry:
    """One row of the file index: file | category | purpose | when-to-read."""

    path: str      # repo-relative, e.g. "guardrails.md" | "re-library/tools-crypto.md"
    category: str
    purpose: str
    when: str


@dataclass(frozen=True)
class Scene:
    """One row of the scenario map: 场景 | 主文件 | 补充."""

    label: str
    primary: tuple[str, ...]        # resolved file paths
    supplementary: tuple[str, ...]


@dataclass(frozen=True)
class RecallResult:
    query: str
    kind: str                       # "scene" | "category" | "filename" | "none"
    scenes: tuple[Scene, ...]
    entries: tuple[Entry, ...]

    @property
    def files(self) -> tuple[str, ...]:
        """All matched file paths in deterministic (index) order, deduped."""
        seen: set[str] = set()
        out: list[str] = []
        for s in self.scenes:
            for p in (*s.primary, *s.supplementary):
                if p not in seen:
                    seen.add(p)
                    out.append(p)
        for e in self.entries:
            if e.path not in seen:
                seen.add(e.path)
                out.append(e.path)
        return tuple(out)


def default_index_path() -> Path:
    """INDEX.md lives next to the skill root (this script is under scripts/)."""
    return Path(__file__).resolve().parent.parent / "references" / "INDEX.md"


def _split_table_row(line: str) -> list[str] | None:
    """Split a markdown table row; return None for non-rows and separators."""
    s = line.strip()
    if not s.startswith("|") or not s.endswith("|"):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
        return None  # separator row
    return cells


def _tokens(cell: str) -> list[str]:
    """Backtick-quoted file tokens in a cell (the INDEX.md convention)."""
    return [t.strip() for t in re.findall(r"`([^`]+)`", cell)]


def _resolve_token(tok: str, cell: str, refs_dir: Path) -> str | None:
    """Map a scene-table token to a repo-relative path, or None if unresolvable.

    Existence decides the section; the cell hint ("re-library" / "顶层") is
    only a tiebreaker when a token exists in both sections. Tokens like
    `operational-mechanics` may sit in a re-library-scoped cell yet be
    top-level files — resolution must not drop them.
    """
    if "/" in tok:
        rel = tok if tok.endswith(".md") else tok + ".md"
        return rel if (refs_dir / rel).is_file() else None
    top_rel, sub_rel = f"{tok}.md", f"re-library/{tok}.md"
    top_ok = (refs_dir / top_rel).is_file()
    sub_ok = (refs_dir / sub_rel).is_file()
    if not top_ok and not sub_ok:
        return None
    if top_ok and sub_ok:
        if "re-library" in cell:
            return sub_rel
        if "顶层" in cell:
            return top_rel
        return top_rel  # no hint: top-level (protocols layer) wins
    return sub_rel if sub_ok else top_rel


def _resolve_tokens(cell: str, refs_dir: Path) -> tuple[str, ...]:
    out: list[str] = []
    for tok in _tokens(cell):
        rel = _resolve_token(tok, cell, refs_dir)
        if rel and rel not in out:
            out.append(rel)
    return tuple(out)


def parse_index(index_path: Path) -> tuple[list[Entry], list[Scene]]:
    """Parse INDEX.md into (file entries, scene map). Order = file order."""
    text = index_path.read_text(encoding="utf-8")
    refs_dir = index_path.parent
    entries: list[Entry] = []
    scenes: list[Scene] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line
            continue
        cells = _split_table_row(line)
        if not cells or not section:
            continue
        if section.startswith(SECTION_SCENE):
            if len(cells) < 3 or cells[0] in _HEADER_CELLS:
                continue
            label, primary, supplementary = cells[0], cells[1], cells[2]
            scenes.append(Scene(
                label=label,
                primary=_resolve_tokens(primary, refs_dir),
                supplementary=_resolve_tokens(supplementary, refs_dir),
            ))
        elif section.startswith(SECTION_TOP) or section.startswith(SECTION_RELIB):
            if len(cells) < 4 or cells[0].strip("`").strip() in _HEADER_CELLS:
                continue
            # The file column already carries the full relative path
            # (e.g. "re-library/tools-crypto.md"); the section prefix is only
            # a fallback for rows that omit it.
            path = cells[0].strip("`").strip()
            if not path.endswith(".md"):
                path += ".md"
            if section.startswith(SECTION_RELIB) and not path.startswith("re-library/"):
                path = "re-library/" + path
            entries.append(Entry(
                path=path,
                category=cells[1],
                purpose=cells[2],
                when=cells[3],
            ))
    return entries, scenes


def _norm(text: str) -> str:
    """Case-fold and strip separators so 'dynamic analysis' == 'dynamic-analysis'
    and posix/Windows paths compare equal."""
    return re.sub(r"[\s\-_/\\]+", "", text).lower()


def recall(entries: list[Entry], scenes: list[Scene], query: str) -> RecallResult:
    """Match query with #229 precedence: scene map, then category, then file name."""
    q = _norm(query)
    scene_hits = tuple(s for s in scenes if q in _norm(s.label))
    if scene_hits:
        return RecallResult(query, "scene", scene_hits, ())

    cat_exact = tuple(e for e in entries if _norm(e.category) == q)
    if cat_exact:
        return RecallResult(query, "category", (), cat_exact)

    cat_sub = tuple(e for e in entries if q in _norm(e.category))
    if cat_sub:
        return RecallResult(query, "category", (), cat_sub)

    name_hits = tuple(e for e in entries if q in _norm(e.path))
    if name_hits:
        return RecallResult(query, "filename", (), name_hits)

    return RecallResult(query, "none", (), ())


def _format_entry(e: Entry) -> str:
    return f"{e.path} | {e.category} | {e.purpose} | {e.when}"


def print_result(result: RecallResult, entries: list[Entry]) -> None:
    files = result.files
    print(f"# references recall: {result.query} — {len(files)} file(s)")
    if result.kind == "scene":
        for s in result.scenes:
            print(f"## scene: {s.label}")
            for p in (*s.primary, *s.supplementary):
                print(_format_entry(_entry_by_path(entries, p)))
    else:
        print(f"# matched by {result.kind}")
        for e in result.entries:
            print(_format_entry(e))


def _entry_by_path(entries: list[Entry], path: str) -> Entry:
    """Index row for a scene-file path; identity row only if the index is broken."""
    for e in entries:
        if e.path == path:
            return e
    return Entry(path=path, category="", purpose="", when="")


def print_categories(entries: list[Entry]) -> None:
    counts = Counter(e.category for e in entries)
    print(f"# categories ({len(counts)}) — file count per category")
    for cat, n in sorted(counts.items()):
        print(f"{cat} ({n})")


def print_scene_map(scenes: list[Scene]) -> None:
    print(f"# scene map ({len(scenes)} scene(s)) — scenario -> file paths")
    for s in scenes:
        print(f"## {s.label}")
        print(f"primary: {', '.join(s.primary)}")
        print(f"supplementary: {', '.join(s.supplementary)}")


def print_no_match(query: str, entries: list[Entry]) -> None:
    print(f"# references recall: {query} — no match")
    print("No reference file matches the query. Closest categories:")
    counts = Counter(e.category for e in entries)
    for cat, n in sorted(counts.items()):
        print(f"  {cat} ({n})")
    print("Try a scenario keyword (--scene-map) or a file name; "
          "see references/INDEX.md for the full index.")


def main(argv: list[str]) -> int:
    # INDEX.md is UTF-8 with CJK scene labels; force UTF-8 stdout so piped
    # output (agents, CI) round-trips on Windows consoles regardless of
    # the active code page.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0 if len(argv) >= 2 else 2

    index_path = default_index_path()
    if not index_path.is_file():
        print(f"error: INDEX.md not found at {index_path}", file=sys.stderr)
        return 2

    entries, scenes = parse_index(index_path)

    arg = argv[1]
    if arg == "--list-categories":
        print_categories(entries)
        return 0
    if arg == "--scene-map":
        print_scene_map(scenes)
        return 0

    result = recall(entries, scenes, arg)
    if result.kind == "none":
        print_no_match(arg, entries)
        return 1

    print_result(result, entries)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
