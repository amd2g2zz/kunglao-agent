#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reference_index_build.py — the re-library authoring CLI, keyed on the mapping.

One entry point over references/re-library/_mapping.yaml (schema
re-library-mapping/1), two faces:

  default       generate the two-tier index (see below)
  --scaffold    emit a standard-shaped card skeleton at a
                mapping-registered path (the scaffolder face)

Index face — single home of card placement is the mapping

Single home of card placement is references/re-library/_mapping.yaml
(schema re-library-mapping/1, extended with `domains:` and `scenarios:`
routing data blocks); this generator renders the two progressive-
disclosure tiers from that data plus each card's frontmatter:

  references/_INDEX.md           global tier: domain table, scenario map,
                                 per-domain file pointers, re-library
                                 catalog (a marked hand region for the
                                 Population B top-level table is preserved
                                 byte-for-byte)
  references/_index-<domain>.md  per-domain tier: one row per card whose
                                 summary cell is the card's frontmatter
                                 description verbatim

Rows emit the card's EXISTING path (the mapping `to` once the move has
landed, the `from` before it), so regeneration is correct on both sides
of the tree move and the intermediate state never dangles. Output is
byte-deterministic; `--check` exits 1 when committed files drift from
regeneration.

Usage:
  python scripts/reference_index_build.py
  python scripts/reference_index_build.py --check
Exit codes: 0 = written/verified; 1 = drift (with --check) or refusal
(mapping unreadable, card missing frontmatter).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_REL = "references/re-library/_mapping.yaml"
MAPPING_SCHEMA = "re-library-mapping/1"
INDEX_REL = "references/_INDEX.md"
RELIB_PREFIX = "references/re-library/"

DOMAIN_FILE = "_index-{domain}.md"
HAND_BEGIN = "<!-- BEGIN hand: top-level references -->"
HAND_END = "<!-- END hand: top-level references -->"

GLOBAL_HEADER = """# references/ Domain Index — progressive disclosure entry point

> Orchestrator: read this file once per round, pick a domain, dispatch
> the worker, worker reads `_index-<domain>.md`, then loads specific
> files. GENERATED FILE — regenerate with
> `python scripts/reference_index_build.py`; entries byte-match card
> frontmatter. Hand edits outside the marked hand region are overwritten.

## Domain table

| Domain | Files (re-library/) | Purpose |
|---|---|---|
"""

SCENARIO_HEADER = """
| Scenario | Domain |
|---|---|
"""

INDEXFILES_HEADER = """
## Per-domain index files

| File | Domain | Purpose | When to read |
|------|--------|---------|--------------|
"""

RELIB_HEADER = """
## re-library/ (Reverse Engineering Knowledge Base)

| File | Category | Purpose | When to read |
|------|----------|---------|--------------|
"""

DOMAIN_HEADER = """# {domain} domain index (file level)
> GENERATED FILE — regenerate with `python scripts/reference_index_build.py`.
> Row summaries are the card frontmatter descriptions, byte-for-byte.
| File | Summary |
|---|---|
"""


def _refusal(message: str) -> int:
    print(f"reference_index_build: refusal: {message}", file=sys.stderr)
    return 1


# ------------------------------------------------------------- data loading

def _load_mapping(root: Path) -> dict:
    path = root / MAPPING_REL
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise Refusal(f"mapping unreadable: {exc}")
    doc = doc or {}
    if doc.get("schema") != MAPPING_SCHEMA:
        raise Refusal(f"mapping schema must be {MAPPING_SCHEMA!r}")
    for key in ("domains", "scenarios", "cards"):
        if not doc.get(key):
            raise Refusal(f"mapping block {key!r} is missing or empty")
    return doc


def _card_frontmatter(root: Path, rel_path: str) -> dict:
    path = root / rel_path
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal(f"{rel_path}: unreadable: {exc}")
    if not text.startswith("---\n") or len(text.split("---\n", 2)) < 3:
        raise Refusal(f"{rel_path}: mapped card has no frontmatter")
    fm = yaml.safe_load(text.split("---\n", 2)[1])
    if not isinstance(fm, dict) or not fm.get("description"):
        raise Refusal(f"{rel_path}: frontmatter lacks a description")
    return fm


