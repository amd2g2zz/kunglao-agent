# -*- coding: utf-8 -*-
"""Issue #93 regression tests: skill arguments = the user REQUEST, not a workspace path.

Guards three facts (SDD design D1/D2/D3, issue #93 — user correction on #90):
1. SKILL.md frontmatter declares `arguments: [request]` + `argument-hint: [request]`
   and does NOT declare `workspace` — the plain-skill loader's named-argument
   surface for `/kunglao-agent [subcommand | natural-language need]`.
2. SKILL.md body `## Arguments` section consumes `$ARGUMENTS` as a two-form
   intent contract: exact subcommand (`init` / `analysis` / `verify` / `resume` /
   mechanical passthrough) OR natural-language request mapped by intent keywords;
   workspace is NEVER a parameter (Phase 0 auto-detection); empty → `analysis`.
3. The repo root ships a metadata-only `.claude-plugin/plugin.json` (#366,
   user decision 2026-08-15 — version 0.1 must be plugin-manager-visible).
   The manifest declares identity fields ONLY: component paths (skills/
   hooks/commands) are what broke bare `/kunglao-agent` (regression 7f5f179,
   2026-08-10, `skills: ["./"]` wiring) and stay out until #364 (v1.0).

RED on baseline (2d695a8, #90 workspace semantics): 3.1 fails (frontmatter says
`workspace`, not `request`), 3.2 fails (Arguments section states "first argument
is the workspace path"; no subcommand set / mapping rule), 3.3 passes trivially
(it guards the future).
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


def test_skill_frontmatter_declares_request_argument() -> None:
    """D1: frontmatter declares `arguments: [request]` (NOT workspace) + argument-hint."""
    fm = _frontmatter()
    arguments = fm.get("arguments")
    assert arguments is not None, "frontmatter missing `arguments` key"
    assert "request" in arguments, \
        f"`arguments` must declare 'request' (the user request / subcommand), got: {arguments}"
    assert "workspace" not in arguments, \
        f"`arguments` must NOT contain 'workspace' (workspace is auto-detected in Phase 0), got: {arguments}"
    hint = fm.get("argument-hint")
    assert hint is not None, "frontmatter missing `argument-hint` key"
    assert "request" in hint, f"`argument-hint` must reference 'request', got: {hint}"


def test_skill_body_arguments_intent_contract() -> None:
    """D2: body `## Arguments` consumes $ARGUMENTS as subcommand or natural-language need."""
    section = _arguments_section()
    assert "$ARGUMENTS" in section, "Arguments section must reference the $ARGUMENTS placeholder"
    # subcommand set: the four semantic subcommands named in the contract
    assert "init" in section, "Arguments section must list the `init` subcommand"
    assert "analysis" in section, "Arguments section must list the `analysis` subcommand"
    assert "verify" in section, "Arguments section must list the `verify` subcommand"
    assert "resume" in section, "Arguments section must list the `resume` subcommand"
    # natural-language mapping rule: keyword -> subcommand
    assert "keyword" in section.lower() or "intent" in section.lower(), \
        "Arguments section must state the natural-language intent-mapping rule"
    # workspace is NEVER a parameter (Phase 0 auto-detection)
    assert "never a parameter" in section.lower() or "workspace is not a parameter" in section.lower(), \
        "Arguments section must state that workspace is never a parameter (Phase 0 auto-detection)"
    # empty -> default analysis loop
    assert "empty" in section.lower() and "analysis" in section, \
        "Arguments section must state the empty-$ARGUMENTS default (analysis)"


def test_repo_claude_plugin_is_metadata_only() -> None:
    """D3 (#366 amendment): `.claude-plugin/plugin.json` ships metadata-only.

    Identity fields (name/description/version/author/homepage/license) are
    required so v0.1 is visible to the plugin manager; any component
    wiring (skills/hooks/commands paths) re-triggers the 7f5f179 breakage
    (skills-directory plugin identity in the next session breaks bare
    /kunglao-agent) and is deferred to #364.
    """
    import json
    plugin_dir = ROOT / ".claude-plugin"
    assert plugin_dir.is_dir(), ".claude-plugin/ missing (issue #366 v0.1 deliverable)"
    manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "kunglao-agent"
    assert manifest["version"], "plugin.json version missing"
    forbidden = {"skills", "commands", "agents", "hooks", "mcpServers",
                 "lspServers", "outputStyles", "workflows"}
    wired = sorted(forbidden & set(manifest))
    assert not wired, (
        f"plugin.json declares component fields {wired} — behavioral surface is "
        f"#364 (v1.0), out of #366 minimal scope (regression 7f5f179)"
    )
