# -*- coding: utf-8 -*-
"""Issue #413 — subcommand UX + guided entry contract (TDD).

The skill used to be a single root SKILL.md whose only hint was `[request]`:
operators did not know whether to type arguments or what they are. #413 moves
the plugin to the official `skills/` subdirectory layout — one skill directory
per command, namespace = plugin:skill (`/kunglao-agent:init`) — and adds a
command menu on no-args plus argument hints at autocomplete.

RED on baseline (dev @ 64040b3): no skills/ directory exists; root SKILL.md
argument-hint is `[request]`; empty $ARGUMENTS silently runs `analysis` (the
old #93 contract); README has no Command Reference table. Every test here
fails until the #413 layout + routing lands.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
MAIN = SKILLS / "kunglao-agent" / "SKILL.md"
INIT = SKILLS / "init" / "SKILL.md"
ANALYSIS = SKILLS / "analysis" / "SKILL.md"
HELP = SKILLS / "help" / "SKILL.md"
ROOT_SKILL = ROOT / "SKILL.md"
README = ROOT / "README.md"


def _frontmatter(path: Path) -> dict:
    """Parse a SKILL.md YAML frontmatter block (delimited by leading/trailing `---`)."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, f"{path.relative_to(ROOT)} must start with a YAML frontmatter block"
    fm = yaml.safe_load(m.group(1))
    assert isinstance(fm, dict), "frontmatter must parse to a mapping"
    return fm


def _body(path: Path) -> str:
    """SKILL.md body = everything after the frontmatter block."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
    assert m, f"{path.relative_to(ROOT)} must start with a YAML frontmatter block"
    return text[m.end():]


# ---------------------------------------------------------------------------
# 1. skills/ layout — the four skill files exist
# ---------------------------------------------------------------------------

def test_skills_layout_exists() -> None:
    """#413 moves the plugin to skills/: main + init + analysis + help."""
    for path in (MAIN, INIT, ANALYSIS, HELP):
        assert path.is_file(), f"missing skill file: {path.relative_to(ROOT)}"


def test_main_skill_is_the_full_contract() -> None:
    """The main skill keeps the convergence contract (reachable via
    /kunglao-agent:analysis and main-with-args)."""
    body = _body(MAIN)
    for kw in ("convergence", "dispatch", "Phase 0 Environment Probe"):
        assert kw in body, f"main skill missing contract keyword: {kw}"


# ---------------------------------------------------------------------------
# 2. argument-hint (shown at autocomplete) on every skill
# ---------------------------------------------------------------------------

def test_main_skill_argument_hint_lists_subcommands() -> None:
    """Main skill hint advertises the menu: init | analysis | help."""
    hint = str(_frontmatter(MAIN).get("argument-hint", ""))
    for token in ("init", "analysis", "help"):
        assert token in hint, f"main argument-hint missing '{token}': {hint}"


def test_init_skill_argument_hint() -> None:
    """/kunglao-agent:init hint: <workspace> [--type windows|linux|android]."""
    hint = str(_frontmatter(INIT).get("argument-hint", ""))
    assert "<workspace>" in hint, f"init argument-hint missing <workspace>: {hint}"
    assert "--type" in hint, f"init argument-hint missing --type: {hint}"
    for os_ in ("windows", "linux", "android"):
        assert os_ in hint, f"init argument-hint missing --type choice '{os_}': {hint}"


def test_analysis_skill_argument_hint() -> None:
    """/kunglao-agent:analysis hint: <workspace>."""
    hint = str(_frontmatter(ANALYSIS).get("argument-hint", ""))
    assert "<workspace>" in hint, f"analysis argument-hint missing <workspace>: {hint}"


def test_help_skill_argument_hint() -> None:
    """/kunglao-agent:help has a hint (usage list, no positional args)."""
    hint = str(_frontmatter(HELP).get("argument-hint", ""))
    assert hint, "help skill missing argument-hint"


# ---------------------------------------------------------------------------
# 3. main skill routing body — no args → menu + WAIT, unknown → menu + label
# ---------------------------------------------------------------------------

def test_main_skill_no_args_prints_menu_and_waits() -> None:
    """With no args the main skill MUST print the subcommand menu and WAIT —
    it must never silently run (the old empty→analysis default)."""
    body = _body(MAIN)
    assert "menu" in body.lower(), "main skill body must print a subcommand menu"
    assert "$ARGUMENTS" in body, "main skill body must consume the $ARGUMENTS placeholder"
    # no-args branch: prints menu and does NOT silently run
    m = re.search(r"no\s+args|empty", body, re.IGNORECASE)
    assert m, "main skill body must state the no-args branch"
    # WAIT / stop — the menu is an interaction point, not a dispatch
    assert "wait" in body.lower(), "main skill body must say to WAIT on no args"
    # the old silent default is gone
    assert "silently run" not in body.lower() or "never silently run" in body.lower(), \
        "main skill must explicitly forbid silently running on no args"


def test_main_skill_unknown_subcommand_prints_menu_and_label() -> None:
    """An unknown subcommand prints the menu plus 'unknown: <x>'."""
    body = _body(MAIN)
    assert "unknown" in body.lower(), "main skill body must handle unknown subcommands"
    assert "unknown:" in body.lower(), "main skill body must label the unknown token ('unknown: <x>')"


def test_main_skill_lists_analysis_subcommand() -> None:
    """The convergence loop stays reachable via the `analysis` subcommand."""
    body = _body(MAIN)
    assert "analysis" in body, "main skill body must list the analysis subcommand"


# ---------------------------------------------------------------------------
# 4. examples line per subcommand
# ---------------------------------------------------------------------------

def test_each_skill_has_examples_section() -> None:
    """Every skill carries an examples line per subcommand (usage guidance)."""
    for path in (MAIN, INIT, ANALYSIS, HELP):
        body = _body(path)
        assert "## Examples" in body, f"{path.relative_to(ROOT)} missing ## Examples section"


# ---------------------------------------------------------------------------
# 5. README Command Reference table
# ---------------------------------------------------------------------------

def test_readme_has_command_reference_table() -> None:
    """README documents a Command Reference table: command / args / purpose / example."""
    text = README.read_text(encoding="utf-8")
    assert "Command Reference" in text, "README missing Command Reference heading"
    m = re.search(r"\|\s*Command\s*\|\s*Args?\w*\s*\|\s*Purpose\s*\|\s*Example\s*\|", text)
    assert m, "README command table must have command/args/purpose/example columns"
    # the table covers all four commands
    table_region = text[m.end():]
    for cmd in ("`/kunglao-agent`", ":init", ":analysis", ":help"):
        assert cmd in text, f"README command table missing {cmd}"
    assert table_region.strip(), "README command table must have body rows"


# ---------------------------------------------------------------------------
# 6. root SKILL.md — skill-dir install router keeps the menu behavior
# ---------------------------------------------------------------------------

def test_root_skill_is_router_with_menu() -> None:
    """The root SKILL.md (skill-dir install path) also prints the menu on no
    args and routes to the skills/ subcommand files."""
    assert ROOT_SKILL.is_file(), "root SKILL.md must remain (skill-dir install router)"
    body = _body(ROOT_SKILL)
    assert "menu" in body.lower(), "root SKILL.md must print the subcommand menu"
    assert "skills/" in body, "root SKILL.md must route to the skills/ subcommand files"
    fm = _frontmatter(ROOT_SKILL)
    hint = str(fm.get("argument-hint", ""))
    for token in ("init", "analysis", "help"):
        assert token in hint, f"root argument-hint missing '{token}': {hint}"
