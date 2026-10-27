# -*- coding: utf-8 -*-
"""rlvr/distill_dgate.py — the D-gate: the runtime notes quality
bar (the NOTES_DUE chain's lint face).

The NOTES_DUE chain already obliges a terminal claim to write
`notes/<id>.md`; this face decides whether a note is DISTILL-WORTHY: it
passes only when it answers the three questions —

    plan_order         why this plan order
    branches           situation -> next-action branches
    hidden_reasoning   the hidden reasoning

Mechanical lint: each question needs a markdown section whose heading
matches one of its documented keyword variants, and the section body must
be non-trivial (>= MIN_SECTION_CHARS of non-whitespace below the heading).
The StandardDistillItem schema is the target shape — `hybrid_distill
--strategy self` consumes ONLY lint-passing notes as sources, so
self-distill items are born at runtime here.

Pure reads; zero telemetry points (Standard 11).
"""
from __future__ import annotations

import re
from pathlib import Path

#: the three questions, each with heading keyword variants (a variant
#: matches when EVERY keyword appears in the lowercased heading text)
QUESTIONS: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    ("plan_order", (("why", "order"), ("plan", "order"))),
    ("branches", (("branch",), ("situation", "action"))),
    ("hidden_reasoning", (("hidden",), ("reasoning",))),
)

#: a section body under MIN_SECTION_CHARS of non-whitespace is a stub
MIN_SECTION_CHARS = 40

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) pairs in document order. Text before the first
    heading belongs to no section (a preamble never answers a question)."""
    out: list[tuple[str, str]] = []
    matches = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) \
            else len(text)
        out.append((m.group(2), text[m.end():end]))
    return out


def _matches(heading: str, variants: tuple[tuple[str, ...], ...]) -> bool:
    low = heading.lower()
    return any(all(k in low for k in variant) for variant in variants)


def _nontrivial(body: str) -> bool:
    return len("".join(body.split())) >= MIN_SECTION_CHARS


def lint_note(text: str) -> dict:
    """The three-question lint. Returns {ok, missing, trivial, sections}:
    ok True iff every question has a matching section AND that section is
    non-trivial. Deterministic; pure."""
    sections = _sections(str(text or ""))
    missing: list[str] = []
    trivial: list[str] = []
    for qname, variants in QUESTIONS:
        bodies = [body for heading, body in sections
                  if _matches(heading, variants)]
        if not bodies:
            missing.append(qname)
        elif not any(_nontrivial(b) for b in bodies):
            trivial.append(qname)
    return {"ok": not missing and not trivial,
            "missing": missing, "trivial": trivial,
            "sections": [h for h, _b in sections]}


def passing_notes(ws) -> list[Path]:
    """The D-gate-passing notes of a workspace (the self pipeline's note
    sources), sorted, deterministic. A missing notes/ dir is an honest
    empty set; an unreadable note is skipped (never blocks the sweep)."""
    notes_dir = Path(ws) / "notes"
    if not notes_dir.is_dir():
        return []
    picked: list[Path] = []
    for p in sorted(notes_dir.glob("*.md")):
        if p.name.lower() == "readme.md":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if lint_note(text)["ok"]:
            picked.append(p)
    return picked
