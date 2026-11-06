# -*- coding: utf-8 -*-
"""The resume handoff contract is ONE split, stated three times.

The CLI (scripts/kunglao_resume.py) is read-only; the slash command owns
the follow-through. This file pins the three statements to each other:

  1. the skill's exit table and its handoff section say the same split;
  2. the CLI docstring states the same split;
  3. the skill's handoff section covers every decision the CLI's lookup
     table can emit;
  4. the observed regression state (expired activation TTL plus a
     DISPATCH_VERIFIER decision) has a prescribed order: renew the TTL
     first, then dispatch the verifier.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "resume" / "SKILL.md"
ROOT_SKILL = ROOT / "skills" / "kunglao-agent" / "SKILL.md"
CLI = ROOT / "scripts" / "kunglao_resume.py"
sys.path.insert(0, str(ROOT / "scripts"))


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def _cli_doc() -> str:
    return ast.get_docstring(ast.parse(CLI.read_text(encoding="utf-8"))) or ""


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start: len(text) if nxt == -1 else nxt]


def test_exit_table_states_the_split():
    table = _section(_skill(), "## Exit codes")
    rc0 = next(line for line in table.splitlines() if line.startswith("| 0 |"))
    assert "COMMAND" in rc0 and "CLI" in rc0, rc0


def test_handoff_section_names_cli_readonly_and_command_actions():
    section = _section(_skill(), "## Handoff contract")
    # the CLI face
    assert "READ-ONLY" in section.upper()
    assert "renews no TTL" in section
    # the safe preconditions
    assert "--renew" in section
    assert "never auto-dispatch" in section
    # the explicit handoff instead of a silent stop
    assert "/kunglao-agent analysis" in section


def test_cli_docstring_matches_the_split():
    doc = _cli_doc()
    assert "READ-ONLY CONTRACT" in doc
    assert "HANDOFF CONTRACT" in doc
    assert "never follows through" in doc
    assert "COMMAND" in doc
    assert "RC_RESUMABLE" in doc


def _mapped_decisions(section: str) -> set[str]:
    """The backticked decision tokens carrying an arrow mapping in the
    numbered next-step block.

    A plain substring check is not enough: ``DISPATCH`` is a prefix of
    ``DISPATCH_VERIFIER``, so deleting the real mapping row would still
    pass. The mapping SHAPE (``\\`DECISION\\` →``) is what the command acts
    on, so that is what gets extracted and compared.
    """
    return set(re.findall(r"`([A-Z_]+)`\s*→", section))


def test_skill_maps_every_decision_and_no_extra():
    """Bidirectional: every CLI decision has an arrow mapping in the
    skill, and the skill maps no decision the CLI cannot emit."""
    import kunglao_resume  # the module's lookup table
    section = _section(_skill(), "## Handoff contract")
    mapped = _mapped_decisions(section)
    expected = set(kunglao_resume.NEXT_STEP_BY_DECISION)
    assert mapped == expected, (
        f"decision-mapping drift: skill={sorted(mapped)} "
        f"cli={sorted(expected)}")


def test_frontmatter_scopes_the_read_only_claim_to_the_cli():
    """The discovery-time description must not claim the WHOLE command is
    write-free: the command renews an expired TTL (a write)."""
    frontmatter = _skill().split("---", 2)[1]
    flat = " ".join(frontmatter.split())
    assert "CLI never writes" in flat, flat
    assert "Never writes —" not in flat, (
        "the unqualified 'Never writes' claim contradicts the renew step")


def test_root_skill_example_scopes_the_read_only_claim():
    """The root skill's Examples line is a discovery surface too: it must
    scope read-only to the CLI and name the command's follow-through."""
    text = ROOT_SKILL.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines()
                if "/kunglao-agent resume" in ln)
    assert "the CLI never writes" in line, line
    assert "(never writes" not in line, line
    assert "command" in line.lower(), line


def test_regression_fixture_states_the_prescribed_order():
    """The observed workspace state: activation TTL expired plus a
    DISPATCH_VERIFIER decision -> renew first, then dispatch the verifier."""
    section = _section(_skill(), "## Handoff contract")
    renew_at = section.find("--renew")
    verifier_at = section.find("DISPATCH_VERIFIER")
    assert renew_at != -1 and verifier_at != -1
    assert renew_at < verifier_at, (
        "the TTL renew precondition must precede the verifier dispatch")
    flat = " ".join(section.split()).lower()
    assert "expired" in flat and "renew" in flat
