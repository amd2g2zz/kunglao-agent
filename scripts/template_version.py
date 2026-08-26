#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""template_version.py — workspace template version stamp (#536).

The kunglao template release that materialized a workspace is pinned as a
uniform comment line on the three text carriers:

    # kunglao_template_version: <semver>

  - <ws>/CLAUDE.md          (top of file, before the rendered template)
  - <ws>/facts/_INDEX.md    (header block; update_index preserves comments)
  - <ws>/claim-register.yaml (header block, next to the [initialized] marker)

The comment form is load-bearing, not cosmetic: claim-register.yaml must
stay YAML-parseable (the stamp rides the comment header the [initialized]
marker already uses), and facts/_INDEX.md row rewrites (update_index._write)
preserve `#` lines verbatim — a bare `key: value` line would be dropped on
the first row upsert.

Umbrella rule (same shape as state_hash, kunglao-init.py): init WRITES the
stamps (claim_register_text / _INDEX scaffold stub / stamp_workspace on
CLAUDE.md), hooks_selfcheck + env_check VERIFY them, kunglao-status /
kunglao_resume cross-check workspace stamp vs the skill package version and
emit a one-line upgrade warning when the workspace is behind.

Version authority: pyproject.toml [project].version — the SAME source
release_receipt.py checks against release-manifest.yaml and
.claude-plugin/plugin.json. No third version file (a skills/VERSION would
drift from the receipt-checked pair).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Stamp carriers, stable order for messages. Labels double as the fault
# names verify_stamps / the env_check row report.
CARRIERS: tuple[tuple[str, str], ...] = (
    ("CLAUDE.md", "CLAUDE.md"),
    ("facts/_INDEX.md", "facts/_INDEX.md"),
    ("claim-register.yaml", "claim-register.yaml"),
)

STAMP_KEY = "kunglao_template_version"
# Comment-prefixed so the line is legal YAML (claim-register) and survives
# update_index row rewrites (_INDEX comment preservation).
STAMP_RE = re.compile(rf"^#\s*{STAMP_KEY}:\s*(\S+)", re.MULTILINE)

_FALLBACK_VERSION = "0.1.1"  # unreachable in-tree (pyproject ships); shapes the error path


def _read_version_from_pyproject() -> str | None:
    p = _REPO_ROOT / "pyproject.toml"
    if not p.is_file():
        return None
    m = re.search(r'^version\s*=\s*"([^"]+)"',
                  p.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
    return m.group(1) if m else None


def _read_version_from_plugin_manifest() -> str | None:
    p = _REPO_ROOT / ".claude-plugin" / "plugin.json"
    if not p.is_file():
        return None
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("version") or "")
    except (ValueError, OSError):
        return None


def read_skill_version() -> str:
    """The skill package version (single source: pyproject.toml, receipt-
    checked against release-manifest.yaml + plugin.json).

    Function, not a frozen constant, so tests and future callers can
    re-read after a version bump without an import cycle."""
    v = _read_version_from_pyproject() or _read_version_from_plugin_manifest()
    if v:
        return v
    raise RuntimeError(
        "template_version: no skill version found — neither pyproject.toml "
        "nor .claude-plugin/plugin.json declares one (both are repo-contract "
        "assets; a missing one is a release defect, not a default)")


def stamp_line(version: str) -> str:
    """The canonical carrier line (comment form — see module docstring)."""
    return f"# {STAMP_KEY}: {version}"


def stamp_workspace(ws: Path, *, version: str | None = None) -> list[str]:
    """Write (or refresh) the stamp on every carrier. Idempotent: an
    existing stamp line is replaced in place, a missing one is prepended
    at the top of the file; the rest of the file is untouched.

    Returns the list of carrier labels actually written (empty = all
    already carried exactly `version`). Missing parent dirs/files are
    created only for carriers whose file exists — a bare CLAUDE.md-less
    directory is not silently scaffolded here (init owns scaffolding)."""
    version = version or read_skill_version()
    written: list[str] = []
    ws = Path(ws)
    for label, rel in CARRIERS:
        p = ws / rel
        if not p.exists():
            continue  # init scaffolds; stamp only refreshes what is there
        text = p.read_text(encoding="utf-8", errors="replace")
        line = stamp_line(version)
        if STAMP_RE.search(text):
            new_text = STAMP_RE.sub(line, text, count=1)
        else:
            new_text = line + "\n" + text
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            written.append(label)
    return written


