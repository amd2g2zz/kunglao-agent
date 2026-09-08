#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/re_pin_references.py — regenerate references/_INDEX.yaml file pins.

The pins in references/_INDEX.yaml drift whenever a references/ file is
edited (docs-only PRs, folds, case edits) without re-running this script —
the drift then fails tests/test_replay_gate.py in CI. Run this after ANY
references/ change:

    uv run python scripts/re_pin_references.py

Deterministic: recomputes sha256 for every file currently listed in
`files:` plus any .md under references/ not yet pinned, rewrites only the
`files:` block (sorted, one file per line), preserves `symptom_map` and all
other blocks byte-for-byte. No arguments, no side effects outside
references/_INDEX.yaml.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "references" / "_INDEX.yaml"
REFS = ROOT / "references"


def _sha256(p: Path) -> str:
    # newline-normalized: CI checks out LF while Windows trees are CRLF --
    # otherwise every pin drifts across environments.
    data = p.read_bytes()
    CR, LF = bytes((13,)), bytes((10,))
    return hashlib.sha256(
        data.replace(CR + LF, LF).replace(CR, LF)).hexdigest()


MAPPING = REFS / "re-library" / "_mapping.yaml"


def _mapping_faces() -> list[str]:
    """Card faces from the mapping: the destination once the move has
    landed, the source before it. The mapping is the single home of
    placement, so discovery resolves through it rather than walking the
    re-library tree."""
    if not MAPPING.is_file():
        raise SystemExit(f"ERROR: {MAPPING} missing — the mapping is required")
    doc = yaml.safe_load(MAPPING.read_text(encoding="utf-8")) or {}
    faces: list[str] = []
    for row in doc.get("cards") or []:
        for key in ("to", "from"):
            rel = str(row.get(key, ""))
            if rel and (ROOT / rel).is_file():
                faces.append(rel)
                break
    return faces


def _discover() -> list[str]:
    rels: list[str] = []
    for p in sorted(REFS.rglob("*.md")):
        if p.relative_to(REFS).is_relative_to("re-library"):
            continue  # re-library faces come from the mapping, not the walk
        rels.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    rels.extend(_mapping_faces())
    return sorted(set(rels))


def repin() -> tuple[int, list[str]]:
    """Recompute the files: block. Returns (changed_count, new_file_list)."""
    if not INDEX.exists():
        print(f"ERROR: {INDEX} missing — nothing to re-pin", file=sys.stderr)
        return 0, []
    lines = INDEX.read_text(encoding="utf-8").splitlines()
    files_start = next(i for i, ln in enumerate(lines) if ln.strip() == "files:")
    files_end = next(
        i for i in range(files_start + 1, len(lines)) if not lines[i].startswith("  ")
    )
    new_block = ["files:"] + [
        f"  {rel}: {_sha256(ROOT / rel)}" for rel in _discover()
    ]
    changed = new_block != lines[files_start:files_end]
    if changed:
        out = lines[:files_start] + new_block + lines[files_end:]
        # newline="\n": text-mode write on Windows would otherwise translate
        # LF -> CRLF, leaving the yaml CRLF on disk (issue #271 — CRLF pins
        # caused INDEX_DRIFT; keep the file LF so re-pins are portable).
        INDEX.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    return (1 if changed else 0), new_block[1:]


def main() -> int:
    changed, pins = repin()
    if changed:
        print(f"re-pinned {len(pins)} references files in references/_INDEX.yaml")
    else:
        print(f"no drift: {len(pins)} pins current")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
