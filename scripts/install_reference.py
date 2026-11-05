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
import re
from pathlib import Path

from _common import atomic_write_text

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


def outside_spans(text: str, workspace: Path) -> list[tuple[int, int, str]]:
    """#1002 — (start, end, matched) skill references resolving OUTSIDE the
    workspace, regardless of install name.

    In a workspace that carries its own project skill copy, the name
    predicate above is insufficient: a GLOBAL ``~/.claude/skills/kunglao-
    agent`` reference has the same name as the project copy yet still
    shadows it. The workspace-authoritative sweep rewrites every ref whose
    prefix is not under the workspace.
    """
    ws = Path(workspace).resolve()
    return [(m.start(), m.end(), m.group(0))
            for m in SKILL_REF_RE.finditer(text)
            if _is_global_prefix(m.group("prefix"), ws)]


# #1002: subpaths the deployment manifest mirrors at <ws>/.claude/<dir>.
# A reference into one of these must land on the workspace RUNTIME tree,
# not on the skill package (which carries only SKILL.md + skills/**).
_DEPLOY_SUBDIRS = ("scripts", "hooks", "agents", "references",
                   "templates", "tools")


def _workspace_target(ws: Path, tail: str) -> Path:
    """Map an install reference to the deployed workspace surface.

    ``<install>/scripts/x`` -> ``<ws>/.claude/scripts/x`` (the manifest
    mirror); ``<install>/SKILL.md`` / ``<install>/skills/...`` / a bare
    install root -> the project skill package
    ``<ws>/.claude/skills/kunglao-agent``.
    """
    rest = (tail or "").lstrip("/")
    seg = rest.split("/", 1)[0].split()[0] if rest.strip() else ""
    seg = seg.rstrip("`'\"<>,;)]}")
    if seg in _DEPLOY_SUBDIRS:
        return ws / ".claude"
    return ws / ".claude" / "skills" / "kunglao-agent"


def _rewire_style(matched: str, active_root: Path,
                  had_slash: bool, base: Path | None = None,
                  tail: str = "") -> str:
    """Same-style, same-face reference to the active root (`~` stays `~`,
    absolute stays absolute; root/deep face preserved — byte-conservative
    outside the install name itself).

    #1002: when ``base`` is given the reference is rewritten as an ABSOLUTE
    path on the workspace surface, chosen by the subpath that FOLLOWS the
    match (``tail``): runtime mirrors (scripts/hooks/tools/references/...)
    land under ``<ws>/.claude``; skill-package paths land under
    ``<ws>/.claude/skills/kunglao-agent``. The workspace is not necessarily
    under HOME, so a global ``~/...`` reference becomes absolute.
    """
    new_name = active_root.name
    prefix = matched.split("/.claude/skills/", 1)[0]
    sep = "/" if had_slash else ""
    if base is not None:
        target = _workspace_target(base, tail)
        return f"{target.as_posix()}{sep}"
    if prefix == "~":
        return f"~/.claude/skills/{new_name}{sep}"
    absolute = active_root.as_posix().rstrip("/")
    return f"{absolute}/.claude/skills/{new_name}{sep}"


def scan_workspace(workspace: Path,
                   active_root: Path,
                   outside_only: bool = False) -> dict[str, list[str]]:
    """Carrier -> unique STALE reference strings (name != active_root.name).
    Missing carriers are simply absent from the result; an unreadable
    carrier yields no row (hard I/O failures surface in the callers' own
    reads — this scanner never masks them as 'clean').

    #1002: ``outside_only`` switches the predicate to "resolves outside
    the workspace" (the project-copy-authoritative sweep)."""
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
        spans = (outside_spans(text, ws) if outside_only
                 else stale_spans(text, active_root.name))
        seen: list[str] = []
        for _, _, matched in spans:
            if matched not in seen:
                seen.append(matched)
        if seen:
            out[rel] = seen
    return out


