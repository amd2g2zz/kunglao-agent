#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_worker_lookup_constitution_145.py — worker-entry lookup
constitution sync pin (issue #145, guidance layer — ZERO enforcement).

Contract: every worker-facing agent file carries a front-loaded, formal-
voice reference-lookup + working-rules block (owner-revised wording 2026-09-07:
discretionary consultations — "a registered CLI may already cover this
capability" — never imperative "use X first" framing), closing on the
advisory-discretion line. Two byte-stable headings:
  ## Reference lookup (aids, not mandates)
  ## Working rules

Position rule (owner ruling): IDENTITY FIRST — the file's H1 title and
opening role prose stay ahead of the block (the agent learns who it is
before where to look), so the block sits at the END of the opening
identity/role prose, immediately before the file's first pre-existing `##`
section. Still front-loaded: the block must sit within the first
MAX_MARKER_BODY_LINE body lines. Guidance buried past line ~400 of a
constitution loses to the immediate task text (issue #34 disease) — a block
that rots to the bottom is behaviorally absent.

Windows are measured body-relative (after YAML frontmatter, which runs
40-76 lines today; the pure-insertion contract forbids rewriting it).

Deliberately pinned to a fixed file list (WORKER_FILES): protocol agents
(kunglao-redteam, kunglao-init-worker, verdict-scorer) are optional per the
issue and absent from this registry.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agents"

# Worker-facing agent files (issue #145 target set, pinned — additions to
# agents/ do NOT auto-enter this registry; extend explicitly).
WORKER_FILES = (
    "kunglao-worker.md",
    "ghidra-light.md",
    "go-symbols.md",
    "floss-filter.md",
    "pefile-signature.md",
    "web-re-worker.md",
)

# Byte-stable block headings (sync markers).
MARKER = "## Reference lookup (aids, not mandates)"
RULES_MARKER = "## Working rules"

# Byte-stable advisory-discretion closing line.
CLOSING = "proceed with a hand-rolled implementation at your discretion"

# Compressed rule slice (worker-relevant subset; the full rule text stays
# out of agent files — context budget).
RULE_SLICE_MARKERS = (
    "Explicit error handling at every level",
    "Never swallow errors silently",
    "No hardcoded secrets",
    "Validate inputs at boundaries",
    "Small focused functions",
    "Reuse-first",
)

# Owner-rejected first-draft forms (2026-09-07): MUST NOT reappear — the
# registry wording was covert-mandate ("...first") and the closing line plus
# system-meta commentary were informal. Guarded here so a future edit cannot
# silently regress to the rejected form.
REJECTED_FORMS = (
    "Before you build (first 3 lookups",
    "Hand-roll freely",
    "rule files never load in subagent sessions",
)

# "Still early": the Reference-lookup heading must sit within the first N
# body lines (identity prose stays ahead of it; web-re-worker's opening
# prose puts it deepest at body line 20).
MAX_MARKER_BODY_LINE = 40


def _body_lines(path: Path) -> list[str]:
    """Lines after the YAML frontmatter closing `---` (fail-closed on
    missing/malformed frontmatter)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", f"{path.name}: no frontmatter"
    try:
        end = lines.index("---", 1)
    except ValueError as exc:  # unterminated frontmatter
        raise AssertionError(f"{path.name}: unterminated frontmatter") from exc
    return lines[end + 1 :]


def _marker_idx(body: list[str], name: str) -> int:
    hits = [i for i, line in enumerate(body) if line.strip() == MARKER]
    assert hits, f"{name}: block heading missing: {MARKER!r}"
    return hits[0]


@pytest.mark.parametrize("name", WORKER_FILES)
def test_block_within_first_n_body_lines(name: str) -> None:
    body = _body_lines(AGENT_DIR / name)
    idx = _marker_idx(body, name)
    assert idx < MAX_MARKER_BODY_LINE, (
        f"{name}: block heading at body line {idx + 1} — not front-loaded "
        f"(must sit within the first {MAX_MARKER_BODY_LINE} body lines)"
    )


@pytest.mark.parametrize("name", WORKER_FILES)
def test_identity_precedes_block(name: str) -> None:
    """Owner position ruling: the H1 identity title comes BEFORE the block
    (the agent learns who it is before where to look)."""
    body = _body_lines(AGENT_DIR / name)
    marker_idx = _marker_idx(body, name)
    h1_idx = next(
        (i for i, line in enumerate(body) if line.lstrip().startswith("# ")),
        None,
    )
    assert h1_idx is not None, f"{name}: no H1 identity title in body"
    assert h1_idx < marker_idx, (
        f"{name}: block (body line {marker_idx + 1}) precedes the H1 "
        f"identity title (body line {h1_idx + 1}) — identity must come first"
    )


@pytest.mark.parametrize("name", WORKER_FILES)
def test_block_precedes_existing_first_heading(name: str) -> None:
    """Position: the block closes the opening identity/role prose — it sits
    before the file's pre-existing first `##` section heading (its own two
    headings do not count)."""
    body = _body_lines(AGENT_DIR / name)
    marker_idx = _marker_idx(body, name)
    section_idx = next(
        (
            i
            for i, line in enumerate(body)
            if line.lstrip().startswith("## ")
            and line.strip() not in (MARKER, RULES_MARKER)
        ),
        None,
    )
    assert section_idx is not None, f"{name}: no content section in body"
    assert marker_idx < section_idx, (
        f"{name}: block (body line {marker_idx + 1}) sits AFTER the existing "
        f"first section heading (body line {section_idx + 1}) — block must "
        "close the opening identity/role prose"
    )


@pytest.mark.parametrize("name", WORKER_FILES)
def test_closing_line_present(name: str) -> None:
    text = (AGENT_DIR / name).read_text(encoding="utf-8")
    assert CLOSING in text, f"{name}: closing line missing: {CLOSING!r}"


@pytest.mark.parametrize("name", WORKER_FILES)
def test_rule_slice_present(name: str) -> None:
    text = (AGENT_DIR / name).read_text(encoding="utf-8")
    missing = [m for m in RULE_SLICE_MARKERS if m not in text]
    assert not missing, f"{name}: rule-slice lines missing: {missing}"


@pytest.mark.parametrize("name", WORKER_FILES)
def test_no_rejected_form(name: str) -> None:
    """The owner-rejected first-draft wording must not reappear."""
    text = (AGENT_DIR / name).read_text(encoding="utf-8")
    hits = [r for r in REJECTED_FORMS if r in text]
    assert not hits, f"{name}: owner-rejected wording reappeared: {hits}"
