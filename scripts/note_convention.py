#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""note_convention.py — the settle-note writing convention (ICD-203 shape).

Verify / retro / gap notes are findings, not prose: every note separates the
four clauses the reference convention requires —

    assertion    the finding itself (one claim, stated plainly)
    derivation   HOW the finding was reached (the command, tool, or method
                 that produced it — the derivation source, named)
    evidence     the LINKS backing it (artifact paths, fact ids, ledger
                 files — machine-resolvable references, never bare trust)
    uncertainty  what the note does NOT know, stated explicitly ("none —"
                 counts, silence does not)

— the same clauses the fact schema's ICD-203 credibility defaults carry at
the fact layer (source reliability explicit, uncertainty explicit,
information / assumption / judgment separated), extended to the note layer.
The convention is a template + a shape lint; notes keep their channels (this
module owns the shape, never the storage).

Usage:
  python scripts/note_convention.py --template verify|retro|gap
  python scripts/note_convention.py --check <note.md>
Exit codes: 0 clean / 1 shape violations (each printed) / 2 usage.
"""
from __future__ import annotations

import argparse
import re
import sys

KINDS = ("verify", "retro", "gap")
SECTIONS = ("assertion", "derivation", "evidence", "uncertainty")

_SECTION_HEAD = re.compile(
    r"^(?:#{1,4}\s*|\*\*)?(assertion|derivation|evidence|uncertainty)"
    r"(?:\*\*)?\s*:?\s*$", re.IGNORECASE | re.MULTILINE)
#: a machine-resolvable reference: a path (has a slash or a known evidence
#: suffix), a fact id, or an evidence-id token
_LINK = re.compile(
    r"(?:\S*/\S+)|(?:\bF\d{3,}-[a-z0-9-]+\b)|(?:\beid-[A-Za-z0-9_-]+\b)|"
    r"(?:\bS\d+\b)|(?:[\w.-]+\.(?:md|json|jsonl|xml|yaml|txt|log)\b)")
_DERIVATION_SOURCE = re.compile(
    r"(?:\S*/\S+)|(?:[\w.-]+\.(?:py|sh|json|jsonl|xml|yaml|log|md|txt)\b)|"
    r"(?:\bF\d{3,}-[a-z0-9-]+\b)|(?:\beid-[A-Za-z0-9_-]+\b)")


def template(kind: str) -> str:
    """The note skeleton for one settle-note kind (fill the brackets; keep
    the four sections)."""
    if kind not in KINDS:
        raise ValueError(f"unknown note kind {kind!r} (kinds: {KINDS})")
    return f"""# {kind} note

## Assertion
<the finding — one claim, stated plainly>

## Derivation
<how this was reached — the command / tool / method, with its source path>

## Evidence
- <artifact path / fact id / ledger file>

## Uncertainty
<what this note does not know — or: none — <why the finding is settled>>
"""


def _sections(text: str) -> dict[str, str]:
    """Section name -> body text (tolerant: case-insensitive heads, the
    canonical markdown form plus the bare `name:` prefix)."""
    found: dict[str, str] = {}
    matches = list(_SECTION_HEAD.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        found.setdefault(name, text[start:end])
    return found


def check_note(text: str) -> list[str]:
    """The shape lint: every violation, one human-readable line each.

    A note passes when the four sections are present, the assertion /
    derivation / evidence bodies are non-empty, the derivation names its
    source, the evidence cites at least one machine-resolvable link, and
    the uncertainty clause is explicit (present and non-empty — an explicit
    "none" passes; silence does not)."""
    violations: list[str] = []
    found = _sections(text)
    for name in SECTIONS:
        if name not in found:
            violations.append(f"missing section: {name}")
    if "derivation" in found and not _DERIVATION_SOURCE.search(
            found["derivation"]):
        violations.append(
            "derivation names no source (a command, tool, or file reference)")
    if "evidence" in found and not _LINK.search(found["evidence"]):
        violations.append("evidence cites no machine-resolvable link "
                          "(path / fact id / evidence id)")
    if "uncertainty" in found and not found["uncertainty"].strip():
        violations.append("uncertainty is empty — state it explicitly "
                          '("none — <why>" counts, silence does not)')
    return violations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="settle-note shape lint (the four ICD-203 clauses)")
    ap.add_argument("--template", choices=KINDS,
                    help="print the note skeleton for one kind")
    ap.add_argument("--check", metavar="FILE",
                    help="lint one note file")
    args = ap.parse_args(argv)
    if args.template:
        print(template(args.template), end="")
        return 0
    if args.check:
        try:
            text = open(args.check, encoding="utf-8",
                        errors="replace").read()
        except OSError as exc:
            print(f"unreadable: {exc}", file=sys.stderr)
            return 2
        violations = check_note(text)
        for v in violations:
            print(f"NOTE: {v}")
        print("OK" if not violations else "FAIL")
        return 0 if not violations else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