def _current_face(root: Path, row: dict) -> str:
    """The mapping path that exists right now (to post-move, from pre-move)."""
    for key in ("to", "from"):
        rel = row.get(key, "")
        if rel and (root / rel).is_file():
            return rel
    raise Refusal(f"{row.get('from')}: neither mapping path exists on disk")


class Refusal(Exception):
    """A generator refusal with a user-facing reason."""


def _esc(cell: str) -> str:
    return str(cell).replace("|", "\\|").replace("\n", " ").strip()


# -------------------------------------------------------------- rendering

TOP_SECTION = "## Top-level references"


def _preserved_hand_region(existing: Path) -> str:
    """The marked Population B table region survives regeneration as-is.
    A pre-marker file migrates: its Top-level references section (the
    Population B table, hand-maintained until that population's own index
    treatment) is adopted into the markers on first regeneration."""
    empty = "\n" + HAND_BEGIN + "\n" + HAND_END + "\n"
    if not existing.is_file():
        return empty
    text = existing.read_text(encoding="utf-8")
    begin = text.find(HAND_BEGIN)
    end = text.find(HAND_END)
    if begin != -1 and end != -1 and end > begin:
        return "\n" + text[begin:end + len(HAND_END)] + "\n"
    if TOP_SECTION in text:
        start = text.index(TOP_SECTION)
        nxt = text.find("\n## ", start + len(TOP_SECTION))
        section = text[start:] if nxt == -1 else text[start:nxt]
        return "\n" + HAND_BEGIN + "\n" + section.rstrip() + "\n" + HAND_END + "\n"
    return empty


def _render_global(root: Path, doc: dict) -> str:
    by_domain: dict[str, list[dict]] = {d: [] for d in doc["domains"]}
    for row in doc["cards"]:
        by_domain.setdefault(row["domain"], []).append(row)

    out = [GLOBAL_HEADER]
    for domain, purpose in doc["domains"].items():
        rows = [r for r in by_domain.get(domain, []) if r["from"].endswith(".md")]
        shorts = ", ".join(Path(r["to"]).stem for r in sorted(rows, key=lambda r: r["from"]))
        out.append(f"| {domain} | {shorts} | {_esc(purpose)} |\n")

    out.append(SCENARIO_HEADER)
    for label, expr in doc["scenarios"].items():
        out.append(f"| {_esc(label)} | {_esc(expr)} |\n")

    out.append(INDEXFILES_HEADER)
    for domain, purpose in doc["domains"].items():
        fname = DOMAIN_FILE.format(domain=domain)
        out.append(f"| `{fname}` | {domain} | {_esc(purpose)} | "
                   f"When dispatched to {domain} work |\n")

    out.append(RELIB_HEADER)
    for row in sorted(doc["cards"], key=lambda r: r["from"]):
        if not row["from"].endswith(".md"):
            continue  # data files ride with their consumer card, no catalog row
        face = _current_face(root, row)
        fm = _card_frontmatter(root, face)
        rel_in_refs = face[len("references/"):]
        out.append(f"| `{rel_in_refs}` | {row['domain']} | "
                   f"{_esc(fm['description'])} |  |\n")

    out.append(_preserved_hand_region(root / INDEX_REL))
    return "".join(out)


def _render_domain(root: Path, domain: str, rows: list[dict]) -> str:
    out = [DOMAIN_HEADER.format(domain=domain)]
    rows = [r for r in rows if r["from"].endswith(".md")]
    for row in sorted(rows, key=lambda r: r["from"]):
        face = _current_face(root, row)
        rel_in_refs = face[len("references/"):]
        fm = _card_frontmatter(root, face)
        stem = Path(face).stem
        out.append(f"| [{stem}.md]({rel_in_refs}) | {_esc(fm['description'])} |\n")
    return "".join(out)


def build_outputs(root: Path) -> dict[str, str]:
    doc = _load_mapping(root)
    by_domain: dict[str, list[dict]] = {d: [] for d in doc["domains"]}
    for row in doc["cards"]:
        by_domain.setdefault(row["domain"], []).append(row)
    outputs = {INDEX_REL: _render_global(root, doc)}
    for domain in doc["domains"]:
        rel = "references/" + DOMAIN_FILE.format(domain=domain)
        outputs[rel] = _render_domain(root, domain, by_domain.get(domain, []))
    return outputs




