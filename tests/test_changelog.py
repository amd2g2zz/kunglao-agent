# -*- coding: utf-8 -*-
"""tests/test_changelog.py — issue #352 release v0.1 contract (TDD).

Contract: CHANGELOG.md exists as the single first-release record (Keep a
Changelog 1.1), declares [0.1], covers Added/Changed/Fixed, and folds the
internal v1.9.x iteration markers into a mapping section; the two real
version sources (pyproject.toml + release-manifest.yaml) read 0.1.
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


def test_changelog_has_internal_version_mapping():
    text = _changelog_text()
    assert "Internal version mapping" in text, "missing internal-version mapping section"
    # The mapping must cover the top historical markers (v1.9.29/v1.9.24) and
    # state that they belong to v0.1 scope.
    assert "v1.9.29" in text and "v1.9.24" in text
    assert "0.1" in text


# ---------- Added-section reference format ----------

def test_changelog_references_issue_numbers():
    text = _changelog_text()
    added = text.split("### Added", 1)[1].split("### ", 1)[0]
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
    assert expected == "0.1.3", f"pyproject version is {expected}, expected 0.1.3"

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == expected, \
        f"release-manifest version is {manifest['version']}, expected {expected}"
