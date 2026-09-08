#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scaffold_card.py — emit a standard-shaped card skeleton at a mapping-registered path.

The re-library mapping (references/re-library/_mapping.yaml, schema
re-library-mapping/1) is the single home of card placement: this tool
refuses to create a card anywhere the mapping does not already register,
so placement is always declared data-first. Emitted skeleton shape (the
three standard components every card carries, per the standardization
constitution):

  ---
  name: <stem>
  description: <one paragraph naming when to use and when not>
  domain: <mapping row domain>
  family: <mapping row family>
  ---

  # <Title>

  ## When to Use
  - <scenario bullet>

  ## When Not To Use
  - <boundary bullet naming where the excluded content lives>

  ## Worked Example

  ```python
  # few-shot listing with synthetic values
  ```

Usage:
  python scripts/scaffold_card.py --path references/re-library/web/vm/x.md --description "..."
  python scripts/scaffold_card.py --path <p> --name <name> --root <repo root>

Exit codes: 0 = skeleton written; 1 = refusal (unregistered path, existing
file, mapping absent or misparsed, description missing/empty).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_REL = "references/re-library/_mapping.yaml"
MAPPING_SCHEMA = "re-library-mapping/1"
RELIB_PREFIX = "references/re-library/"

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
    """A refusal with a user-facing reason; main() converts it to exit 1."""


def _refusal(message: str) -> int:
    print(f"scaffold_card: refusal: {message}", file=sys.stderr)
    return 1


def _load_row(mapping_path: Path, rel_path: str) -> dict | None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit a standard card skeleton at a mapping-registered path.")
    parser.add_argument("--path", required=True,
                        help="repo-relative card path, must equal a mapping row 'to'")
    parser.add_argument("--description", required=True,
                        help="when-to-use + when-not description for the frontmatter")
    parser.add_argument("--name", default=None,
                        help="frontmatter name (default: path stem)")
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="repository root (default: this repo)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    rel_path = "/".join(Path(args.path).parts)
    if not rel_path.startswith(RELIB_PREFIX) or not rel_path.endswith(".md"):
        return _refusal("path must be a .md file under references/re-library/")
    try:
        row = _load_row(root / MAPPING_REL, rel_path)
    except ScaffoldRefusal as exc:
        return _refusal(str(exc))
    if row is None:
        return _refusal(
            f"{rel_path} is not registered in {MAPPING_REL} — add the row first")
    target = root / rel_path
    if target.exists():
        return _refusal(f"{rel_path} already exists")
    if not args.description.strip():
        return _refusal("description must not be empty")

    stem = target.stem
    fm_doc = {
        "name": args.name or stem,
        "description": args.description.strip(),
        "domain": row.get("domain"),
        "family": row.get("family"),
    }
    fm = yaml.safe_dump(fm_doc, sort_keys=False, allow_unicode=True, width=100)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SKELETON.format(fm=fm, title=stem.replace("-", " ").title()),
                      encoding="utf-8")
    print(f"scaffold_card: wrote {rel_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
