# -*- coding: utf-8 -*-
"""tests/test_upgrade_slash_command_746.py — issue #746 slash-command surface.

Plan: `.claude/PRPs/plans/subplans/v013/upgrade-slash-command.plan.md`.

6 RED → GREEN cases covering:
  1. registry has upgrade entry (6 D4 fields, all non-empty)
  2. skills/upgrade/SKILL.md frontmatter name + argument-hint equal registry
  3. scripts/kunglao_upgrade.py main() accepts --json (RC=0 dry-run shape)
  4. scripts/kunglao_upgrade.py main() rejects un-stamped workspace (RC=3)
  5. root SKILL.md menu renders the upgrade command + args + example
  6. README.md Command Reference table has upgrade row
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
SUB_COMMANDS = SKILLS / "subcommands.yaml"
UPGRADE_SKILL = SKILLS / "upgrade" / "SKILL.md"
KUNGLAO_UPGRADE_PY = ROOT / "scripts" / "kunglao_upgrade.py"
ROOT_SKILL = ROOT / "SKILL.md"
README = ROOT / "README.md"

REGISTRY_FIELDS = {
    "invocation", "argument-hint", "zero-args", "missing-args",
    "example", "next-step",
}


# ---------------------------------------------------------------------------
# 1. registry has upgrade entry (6 D4 fields, all non-empty)
# ---------------------------------------------------------------------------

def test_subcommands_yaml_has_upgrade_entry() -> None:
    """Single source has upgrade entry covering the D4 contract."""
    data = yaml.safe_load(SUB_COMMANDS.read_text(encoding="utf-8"))
    reg = data["subcommands"]
    assert "upgrade" in reg, "registry missing 'upgrade' entry"
    rec = reg["upgrade"]
    assert isinstance(rec, dict)
    missing = REGISTRY_FIELDS - set(rec)
    assert not missing, f"registry['upgrade'] missing fields: {sorted(missing)}"
    for field in REGISTRY_FIELDS:
        assert str(rec[field]).strip(), f"registry['upgrade'][{field}] is empty"
    assert rec["invocation"].startswith("/kunglao-agent:upgrade"), (
        f"invocation must use the namespaced slash-command form: "
        f"{rec['invocation']!r}")


# ---------------------------------------------------------------------------
# 2. skills/upgrade/SKILL.md frontmatter mirrors registry
# ---------------------------------------------------------------------------

def test_skills_upgrade_skill_md_mirrors_registry() -> None:
    """Render surface B (skill frontmatter) equals registry hint EXACTLY."""
    text = UPGRADE_SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "skills/upgrade/SKILL.md must start with YAML frontmatter"
    end = text.find("\n---\n", 4)
    assert end > 0, "skills/upgrade/SKILL.md frontmatter must close with ---"
    fm = yaml.safe_load(text[4:end])
    reg = yaml.safe_load(SUB_COMMANDS.read_text(encoding="utf-8"))["subcommands"]
    assert fm.get("name") == "kunglao-agent:upgrade", (
        f"frontmatter name drifts: {fm.get('name')!r}")
    assert fm.get("argument-hint") == reg["upgrade"]["argument-hint"], (
        f"argument-hint drifts from registry: "
        f"{fm.get('argument-hint')!r} != {reg['upgrade']['argument-hint']!r}")
    # body must include the prescribed "No arguments" section per #456
    body = text[end + 5:]
    assert "## No arguments" in body, (
        "skills/upgrade/SKILL.md missing '## No arguments' section "
        "(prescribed by #456 zero-args contract)")


# ---------------------------------------------------------------------------
# 3. --json flag returns a parseable envelope on RC=0 dry-run
# ---------------------------------------------------------------------------

def test_kunglao_upgrade_main_accepts_json_dry_run(tmp_path: Path) -> None:
    """--json on a workspace with a trailing version stamp returns
    `status=dry-run, rc=0, items=[...]` parseable JSON envelope."""
    # Stamp the workspace at a trailing version so the dry-run has migrations to list.
    (tmp_path / "CLAUDE.md").write_text(
        "# kunglao_template_version: 0.1.0\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(KUNGLAO_UPGRADE_PY), str(tmp_path),
         "--dry-run", "--json"],
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, (
        f"dry-run RC must be 0, got {proc.returncode}: "
        f"stdout={proc.stdout[-200:]} stderr={proc.stderr[-200:]}")
    # Stdout should contain a parseable JSON envelope (other human-readable
    # output, if any, must come from stderr only — see #317 UTF-8 contract).
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["status"] == "dry-run", envelope
    assert envelope["rc"] == 0
    assert isinstance(envelope["items"], list)
    assert len(envelope["items"]) > 0, "dry-run must list at least one item"
    for it in envelope["items"]:
        assert {"name", "action", "detail"} <= set(it), it
        assert it["action"] == "noop", (
            f"dry-run items must report action=noop, got {it['action']}")
    assert envelope["iron_rule_hash"] == {"pre": "", "post": ""}, envelope
    assert envelope["started_at"] and envelope["ended_at"]


# ---------------------------------------------------------------------------
# 4. --json returns status=refused, rc=3 for an un-stamped workspace
# ---------------------------------------------------------------------------

def test_kunglao_upgrade_main_json_refuses_unstamped(tmp_path: Path) -> None:
    """Workspace with no version stamp must return RC=3 with status=refused
    in the JSON envelope (the slash command SKILL.md directs the user to
    /kunglao-agent:init on this exit)."""
    proc = subprocess.run(
        [sys.executable, str(KUNGLAO_UPGRADE_PY), str(tmp_path), "--json"],
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 3, (
        f"un-stamped workspace must exit 3, got {proc.returncode}: "
        f"stderr={proc.stderr[-200:]}")
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["status"] == "refused"
    assert envelope["rc"] == 3
    assert envelope["items"] == []


# ---------------------------------------------------------------------------
# 5. root SKILL.md menu renders upgrade command + args + example
# ---------------------------------------------------------------------------

def test_root_skill_menu_renders_upgrade() -> None:
    """The root router menu must include the registry command, args, and example."""
    text = ROOT_SKILL.read_text(encoding="utf-8")
    reg = yaml.safe_load(SUB_COMMANDS.read_text(encoding="utf-8"))["subcommands"]
    up = reg["upgrade"]
    command = up["invocation"].split(None, 1)[0]
    assert command in text, f"root SKILL.md menu missing {command}"
    args = up["invocation"].split(None, 1)[1]
    assert args in text, f"root SKILL.md menu missing args: {args}"
    assert up["example"] in text, (
        f"root SKILL.md menu missing upgrade example: {up['example']}")
    # next-step mapping must mention legacy → upgrade
    assert "legacy" in text.lower() or "behind" in text.lower(), (
        "root SKILL.md next-steps missing legacy/behind mapping to upgrade")


# ---------------------------------------------------------------------------
# 6. README Command Reference has upgrade row
# ---------------------------------------------------------------------------

def test_readme_command_table_has_upgrade_row() -> None:
    """The README Subcommands table must include upgrade with args cell
    mirroring the registry invocation."""
    # 2026-09-06 re-pin (#96): the rewrite folds the args into the command's
    # own backtick span, so the bare `/kunglao-agent:upgrade` backticked
    # token is gone; pin the unbackticked token + registry args cell, and
    # keep the row's when-to-use semantics (after a plugin update).
    text = README.read_text(encoding="utf-8")
    reg = yaml.safe_load(SUB_COMMANDS.read_text(encoding="utf-8"))["subcommands"]
    up = reg["upgrade"]
    assert "/kunglao-agent:upgrade" in text, (
        "README Subcommands table missing /kunglao-agent:upgrade row")
    args = up["invocation"].split(None, 1)[1].replace("|", r"\|")
    assert args in text, (
        f"README upgrade row args cell does not match registry: {args}")
    assert "after a plugin update" in text, (
        "the upgrade row must state when to use it (after a plugin update)")