# ---------- scaffold face (card skeleton at a mapping-registered path) ----------

SKELETON = """---
{fm}---

# {title}

## When to Use

- <the scenario that makes this card the right home; concrete target state>

## When Not To Use

- <the boundary: what this card does not cover, and which card owns it>

## Worked Example

```python
# few-shot listing with synthetic values; no corpus literals
```
"""


class ScaffoldRefusal(RuntimeError):
    """A refusal with a user-facing reason; the CLI converts it to exit 1."""


def _scaffold_refusal(message: str) -> int:
    print(f"scaffold: refusal: {message}", file=sys.stderr)
    return 1


def _scaffold_row(mapping_path: Path, rel_path: str) -> dict | None:
    try:
        doc = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise ScaffoldRefusal(f"mapping unreadable: {exc}")
    doc = doc or {}
    if doc.get("schema") != MAPPING_SCHEMA:
        raise ScaffoldRefusal(f"mapping schema must be {MAPPING_SCHEMA!r}")
    rows = doc.get("cards") or []
    for row in rows:
        if isinstance(row, dict) and row.get("to") == rel_path:
            return row
    return None


def scaffold_card(root: Path, rel_path: str, description: str,
                  name: str | None = None) -> int:
    """Emit the standard skeleton at `rel_path` (repo-relative, must equal
    a mapping row 'to'); refuses unregistered paths, existing files, and
    empty descriptions — placement stays declared data-first."""
    if not rel_path.startswith(RELIB_PREFIX) or not rel_path.endswith(".md"):
        return _scaffold_refusal("path must be a .md file under references/re-library/")
    try:
        row = _scaffold_row(root / MAPPING_REL, rel_path)
    except ScaffoldRefusal as exc:
        return _scaffold_refusal(str(exc))
    if row is None:
        return _scaffold_refusal(
            f"{rel_path} is not registered in {MAPPING_REL} — add the row first")
    target = root / rel_path
    if target.exists():
        return _scaffold_refusal(f"{rel_path} already exists")
    if not description.strip():
        return _scaffold_refusal("description must not be empty")

    stem = target.stem
    fm_doc = {
        "name": name or stem,
        "description": description.strip(),
        "domain": row.get("domain"),
        "family": row.get("family"),
    }
    fm = yaml.safe_dump(fm_doc, sort_keys=False, allow_unicode=True, width=100)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SKELETON.format(fm=fm, title=stem.replace("-", " ").title()),
                      encoding="utf-8")
    print(f"scaffold: wrote {rel_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the re-library two-tier index from the mapping.")
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="repository root (default: this repo)")
    parser.add_argument("--check", action="store_true",
                        help="verify committed files match regeneration")
    parser.add_argument("--scaffold", action="store_true",
                        help="emit a card skeleton instead of generating "
                             "the index (requires --path and --description)")
    parser.add_argument("--path", default=None,
                        help="[--scaffold] repo-relative card path, must "
                             "equal a mapping row 'to'")
    parser.add_argument("--description", default=None,
                        help="[--scaffold] when-to-use + when-not "
                             "description for the frontmatter")
    parser.add_argument("--name", default=None,
                        help="[--scaffold] frontmatter name (default: path stem)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.scaffold:
        if not args.path or args.description is None:
            parser.error("--scaffold requires --path and --description")
        return scaffold_card(root, "/".join(Path(args.path).parts),
                             args.description, args.name)

    try:
        outputs = build_outputs(root)
    except Refusal as exc:
        return _refusal(str(exc))

    if args.check:
        drifted = [rel for rel, text in outputs.items()
                   if (root / rel).is_file()
                   and (root / rel).read_text(encoding="utf-8") != text]
        missing = [rel for rel in outputs if not (root / rel).is_file()]
        for rel in sorted(drifted + missing):
            print(f"drift: {rel}", file=sys.stderr)
        return 1 if (drifted or missing) else 0

    for rel, text in outputs.items():
        (root / rel).write_text(text, encoding="utf-8")
    print(f"reference_index_build: wrote {len(outputs)} index files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
