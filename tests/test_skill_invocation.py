"""Issue #90 regression tests: skill loader + arguments.

Guards three facts (SDD design D1/D2/D3, issue #90):
1. SKILL.md frontmatter declares `arguments: [workspace]` + `argument-hint` —
   the plain-skill loader's named-argument surface for `/kunglao-agent <workspace>`.
2. SKILL.md body actually consumes `$ARGUMENTS` (an `## Arguments` section with
   the workspace rule) — without it the loader only appends a trailing
   `ARGUMENTS:` line that the contract ignores.
3. The repo root has NO `.claude-plugin/` — a plugin.json converts the skill
   into a `skills-directory` plugin identity in the next session and breaks
   bare `/kunglao-agent` (regression 7f5f179, 2026-08-10).

RED on baseline: 3.1/3.2 fail (SKILL.md has no arguments/argument-hint and no
$ARGUMENTS consumption); 3.3 passes trivially (it guards the future).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"


def _frontmatter() -> dict:
    """Parse SKILL.md YAML frontmatter (delimited by leading/trailing `---`)."""
    text = SKILL.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "SKILL.md must start with a YAML frontmatter block"
    fm = yaml.safe_load(m.group(1))
    assert isinstance(fm, dict), "frontmatter must parse to a mapping"
    return fm


def _body() -> str:
    """SKILL.md body = everything after the frontmatter block."""
    text = SKILL.read_text(encoding="utf-8")
    m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
    assert m, "SKILL.md must start with a YAML frontmatter block"
    return text[m.end():]


def _arguments_section() -> str:
    """The `## Arguments` section of the body (between its heading and the next `## `)."""
    body = _body()
    m = re.search(r"^## Arguments\n(.*?)(?=^## |\Z)", body, re.DOTALL | re.MULTILINE)
    assert m, "SKILL.md body must contain a `## Arguments` section"
    return m.group(1)


def test_skill_frontmatter_declares_arguments() -> None:
    """D1: frontmatter declares `arguments: [workspace]` + `argument-hint` (named-arg surface)."""
    fm = _frontmatter()
    arguments = fm.get("arguments")
    assert arguments is not None, "frontmatter missing `arguments` key"
    assert "workspace" in arguments, f"`arguments` must include 'workspace', got: {arguments}"
    hint = fm.get("argument-hint")
    assert hint is not None, "frontmatter missing `argument-hint` key"
    assert "workspace" in hint, f"`argument-hint` must reference 'workspace', got: {hint}"


def test_skill_body_consumes_arguments() -> None:
    """D2: body has an `## Arguments` section consuming `$ARGUMENTS` with the workspace rule."""
    section = _arguments_section()
    assert "$ARGUMENTS" in section, "Arguments section must reference the $ARGUMENTS placeholder"
    # workspace rule: first argument = workspace path
    assert "first argument is the workspace path" in section, \
        "Arguments section must state the first-arg-is-workspace-path rule"
    # empty → default detection (falls back to the Local defaults table)
    assert "empty" in section.lower() and "local defaults" in section.lower(), \
        "Arguments section must state the empty-$ARGUMENTS default detection rule"


def test_repo_has_no_claude_plugin_dir() -> None:
    """D3: repo root has no `.claude-plugin/` — plugin-ification breaks bare /kunglao-agent."""
    assert not (ROOT / ".claude-plugin").exists(), \
        "repo root must NOT contain .claude-plugin/ (regression 7f5f179: converts the skill " \
        "into a skills-directory plugin identity and breaks bare /kunglao-agent)"