def rewire_workspace(workspace: Path,
                     active_root: Path,
                     base: Path | None = None,
                     outside_only: bool = False) -> dict[str, dict[str, int]]:
    """Rewrite every stale reference in-place; per-carrier counters.

    Replacement is scoped to the stale spans only; settings.json content
    must JSON-parse BOTH before and after the rewrite or nothing is written.

    #1002: ``base`` rewrites the references as absolute paths under that
    root (the workspace), used when the workspace copy is authoritative;
    ``outside_only`` widens the predicate to every reference resolving
    outside the workspace (same-name global shadows included).
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
        spans = (outside_spans(text, ws) if outside_only
                 else stale_spans(text, active_root.name))
        if not spans:
            continue
        m_by_pos = {m.start(): m for m in SKILL_REF_RE.finditer(text)}
        parts: list[str] = []
        cursor = 0
        for start, end, matched in spans:
            parts.append(text[cursor:start])
            parts.append(_rewire_style(
                matched, active_root, bool(m_by_pos[start].group("slash")),
                base=base, tail=text[end:]))
            cursor = end
        parts.append(text[cursor:])
        new_text = "".join(parts)
        if rel.endswith(".json"):
            json.loads(text)      # pre-guard: carrier must parse as-is…
            json.loads(new_text)  # …and the post-image we are about to write
        atomic_write_text(p, new_text)
        report[rel] = {"before": len(find_refs(text)),
                       "rewired": len(spans),
                       "after": ref_count(new_text, active_root.name)}
    return report


# ---------------------------------------------------------------------------
# #1002: global skill / plugin shadow
# ---------------------------------------------------------------------------
# The stale scan above compares install NAMES (#752 predicate) — a global
# install carrying the SAME name ("kunglao-agent") is invisible to it, yet
# at runtime the global plugin cache / ~/.claude/skills tree wins over the
# project copy. That is a SHADOW, not staleness: detect it separately and
# report remediation (owner contract 2026-11-05: the project copy is
# authoritative; a shadow must never silently coexist).
PLUGIN_CACHE_RE = re.compile(
    r"[^\s\"'`()<>,]*\.claude[/\\]plugins[/\\]cache[/\\][^\s\"'`()<>,]*")


def _is_global_prefix(prefix: str, ws: Path) -> bool:
    """A skill reference prefix resolves OUTSIDE the workspace?"""
    p = (prefix or "").strip()
    if not p:
        return False
    if p.startswith("~") or p.startswith("$HOME"):
        return True
    if not Path(p).is_absolute():
        return False           # relative: not classifiable as a global root
    try:
        return not Path(p).resolve().is_relative_to(ws)
    except (OSError, ValueError):
        return True


def scan_global_shadow(workspace: Path) -> dict[str, list[str]]:
    """Carrier -> unique global skill/plugin references (#1002).

    Two faces: any ``.claude/plugins/cache/...`` token, and any
    ``.claude/skills/<name>`` reference whose prefix sits outside the
    workspace. Missing/unreadable carriers are simply absent (same posture
    as scan_workspace — I/O failures surface in the caller's own reads).

    Only a workspace that CARRIES a project skill copy can be shadowed:
    without one, the global/durable install is the legitimate active root
    (#752 dev co-install ruling), so the scan answers {} and the existing
    stale-rewire face owns the situation.
    """
    ws = Path(workspace).resolve()
    project_skill = ws / ".claude" / "skills" / "kunglao-agent"
    if not project_skill.is_dir():
        return {}
    out: dict[str, list[str]] = {}
    for rel in CARRIERS:
        p = ws / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        refs: list[str] = []

        def _add(ref: str) -> None:
            if ref not in refs:
                refs.append(ref)

        for m in PLUGIN_CACHE_RE.finditer(text):
            _add(m.group(0))
        for m in SKILL_REF_RE.finditer(text):
            if _is_global_prefix(m.group("prefix"), ws):
                _add(m.group(0))
        if refs:
            out[rel] = refs
    return out
