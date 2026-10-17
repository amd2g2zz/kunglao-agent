#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_template_hygiene_674.py — deployed-copy version receipt (issue 674).

The workspace-deployed copy of template_version.py resolves its own root
as <ws>/.claude — where neither repo version asset exists by design (the
deploy manifest ships neither). Every ws-side consumer that left
skill_version=None then raised instead of returning a verdict, crashing
the version-consistency gate of the deployed convergence_check.py.
Resolution order under test: pyproject.toml -> .claude-plugin/plugin.json
-> deployed-manifest.json source_version (the deploy machinery's own
receipt) -> raise (guard unchanged).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import template_version as tv  # noqa: E402


def _deployed_root(tmp_path: Path, version: str = "9.9.9") -> Path:
    """A deployed-form root: the manifest carrier, no repo version assets."""
    root = tmp_path / "ws" / ".claude"
    root.mkdir(parents=True)
    (root / "deployed-manifest.json").write_text(
        json.dumps({"schema_version": 3, "source_version": version,
                    "entries": 0, "dests": []}),
        encoding="utf-8")
    return root


def test_deployed_copy_resolves_skill_version_with_manifest_fallback(
        tmp_path, monkeypatch):
    """The deployed form (no pyproject, no plugin.json) resolves the receipt."""
    monkeypatch.setattr(tv, "_REPO_ROOT", _deployed_root(tmp_path))
    assert tv.read_skill_version() == "9.9.9"


def test_skill_tree_pyproject_keeps_priority(tmp_path, monkeypatch):
    """Skill-tree behavior is unchanged: pyproject still wins when present."""
    root = _deployed_root(tmp_path, version="9.9.9")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "kunglao-agent"\nversion = "1.2.3"\n',
        encoding="utf-8")
    monkeypatch.setattr(tv, "_REPO_ROOT", root)
    assert tv.read_skill_version() == "1.2.3"


def test_version_guard_unchanged_when_no_source(tmp_path, monkeypatch):
    """No source anywhere still raises — the release-defect guard stands."""
    root = tmp_path / "bare"
    root.mkdir()
    monkeypatch.setattr(tv, "_REPO_ROOT", root)
    with pytest.raises(RuntimeError, match="no skill version found"):
        tv.read_skill_version()


def test_corrupt_manifest_falls_through_to_guard(tmp_path, monkeypatch):
    """An unreadable carrier is treated as absent, not as a crash path."""
    root = _deployed_root(tmp_path)
    (root / "deployed-manifest.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(tv, "_REPO_ROOT", root)
    with pytest.raises(RuntimeError, match="no skill version found"):
        tv.read_skill_version()


def test_convergence_check_no_crash_on_deployed_copy(tmp_path, monkeypatch):
    """The deployed-copy traceback from issue 674 is gone: the workspace
    gate resolves a verdict (pass here — stamp == receipt) instead of
    raising out of the version-consistency check."""
    import convergence_check as cc

    root = _deployed_root(tmp_path, version="9.9.9")
    monkeypatch.setattr(tv, "_REPO_ROOT", root)
    ws = tmp_path / "ws"
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions: []\n", encoding="utf-8")
    (ws / "CLAUDE.md").write_text(
        "# kunglao_template_version: 9.9.9\n\n# workspace body\n",
        encoding="utf-8")
    resolved = cc._require_workspace(str(ws))
    assert resolved == ws.resolve()


def test_convergence_check_reports_mismatch_as_verdict(tmp_path, monkeypatch):
    """The deployed-copy mismatch half of the gate: a workspace stamped
    with a different version exits with the upgrade-path verdict byte —
    still never a version-resolution RuntimeError."""
    import convergence_check as cc

    root = _deployed_root(tmp_path, version="9.9.9")
    monkeypatch.setattr(tv, "_REPO_ROOT", root)
    ws = tmp_path / "ws-mismatch"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions: []\n", encoding="utf-8")
    (ws / "CLAUDE.md").write_text(
        "# kunglao_template_version: 8.8.8\n\n# workspace body\n",
        encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cc._require_workspace(str(ws))
    assert excinfo.value.code == cc.EXIT_VERSION_MISMATCH
