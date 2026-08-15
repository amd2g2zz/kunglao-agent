# -*- coding: utf-8 -*-
"""tests/test_plugin_manifest.py — issue #366 minimal v0.1 plugin manifest (TDD).

Contract: kunglao-agent v0.1 ships a metadata-only plugin manifest so version
0.1.0 is visible to the Claude Code plugin manager. Scope is minimal by
design (#366): identity fields only, NO component wiring (skills/hooks/
commands — that migration is #364, v1.0 track).

Facts guarded here:
1. .claude-plugin/plugin.json exists with name/description/version/author/
   homepage/license — exactly the #366 field set, no behavioral surface.
2. Version triple-equality: pyproject.toml == release-manifest.yaml ==
   plugin.json == CHANGELOG [0.1.0] (single source stays pyproject).
3. README.md documents BOTH install paths: plugin (skills-directory, via the
   manifest) and the existing skill-dir clone path.
4. The manifest is metadata-only: it declares no component paths (the
   7f5f179 breakage came from `skills: ["./"]`, not from metadata).

Supersedes the #93 "no .claude-plugin/" guard (user decision 2026-08-15,
issue #366): a metadata-only manifest does not change skill identity for
plain-skill installs; the amended guard lives in test_skill_invocation.py.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
PYPROJECT = ROOT / "pyproject.toml"
RELEASE_MANIFEST = ROOT / "release-manifest.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"

EXPECTED_VERSION = "0.1.0"
# The #366 field set: identity metadata only (issue body scope item 1).
REQUIRED_FIELDS = {"name", "description", "version", "author", "homepage", "license"}
# Component-path fields that would change runtime behavior (#364, not #366).
FORBIDDEN_FIELDS = {"skills", "commands", "agents", "hooks", "mcpServers",
                    "lspServers", "outputStyles", "workflows"}


def _manifest() -> dict:
    assert PLUGIN_MANIFEST.exists(), \
        ".claude-plugin/plugin.json missing (issue #366 v0.1 deliverable)"
    return json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))


# ---------- manifest exists and is minimal ----------

def test_manifest_exists_and_minimal():
    m = _manifest()
    assert m["name"] == "kunglao-agent"
    assert m["version"] == EXPECTED_VERSION
    assert isinstance(m["description"], str) and m["description"].strip()
    assert m["author"].get("name"), "author.name missing"
    assert m["homepage"].startswith("https://"), "homepage must be an https URL"
    assert m["license"] == "MIT"


def test_manifest_declares_only_the_366_field_set():
    """Schema pin: exactly the #366 fields, no component wiring.

    Required fields absent → manifest invalid; component fields present →
    scope creep into #364 (behavioral surface must soak before v1.0).
    """
    m = _manifest()
    assert set(m) == REQUIRED_FIELDS, (
        f"manifest keys {sorted(set(m))} != #366 field set {sorted(REQUIRED_FIELDS)}"
    )


def test_manifest_forbids_component_paths():
    m = _manifest()
    forbidden = sorted(FORBIDDEN_FIELDS & set(m))
    assert not forbidden, (
        f"manifest declares component fields {forbidden} — that is #364 "
        f"(behavioral surface), out of #366 scope"
    )


def test_manifest_description_is_readme_one_liner():
    m = _manifest()
    text = README.read_text(encoding="utf-8")
    match = re.search(r"^# kunglao-agent\n\n(.+)$", text, re.MULTILINE)
    assert match, "README opening one-liner not found"
    assert m["description"] == match.group(1).strip(), (
        "plugin.json description must be the README opening one-liner"
    )


# ---------- version triple-equality ----------

def test_version_triple_equality():
    manifest = _manifest()
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    release = yaml.safe_load(RELEASE_MANIFEST.read_text(encoding="utf-8"))
    changelog = CHANGELOG.read_text(encoding="utf-8")

    py = pyproject["project"]["version"]
    rel = release["version"]
    cl = re.search(r"^## \[0\.1\.0\]", changelog, re.MULTILINE)
    assert cl, "CHANGELOG missing the [0.1.0] header"

    assert py == rel == manifest["version"] == EXPECTED_VERSION, (
        f"version drift: pyproject={py} release-manifest={rel} "
        f"plugin.json={manifest['version']}"
    )


# ---------- README documents both install paths ----------

def test_readme_documents_install():
    text = README.read_text(encoding="utf-8")
    assert "## Quick start" in text and "### 1. Install" in text, \
        "README missing the Quick start install section anchor"
    # (a) plugin path — via the shipped .claude-plugin/plugin.json
    assert ".claude-plugin/plugin.json" in text, \
        "README must document the plugin install path (via the manifest)"
    assert "/plugin marketplace" in text or "--plugin-dir" in text, \
        "README plugin path must show the install mechanism"
    # (b) legacy skill-dir clone path (kept from the original docs)
    assert "~/.claude/skills/kunglao-agent" in text, \
        "README must keep the legacy skill-dir clone path"


def test_readme_no_longer_forbids_claude_plugin():
    """#366 supersedes the #93 README prohibition — the shipped manifest is
    metadata-only, so the blanket 'Do NOT add .claude-plugin/' warning is
    stale. A scoped warning (no component fields) may remain."""
    text = README.read_text(encoding="utf-8")
    assert "Do NOT add a `.claude-plugin/` directory" not in text


# ---------- release-manifest knowledge declaration ----------

def test_plugin_manifest_declared_in_release_manifest():
    """Declaration-scan contract: shipped assets get receipt digests. The
    plugin manifest is shipped knowledge (identity metadata), declared under
    assets.knowledge so release_receipt --check covers it."""
    release = yaml.safe_load(RELEASE_MANIFEST.read_text(encoding="utf-8"))
    declared = release["assets"].get("knowledge", [])
    assert ".claude-plugin/plugin.json" in declared, (
        "release-manifest.yaml assets.knowledge must declare "
        ".claude-plugin/plugin.json (declaration-scan contract, #366)"
    )
