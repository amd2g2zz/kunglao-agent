# -*- coding: utf-8 -*-
"""#674 deployed-copy skill-version resolution.

A workspace-deployed template_version.py resolves _REPO_ROOT to
<ws>/.claude, where the repo version assets (pyproject.toml,
.claude-plugin/plugin.json) never exist — the deployed manifest carries
neither, by design. The deployed-manifest.json `source_version` receipt
must close the gap so ws-side consumers (convergence_check
_require_workspace's gate, heartbeat_loop_prompt's loop-birth gate) no
longer crash with RuntimeError instead of returning a verdict.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import template_version as tv  # noqa: E402


def _deployed_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                   version: str) -> None:
    """Simulate a deployed copy's root: manifest receipt only, no repo
    assets (pyproject.toml / .claude-plugin/plugin.json)."""
    monkeypatch.setattr(tv, "_REPO_ROOT", tmp_path)
    (tmp_path / "deployed-manifest.json").write_text(
        json.dumps({"schema_version": 3, "source_head": "f" * 40,
                    "source_version": version}),
        encoding="utf-8")


def test_read_skill_version_falls_back_to_deployed_manifest(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _deployed_root(tmp_path, monkeypatch, "9.9.9")
    assert tv.read_skill_version() == "9.9.9"


def test_version_mismatch_resolves_from_deployed_copy(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The crash face: _require_workspace's gate calls version_mismatch(ws)
    with no explicit skill_version — from a deployed copy it must resolve
    via the receipt instead of raising (#674)."""
    _deployed_root(tmp_path, monkeypatch, "9.9.9")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text(tv.stamp_line("9.9.9") + "\n", encoding="utf-8")
    assert tv.version_mismatch(ws) is None
    (ws / "CLAUDE.md").write_text(tv.stamp_line("0.0.1") + "\n", encoding="utf-8")
    assert tv.version_mismatch(ws) == (
        "workspace stamp 0.0.1 != executing skill version 9.9.9")


def test_repo_assets_win_over_deployed_manifest(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skill-tree context unchanged: the receipt never outranks the
    receipt-checked repo pair."""
    monkeypatch.setattr(tv, "_REPO_ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "kunglao-agent"\nversion = "1.2.3"\n',
        encoding="utf-8")
    (tmp_path / "deployed-manifest.json").write_text(
        json.dumps({"source_version": "9.9.9"}), encoding="utf-8")
    assert tv.read_skill_version() == "1.2.3"


def test_verify_stamps_default_resolves_from_deployed_copy(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_stamps' expected=None default is the same latent trap."""
    _deployed_root(tmp_path, monkeypatch, "9.9.9")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text(tv.stamp_line("9.9.9") + "\n", encoding="utf-8")
    assert tv.verify_stamps(ws) == {}


def test_still_raises_when_no_version_source_exists(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The release-defect guard stays: a root with no version source at
    all still raises (a silent default is the bug class this guard owns)."""
    monkeypatch.setattr(tv, "_REPO_ROOT", tmp_path)
    with pytest.raises(RuntimeError):
        tv.read_skill_version()
