# -*- coding: utf-8 -*-
"""Issue #93 regression tests — amended by #413 for the subcommand-UX contract.

Original #93 guards (kept where still true):
1. The main skill frontmatter declares `arguments: [request]` and does NOT
   declare `workspace` — the plain-skill loader's named-argument surface for
   `/kunglao-agent [subcommand | natural-language need]`.
3. The repo root ships a metadata-only `.claude-plugin/plugin.json` (#366).

#413 changes (#93 fact 2, and the #93 D1 hint):
- The main skill now lives at `skills/kunglao-agent/SKILL.md` (one skill
  directory per command, plugin namespace = `plugin:skill`).
- `argument-hint` is the subcommand menu (`init <workspace> | analysis
  <workspace> | help`) instead of `[request]` — hints show at autocomplete.
- The body `## Arguments` section still consumes `$ARGUMENTS` as a two-form
  intent contract (subcommand OR natural-language need), workspace is still
  NEVER a parameter, but the empty-`$ARGUMENTS` default CHANGED from
  "silently run analysis" to "print the subcommand menu and WAIT" (#413).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "kunglao-agent" / "SKILL.md"


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
    """D1 (#93): frontmatter declares `arguments: [request]` (NOT workspace)."""
    fm = _frontmatter()
    arguments = fm.get("arguments")
    assert arguments is not None, "frontmatter missing `arguments` key"
    assert "request" in arguments, \
        f"`arguments` must declare 'request' (the user request / subcommand), got: {arguments}"
    assert "workspace" not in arguments, \
        f"`arguments` must NOT contain 'workspace' (workspace is auto-detected in Phase 0), got: {arguments}"
    hint = fm.get("argument-hint")
    assert hint is not None, "frontmatter missing `argument-hint` key"


def test_skill_frontmatter_hint_lists_subcommands() -> None:
    """D1 (#413): the autocomplete hint advertises the subcommand menu."""
    hint = str(_frontmatter().get("argument-hint", ""))
    for token in ("init", "analysis", "help"):
        assert token in hint, f"argument-hint must advertise the {token} subcommand, got: {hint}"


def test_skill_body_arguments_intent_contract() -> None:
    """D2 (#93 + #413): body `## Arguments` consumes $ARGUMENTS as a two-form
    intent contract — subcommand OR natural-language need; empty → menu + WAIT."""
    section = _arguments_section()
    assert "$ARGUMENTS" in section, "Arguments section must reference the $ARGUMENTS placeholder"
    # subcommand set: the semantic subcommands named in the contract
    for sub in ("init", "analysis", "verify", "resume"):
        assert sub in section, f"Arguments section must list the `{sub}` subcommand"
    # natural-language mapping rule: keyword -> subcommand
    assert "keyword" in section.lower() or "intent" in section.lower(), \
        "Arguments section must state the natural-language intent-mapping rule"
    # workspace is NEVER a parameter (Phase 0 auto-detection)
    assert "never a parameter" in section.lower() or "workspace is not a parameter" in section.lower(), \
        "Arguments section must state that workspace is never a parameter (Phase 0 auto-detection)"
    # #413: empty $ARGUMENTS prints the menu and WAITs — it does NOT silently run
    assert "wait" in section.lower(), "Arguments section must say to WAIT on empty $ARGUMENTS"
    assert "menu" in section.lower(), "Arguments section must print the subcommand menu on empty $ARGUMENTS"


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
