# -*- coding: utf-8 -*-
"""install_reference.py — multi-install reference hygiene (#752).

Issue #752 class: with a long-lived dev co-install
(`~/.claude/skills/kunglao-agent-dev`) coexisting with the production
install, a workspace's framework carriers can still reference the OTHER
(stale) install — hook commands wired by a pre-fix tool version
(`--project <old-root> ...`), or CLAUDE.md paths rendered from an old
template (`~/.claude/skills/<old-name>/...`). This module is the pure
scanner/rewriter for exactly that residue, over the two framework carriers:

    .claude/settings.json   hook command faces (+ any other refs)
    CLAUDE.md               template-rendered doc references

Design rulings (#752 design.md):

  - comparison is by INSTALL NAME under ~/.claude/skills/ (the durable
    predicate of hook_activation.canonical_install_root); absolute vs
    tilde prefix does NOT decide staleness.
  - rewire is TEXTUAL and byte-conservative outside matched spans — each
    reference keeps its own prefix style (`~` stays `~`, absolute stays
    absolute); settings.json is JSON-reparsed (pre + post image) before
    anything touches disk, so a rewrite can never corrupt it silently.
  - library-only (no CLI entry point): consumers are hook_activation
    (verifier), kunglao_upgrade (end-step sweep) and the test face. A
    second entry-point face would need ext-index registration without
    adding an operator surface the upgrade sweep does not already provide.

Pure stdlib. Never imports from hook_activation (one-way dependency:
hook_activation -> this module).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

CARRIERS: tuple[str, ...] = (".claude/settings.json", "CLAUDE.md")

# A skills-install reference, TWO faces (#752: the dev-miswire signature is
# exactly the first one — `uv run --project <old-root>` with no deeper
# path):
#   root face  ".../.claude/skills/<name>"       (end-of-token)
#   deep face  ".../.claude/skills/<name>/..."   (trailing slash)
# The slash group captures which face matched; the lookahead pins the token
# boundary ('/' included — a root name directly followed by a deeper path
# segment terminates there) so 'kunglao-agent' never half-matches inside
# 'kunglao-agent-dev'.
# Non-greedy prefix keeps two references on one line independent; the name
# charset excludes '/' and whitespace so only real path segments match.
SKILL_REF_RE = re.compile(
    r"(?P<prefix>~|[^\s\"'`()<>,]{1,4096}?)"
    r"/\.claude/skills/"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9_.\-]*)"
    r"(?P<slash>/)?"
    r"(?=$|[/\s\"'`(),<>;)\]}])"
)


def find_refs(text: str) -> list[str]:
    """Every skills-install reference occurrence in `text` (full span)."""
    return [m.group(0) for m in SKILL_REF_RE.finditer(text)]


def ref_names(text: str) -> set[str]:
    """Distinct install names referenced."""
    return {m.group("name") for m in SKILL_REF_RE.finditer(text)}


def ref_count(text: str, name: str) -> int:
    """Occurrences referencing install <name> — the D5 zero-residue count."""
    return sum(1 for m in SKILL_REF_RE.finditer(text)
               if m.group("name") == name)


def stale_spans(text: str, active_name: str) -> list[tuple[int, int, str]]:
    """(start, end, matched) spans whose install name != active_name."""
    return [(m.start(), m.end(), m.group(0))
            for m in SKILL_REF_RE.finditer(text)
            if m.group("name") != active_name]


def _rewire_style(matched: str, active_root: Path,
                  had_slash: bool) -> str:
    """Same-style, same-face reference to the active root (`~` stays `~`,
    absolute stays absolute; root/deep face preserved — byte-conservative
    outside the install name itself)."""
    new_name = active_root.name
    prefix = matched.split("/.claude/skills/", 1)[0]
    sep = "/" if had_slash else ""
    if prefix == "~":
        return f"~/.claude/skills/{new_name}{sep}"
    base = active_root.as_posix().rstrip("/")
    return f"{base}/.claude/skills/{new_name}{sep}"


def scan_workspace(workspace: Path,
                   active_root: Path) -> dict[str, list[str]]:
    """Carrier -> unique STALE reference strings (name != active_root.name).
    Missing carriers are simply absent from the result; an unreadable
    carrier yields no row (hard I/O failures surface in the callers' own
    reads — this scanner never masks them as 'clean')."""
    ws = Path(workspace)
    out: dict[str, list[str]] = {}
    for rel in CARRIERS:
        p = ws / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        seen: list[str] = []
        for _, _, matched in stale_spans(text, active_root.name):
            if matched not in seen:
                seen.append(matched)
        if seen:
            out[rel] = seen
    return out


def rewire_workspace(workspace: Path,
                     active_root: Path) -> dict[str, dict[str, int]]:
    """Rewrite every stale reference in-place; per-carrier counters.

    Replacement is scoped to the stale spans only; settings.json content
    must JSON-parse BOTH before and after the rewrite or nothing is written.
    """
    ws = Path(workspace)
    report: dict[str, dict[str, int]] = {}
    for rel in CARRIERS:
        p = ws / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        spans = stale_spans(text, active_root.name)
        if not spans:
            continue
        m_by_pos = {m.start(): m for m in SKILL_REF_RE.finditer(text)}
        parts: list[str] = []
        cursor = 0
        for start, end, matched in spans:
            parts.append(text[cursor:start])
            parts.append(_rewire_style(
                matched, active_root, bool(m_by_pos[start].group("slash"))))
            cursor = end
        parts.append(text[cursor:])
        new_text = "".join(parts)
        if rel.endswith(".json"):
            json.loads(text)      # pre-guard: carrier must parse as-is…
            json.loads(new_text)  # …and the post-image we are about to write
        tmp = p.with_name(p.name + ".tmp752")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, p)
        report[rel] = {"before": len(find_refs(text)),
                       "rewired": len(spans),
                       "after": ref_count(new_text, active_root.name)}
    return report