def read_workspace_version(ws: Path) -> str | None:
    """Workspace stamp version, read from CLAUDE.md (the primary carrier)."""
    p = Path(ws) / "CLAUDE.md"
    if not p.is_file():
        return None
    m = STAMP_RE.search(p.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def verify_stamps(ws: Path, *, expected: str | None = None) -> dict[str, str]:
    """Per-carrier fault map: label -> 'missing' | 'mismatch:<found>'.

    A carrier file that does not exist is NOT a stamp fault (init-completeness
    owns existence); a present file without the stamp line is 'missing', one
    carrying a different version is 'mismatch:<found>'. Empty dict = the
    workspace stamp contract holds."""
    expected = expected or read_skill_version()
    ws = Path(ws)
    faults: dict[str, str] = {}
    for label, rel in CARRIERS:
        p = ws / rel
        if not p.exists():
            continue
        m = STAMP_RE.search(p.read_text(encoding="utf-8", errors="replace"))
        if m is None:
            faults[label] = "missing"
        elif m.group(1) != expected:
            faults[label] = f"mismatch:{m.group(1)}"
    return faults


def _semver_tuple(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for p in v.split(".")[:3]:
        digits = re.match(r"\d+", p)
        parts.append(int(digits.group(0)) if digits else 0)
    return tuple(parts)


def upgrade_warning(ws: Path, *, skill_version: str | None = None) -> str | None:
    """One-line warning when the workspace stamp is OLDER than the active
    skill version (strictly older — equal or newer stamps stay silent)."""
    ws_v = read_workspace_version(ws)
    skill_v = skill_version or read_skill_version()
    if ws_v is None or _semver_tuple(ws_v) >= _semver_tuple(skill_v):
        return None
    return (f"upgrade: workspace template version {ws_v} is older than the "
            f"skill version {skill_v} — re-run kunglao-init to align "
            f"(expected {STAMP_KEY}: {skill_v})")


# --------------------------------------------------------------------------
# #758 G4: frame-consistency signature (openspec .../issue-758-runtime-version,
# design D3). The stamp must never outrun the body it stamps: an upgraded
# workspace whose CLAUDE.md predates the current template carries a HONEST old
# stamp until something merges the new template sections into it (Wave-2 G3).
# --------------------------------------------------------------------------

FRAME_HEADING_RE = re.compile(r"^#{1,6}\s")

# Module-level so tests can aim it at an absent path (exercising the
# fail-open branch); production value is repo-owned and receipt-checked.
_FRAME_TMPL = _REPO_ROOT / "templates" / "CLAUDE.md.base.tmpl"


def frame_headings_from_text(text: str) -> list[str]:
    """Heading skeleton of (rendered) markdown: ^#{1,6} lines outside code
    fences, `{{var}}` placeholders normalized to `<var>`. Fence toggles on
    ```-leading lines so embedded bash comments (the android flow card) are
    never counted as headings."""
    out: list[str] = []
    fenced = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if FRAME_HEADING_RE.match(stripped):
            out.append(re.sub(r"\{\{[^{}]*\}\}", "<var>", stripped).rstrip())
    return out


def expected_frame_headings() -> list[str]:
    """Heading skeleton of the CURRENT base-template render. Returns [] when
    the template is unreadable — frame_section_current treats that as
    fail-open (cannot verify != drift, design D3)."""
    try:
        return frame_headings_from_text(
            _FRAME_TMPL.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def frame_section_current(ws: Path, rendered_expected: str | None = None) -> bool:
    """True iff <ws>/CLAUDE.md carries the current template frame.

    Subsequence semantics (D3): template headings must appear IN ORDER in
    the workspace file, with any number of user-added sections interleaved;
    renaming/dropping/reordering any template heading means the body is
    stale — a fresh stamp on top would be the lying-stamp class (#717).

      missing CLAUDE.md       -> False (nothing to be consistent with)
      unreadable/empty tmpl   -> True  (fail-open; cannot verify != drift)
    """
    p = Path(ws) / "CLAUDE.md"
    if not p.is_file():
        return False
    if rendered_expected is not None:
        expected = frame_headings_from_text(rendered_expected)
    else:
        expected = expected_frame_headings()
    if not expected:
        return True
    actual = iter(frame_headings_from_text(
        p.read_text(encoding="utf-8", errors="replace")))
    return all(any(h == probe for probe in actual) for h in expected)
