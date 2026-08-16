# -*- coding: utf-8 -*-
"""tests/test_plugin_manifest.py — issue #366 minimal v0.1 plugin manifest (TDD).

Contract: kunglao-agent v0.1 ships a metadata-only plugin manifest so version
0.1 is visible to the Claude Code plugin manager. Scope is minimal by
design (#366): identity fields only, NO component wiring (skills/hooks/
commands — that migration is #364, v1.0 track).

Facts guarded here:
1. .claude-plugin/plugin.json exists with name/description/version/author/
   homepage/license — exactly the #366 field set, no behavioral surface.
2. Version triple-equality: pyproject.toml == release-manifest.yaml ==
   plugin.json == CHANGELOG [0.1] (single source stays pyproject).
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
try:  # tomllib is 3.11+ stdlib; tomli backfill keeps tests on the 3.10 floor (#352)
    import tomllib
except ImportError:
    import tomli as tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
PYPROJECT = ROOT / "pyproject.toml"
RELEASE_MANIFEST = ROOT / "release-manifest.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"

EXPECTED_VERSION = "0.1.1"
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
    cl = re.search(r"^## \[0\.1\.1\]", changelog, re.MULTILINE)
    assert cl, "CHANGELOG missing the [0.1.1] header"

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

# ---------- marketplace.json (v0.1 ships it, issue #352) ----------

MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
GITHUB_URL = "https://github.com/amd2g2zz/kunglao-agent"

# Schema source: https://code.claude.com/docs/en/plugin-marketplaces
# ("Marketplace schema"). Top-level REQUIRED: name, owner (object, name
# required), plugins. Plugin entry REQUIRED: name, source; the standard
# metadata fields (description/version/author/homepage/license) are optional
# per-entry. `source` must be a schema-conformant source spec — a git URL is
# encoded as {"source": "url", "url": ...}, never as a bare string (a bare
# string is a relative-path source).
MARKETPLACE_REQUIRED_TOP = {"name", "owner", "plugins"}
MARKETPLACE_REQUIRED_OWNER = {"name"}
MARKETPLACE_REQUIRED_ENTRY = {"name", "source"}


def _marketplace() -> dict:
    assert MARKETPLACE.exists(), \
        ".claude-plugin/marketplace.json missing (v0.1 ships it, issue #352)"
    return json.loads(MARKETPLACE.read_text(encoding="utf-8"))


def test_marketplace_exists_with_identity():
    mp = _marketplace()
    assert mp["name"] == "kunglao-agent", "marketplace name (kebab-case id)"
    assert mp["owner"]["name"] == "amd2g2zz", "marketplace owner"


def test_marketplace_schema_required_fields_present():
    """Schema pin: every field the plugin-marketplaces schema marks REQUIRED
    is present at its level (top / owner / plugin entry)."""
    mp = _marketplace()
    assert MARKETPLACE_REQUIRED_TOP <= set(mp), (
        f"marketplace keys {sorted(set(mp))} missing required "
        f"{sorted(MARKETPLACE_REQUIRED_TOP - set(mp))}"
    )
    assert MARKETPLACE_REQUIRED_OWNER <= set(mp["owner"])
    assert len(mp["plugins"]) == 1, "v0.1 marketplace ships exactly one plugin"
    assert MARKETPLACE_REQUIRED_ENTRY <= set(mp["plugins"][0])


def test_marketplace_plugin_entry_matches_plugin_json():
    """The marketplace entry mirrors the shipped metadata-only manifest
    (#366): same identity, version pinned to 0.1, source is the GitHub URL
    in schema-conformant url-source form."""
    mp = _marketplace()
    m = _manifest()
    entry = mp["plugins"][0]
    assert entry["name"] == "kunglao-agent"
    assert entry["source"] == {"source": "url", "url": GITHUB_URL}, (
        "plugin source must be the GitHub URL as a url-type source spec"
    )
    assert entry["version"] == EXPECTED_VERSION
    assert isinstance(entry["description"], str) and entry["description"].strip()
    assert entry["description"] == m["description"], (
        "marketplace description must be the README opening one-liner "
        "(same string as plugin.json)"
    )
    assert entry["author"]["name"] == m["author"]["name"]
    assert entry["homepage"] == m["homepage"]
    assert entry["license"] == m["license"]


def test_marketplace_declared_in_release_manifest():
    """Declaration-scan contract: shipped assets get receipt digests. The
    marketplace catalog is shipped knowledge, declared under assets.knowledge
    next to plugin.json."""
    release = yaml.safe_load(RELEASE_MANIFEST.read_text(encoding="utf-8"))
    declared = release["assets"].get("knowledge", [])
    assert ".claude-plugin/marketplace.json" in declared, (
        "release-manifest.yaml assets.knowledge must declare "
        ".claude-plugin/marketplace.json (declaration-scan contract, #352)"
    )


# ---------- README: project-intro rewrite pins (issue #352) ----------

def test_readme_documents_marketplace_install_path():
    """The marketplace add command is the primary install path (verified
    against https://code.claude.com/docs/en/plugin-marketplaces —
    `/plugin marketplace add owner/repo`)."""
    text = README.read_text(encoding="utf-8")
    assert "/plugin marketplace add amd2g2zz/kunglao-agent" in text, \
        "README must document the marketplace add command as the primary path"


def test_readme_states_python310_and_rejects_python2():
    text = README.read_text(encoding="utf-8")
    assert "Python 3.10" in text, "README must state the Python 3.10+ floor"
    assert "Python 2 is not supported" in text, (
        "README must state plainly that Python 2 is not supported"
    )


def test_readme_has_worked_analysis_case():
    """The missing 案例分析: a walkthrough section labeled as synthetic."""
    text = README.read_text(encoding="utf-8")
    assert "## A worked analysis case" in text, \
        "README must carry the worked analysis walkthrough section"
    assert "synthetic" in text, (
        "the worked case must be labeled representative/synthetic, "
        "not presented as a real measured result"
    )
