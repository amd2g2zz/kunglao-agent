# -*- coding: utf-8 -*-
"""tests/test_changelog.py — issue #352 release v0.1 contract (TDD).

Contract: CHANGELOG.md exists as the single first-release record (Keep a
Changelog 1.1), declares [0.1], and covers Added/Changed/Fixed. The
internal v1.9.x iteration markers were historical provenance only and
have been retired along with the `## Internal version mapping` section
(see PR #744); the two real version sources (pyproject.toml +
release-manifest.yaml) read the current release.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
PYPROJECT = ROOT / "pyproject.toml"
MANIFEST = ROOT / "release-manifest.yaml"


def _changelog_text() -> str:
    assert CHANGELOG.exists(), "CHANGELOG.md missing (issue #352 deliverable)"
    return CHANGELOG.read_text(encoding="utf-8")


# ---------- structure ----------

def test_changelog_declares_v0_1():
    text = _changelog_text()
    assert "# Changelog" in text, "missing top-level Changelog heading"
    assert "## [0.1] - 2026-08-16" in text, "missing [0.1] - 2026-08-16 section"
    v01 = text.split("## [0.1]", 1)[1]
    for sub in ("### Added", "### Changed", "### Fixed"):
        assert sub in v01, f"missing {sub} subsection under [0.1]"


def test_changelog_references_issue_numbers():
    text = _changelog_text()
    # scope to the [0.1] section: an Unreleased section (newer, first in the
    # file) must not inherit the v0.1 documentation-completeness invariant
    v01 = text.split("## [0.1]", 1)[1]
    added = v01.split("### Added", 1)[1].split("### ", 1)[0]
    bullets = [ln for ln in added.splitlines() if ln.startswith("- ")]
    assert len(bullets) >= 10, f"Added section too thin: {len(bullets)} bullets"
    missing = [ln for ln in bullets if not re.search(r"\(#[0-9]+\)", ln)]
    assert not missing, f"Added bullets without (#issue) reference: {missing}"


# ---------- version normalization ----------

def test_manifest_and_pyproject_are_0_1():
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert m, "pyproject.toml missing [project].version"
    expected = m.group(1)  # single source of truth: pyproject version
    # The pin is the UPCOMING release's candidate identity — dev declares its
    # own release identity (owner ruling 2026-09-27); the RC cycle carries the
    # rc suffix until the final bump.
    assert expected == "0.1.6-rc3", f"pyproject version is {expected}, expected 0.1.6-rc3"

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == expected, \
        f"release-manifest version is {manifest['version']}, expected {expected}"


# ---------- newest release section (contract; version-agnostic) ----------

def _latest_section() -> str:
    """The changelog section for the CURRENT pyproject version (the
    release cut renames [Unreleased] in place; the contract follows the
    version, never a fixed heading)."""
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match, "pyproject.toml missing [project].version"
    heading = f"## [{match.group(1)}] - "
    text = _changelog_text()
    assert heading in text, \
        f"missing changelog section for the current version {match.group(1)}"
    rest = text.split(heading, 1)[1]
    nxt = re.search(r"^## \[", rest, re.MULTILINE)
    return rest[:nxt.start()] if nxt else rest


def test_latest_section_shape():
    section = _latest_section()
    for sub in ("### Added", "### Changed", "### Fixed"):
        assert sub in section, f"missing {sub} under the current release"
    bullets = [ln for ln in section.splitlines() if ln.startswith("- ")]
    assert len(bullets) >= 12, \
        f"current release too thin: {len(bullets)} bullets"
    missing = [ln for ln in bullets if not re.search(r"\(#[0-9]+\)", ln)]
    assert not missing, \
        f"current-release bullets without a (#issue) reference: {missing}"


def test_latest_section_covers_all_waves_and_the_gate_reversal():
    section = _latest_section()
    for issue in ("791", "878", "951", "800", "801", "807", "977"):
        assert f"#{issue}" in section, \
            f"current release does not reference wave issue #{issue}"
    assert "SUPERSEDES" in section and "fail-closed" in section, \
        "the #801 gate-layering reversal must be recorded explicitly"
    for hard in ("corruption", "reward_integrity", "termination_budget",
                 "evidence", "execution_surface"):
        assert hard in section, f"missing HARD gate class: {hard}"
