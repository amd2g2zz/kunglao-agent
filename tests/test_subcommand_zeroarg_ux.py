# -*- coding: utf-8 -*-
"""Issue #456 — subcommand zero-args behavior + hint richness (TDD).

#413 guarded the PARENT router only: `/kunglao-agent` with no args prints
the menu and waits. But every sub-skill is an independent slash command in
Claude Code — a bare `/kunglao-agent:init` or `/kunglao-agent:analysis`
bypasses that guard, and their SKILL.md files prescribe NO no-args action,
so the agent improvises (ask? guess cwd? forward an env_check error?).
The router also self-contradicts — "The workspace is never a parameter:
workspace detection runs in Phase 0" next to a menu that says
`analysis <workspace>` — and the same sentence is duplicated in the main
contract. Hints are thin (analysis has no `analyze` alias and no zero-args
guidance; the menu has no per-command examples or next-step guidance).

RED on baseline (dev @ 6462fe4): no skills/subcommands.yaml, no
'## No arguments' sections in init/analysis/help, the contradiction
sentence in TWO SKILL.md copies, hints without zero-args guidance, menu
without examples or next steps. Every test here fails until the #456
contract lands (help's frontmatter hint already exists — that one assert
is an anchor, the rest of its section test is red).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
REGISTRY_FILE = SKILLS / "subcommands.yaml"
MAIN = SKILLS / "kunglao-agent" / "SKILL.md"
INIT = SKILLS / "init" / "SKILL.md"
ANALYSIS = SKILLS / "analysis" / "SKILL.md"
RESUME = SKILLS / "resume" / "SKILL.md"
HELP = SKILLS / "help" / "SKILL.md"
ROOT_SKILL = ROOT / "SKILL.md"
README = ROOT / "README.md"

# every registry record must carry these keys (design D4)
REGISTRY_FIELDS = {
    "invocation", "argument-hint", "zero-args", "missing-args",
    "example", "next-step",
}


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


def _registry() -> dict:
    """Load THE single source (skills/subcommands.yaml)."""
    assert REGISTRY_FILE.is_file(), (
        f"missing single source: {REGISTRY_FILE.relative_to(ROOT)} (design D4)")
    data = yaml.safe_load(REGISTRY_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data.get("subcommands"), dict), \
        "subcommands.yaml must be a mapping under the 'subcommands' key"
    return data["subcommands"]


def _invocation_args(invocation: str) -> str:
    """`/kunglao-agent:init <workspace> [--type ...]` -> `<workspace> [--type ...]`."""
    parts = invocation.split(None, 1)
    return parts[1] if len(parts) > 1 else ""


def _no_args_section(body: str) -> str:
    """Extract the '## No arguments' section body (up to the next ## heading)."""
    m = re.search(r"^## No arguments.*?$(.*?)(?=^## )", body, re.S | re.M)
    assert m, "missing a '## No arguments' section (prescribed zero-args action)"
    return m.group(1)


# ---------------------------------------------------------------------------
# 1. single source — skills/subcommands.yaml and its three render surfaces
# ---------------------------------------------------------------------------

def test_registry_exists_and_covers_all_subcommands() -> None:
    """THE single source exists, parses, and covers init / analysis / help
    with every D4 field."""
    reg = _registry()
    # #466: resume joined the surface — the four-command set; #746 added
    # upgrade to the user-facing slash-command UX surface (the CLI was
    # workspace-internal via #726, now promoted per user 2026-08-26).
    assert set(reg) == {"init", "analysis", "help", "resume", "upgrade"}, (
        f"registry must cover exactly the skills/ subcommands: {sorted(reg)}")
    for name, rec in reg.items():
        assert isinstance(rec, dict), f"registry[{name}] must be a mapping"
        missing = REGISTRY_FIELDS - set(rec)
        assert not missing, f"registry[{name}] missing fields: {sorted(missing)}"
        for field in REGISTRY_FIELDS:
            assert str(rec[field]).strip(), f"registry[{name}][{field}] is empty"


def test_registry_zero_args_actions_are_guided() -> None:
    """Zero-args actions in the registry are guided prompts
    (init/analysis/resume — review F5: resume pinned like its siblings, the
    resume SKILL.md section test alone covered it only indirectly) or the
    usage list (help) — never a bare error, never a silent guess."""
    reg = _registry()
    for name in ("init", "analysis", "resume"):
        assert "guided" in str(reg[name]["zero-args"]).lower(), (
            f"registry[{name}][zero-args] must be a guided prompt")
    assert "usage list" in str(reg["help"]["zero-args"]).lower()


def test_root_menu_renders_registry_invocations_and_examples() -> None:
    """The root router menu carries every registry invocation (command token
    + args) and every per-command example — the menu is a render of the
    single source, not a hand-drifted copy."""
    body = _body(ROOT_SKILL)
    m = re.search(r"^## No arguments.*?$(.*?)(?=^## )", body, re.S | re.M)
    assert m, "root SKILL.md must keep the no-args menu section"
    menu = m.group(1)
    for name, rec in _registry().items():
        command = rec["invocation"].split(None, 1)[0]
        assert command in menu, f"menu missing registry command: {command}"
        args = _invocation_args(str(rec["invocation"]))
        if args:
            assert args in menu, f"menu missing args for {command}: {args}"
        assert str(rec["example"]) in menu, (
            f"menu missing per-command example for {command}: {rec['example']}")


def test_root_menu_has_next_steps_guidance() -> None:
    """The menu ends with next-step guidance mapping operator state to a
    command: uninitialized -> init, initialized -> analysis, unsure -> help."""
    body = _body(ROOT_SKILL)
    assert "next steps" in body.lower(), "menu missing a Next steps block"
    for state, command in (
        ("uninitialized", "/kunglao-agent:init"),
        ("initialized", "/kunglao-agent:analysis"),
        ("unsure", "/kunglao-agent:help"),
    ):
        assert state in body.lower(), f"next-steps missing state: {state}"
        assert command in body, f"next-steps missing command for {state}: {command}"


def test_help_skill_usage_table_covers_registry() -> None:
    """Render surface D: the /kunglao-agent:help body's Usage table must
    cover every registry subcommand token plus its example. This table went
    stale during the upgrade promotion while every other render surface was
    linted — this closes that hole."""
    body = _body(HELP)
    m = re.search(r"^## Usage$(.*?)(?=^## )", body, re.S | re.M)
    assert m, "help SKILL.md must keep the ## Usage section"
    usage = m.group(1)
    for name, rec in _registry().items():
        command = rec["invocation"].split(None, 1)[0]
        assert command in usage, (
            f"help SKILL.md Usage table missing registry command: {command}")
        assert str(rec["example"]) in usage, (
            f"help SKILL.md missing example for {command}: {rec['example']}")


def test_subcommand_hints_equal_registry_hints() -> None:
    """Render surface B: each subcommand frontmatter argument-hint equals the
    registry hint EXACTLY (a mirror is what drifted in #413 — init had a
    hint, analysis did not)."""
    reg = _registry()
    for name in ("init", "analysis", "help", "resume", "upgrade"):
        hint = _frontmatter(SKILLS / name / "SKILL.md").get("argument-hint")
        assert hint == reg[name]["argument-hint"], (
            f"skills/{name}/SKILL.md argument-hint drifts from subcommands.yaml: "
            f"{hint!r} != {reg[name]['argument-hint']!r}")


def test_readme_command_table_matches_registry() -> None:
    """Render surface C: the README Command Reference covers every registry
    command with an args cell consistent with the registry invocation."""
    readme = README.read_text(encoding="utf-8")
    assert "Command Reference" in readme, "README missing Command Reference heading"
    for name, rec in _registry().items():
        command = rec["invocation"].split(None, 1)[0]
        row = f"`{command}`"
        assert row in readme, f"README command table missing row: {row}"
        args = _invocation_args(str(rec["invocation"]))
        if args:
            # README table cells escape pipes
            assert args.replace("|", r"\|") in readme, (
                f"README args cell for {command} does not match the registry: {args}")


# ---------------------------------------------------------------------------
# 2. zero-args behavior defined in every subcommand (below-router guard)
# ---------------------------------------------------------------------------

def test_init_no_args_section_is_defined() -> None:
    """/kunglao-agent:init bare: a '## No arguments' section prescribes the
    guided action — never a bare argparse-style error, never a guess."""
    raw = _no_args_section(_body(INIT))
    sec = raw.lower()
    assert "guided" in sec, "init no-args section must prescribe a guided prompt"
    assert "never guess" in sec, "init no-args section must forbid guessing"
    assert "$ARGUMENTS" in raw, (
        "init no-args section must consume the $ARGUMENTS placeholder")


def test_analysis_no_args_section_is_defined() -> None:
    """/kunglao-agent:analysis bare: guided workspace prompt; a cwd candidate
    may be PROPOSED but must be confirmed — never silently run on it."""
    sec = _no_args_section(_body(ANALYSIS)).lower()
    assert "guided" in sec, "analysis no-args section must prescribe a guided prompt"
    assert "confirm" in sec, "a cwd candidate must be confirmed, not assumed"
    assert "never guess" in sec, "analysis no-args section must forbid guessing"


def test_help_no_args_section_is_defined() -> None:
    """/kunglao-agent:help takes no arguments — its zero-args case IS the
    usage list; pin it so the definition cannot rot."""
    sec = _no_args_section(_body(HELP)).lower()
    assert "usage list" in sec


def test_subcommands_carry_never_guess_guards() -> None:
    """The #413 'menu, WAIT, never guess' guard extended below the router:
    every argument-taking subcommand states it in its body."""
    for path in (INIT, ANALYSIS, RESUME):
        assert "never guess" in _body(path).lower(), (
            f"{path.relative_to(ROOT)} missing the never-guess guard")


# ---------------------------------------------------------------------------
# 3. partial args — defined interaction order
# ---------------------------------------------------------------------------

def test_init_missing_type_routes_to_455_intake() -> None:
    """init <workspace> without --type must NOT silently default to windows;
    it routes into the #455 intake type-alignment sequence (sniff -> confirm,
    ambiguity surfaced as a decision_pending concept)."""
    body = _body(INIT)
    assert re.search(r"missing .--type.", body, re.I), (
        "init SKILL.md missing a 'missing --type' branch")
    assert "intake type-alignment" in body or "type-alignment sequence" in body, (
        "the missing-type branch must route to the intake type-alignment sequence")
    assert re.search(r"never silently default", body, re.I), (
        "init must explicitly forbid silently defaulting the type")


def test_analysis_missing_workspace_is_the_zero_args_case() -> None:
    """analysis takes exactly one positional — a missing workspace is the
    zero-args case: guided prompt with an explicit cwd confirm."""
    body = _body(ANALYSIS)
    sec = _no_args_section(body).lower()
    assert "workspace" in sec
    assert "cwd" in sec, "the guided prompt must state the cwd-candidate rule"


# ---------------------------------------------------------------------------
# 4. router contradiction removed — ONE workspace semantics
# ---------------------------------------------------------------------------

def test_never_a_parameter_phrase_is_gone() -> None:
    """The self-contradicting sentence must be gone from EVERY SKILL.md
    (it existed in both the root router and the main contract)."""
    for path in (ROOT_SKILL, MAIN, INIT, ANALYSIS, HELP):
        text = path.read_text(encoding="utf-8")
        assert "never a parameter" not in text.lower(), (
            f"{path.relative_to(ROOT)} still carries the contradictory "
            f"'never a parameter' sentence (#456 evidence 2)")


def test_workspace_explicit_positional_anchor_in_both_contracts() -> None:
    """ONE semantics, stated identically in the root router AND the main
    contract: the workspace is an explicit positional argument."""
    for path in (ROOT_SKILL, MAIN):
        body = _body(path)
        assert "explicit positional argument" in body.lower(), (
            f"{path.relative_to(ROOT)} missing the workspace-semantics anchor "
            f"('explicit positional argument')")


# ---------------------------------------------------------------------------
# 5. hint enrichment (issue evidence 3)
# ---------------------------------------------------------------------------

def test_analysis_hint_covers_alias_and_zero_args() -> None:
    """analysis hint: the undocumented `analyze` alias + zero-args guidance."""
    hint = str(_frontmatter(ANALYSIS).get("argument-hint", ""))
    assert "analyze" in hint, f"analysis hint missing the 'analyze' alias: {hint}"
    assert re.search(r"no args", hint, re.I), f"analysis hint missing zero-args guidance: {hint}"
    assert "guided" in hint.lower()


def test_init_hint_declares_zero_args_guidance() -> None:
    """init hint keeps the --type choices and adds zero-args guidance."""
    hint = str(_frontmatter(INIT).get("argument-hint", ""))
    for token in ("<workspace>", "--type", "windows", "linux", "android", "web"):
        assert token in hint, f"init hint lost '{token}': {hint}"
    assert re.search(r"no args", hint, re.I), f"init hint missing zero-args guidance: {hint}"
