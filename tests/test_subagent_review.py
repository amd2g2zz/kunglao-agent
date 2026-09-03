#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_subagent_review.py — Gate 5 (#462) mechanical checks.

Covers:
  - N/A: no domain paths staged → trivially pass
  - Missing: domain paths + no .subagent-review/ → HARD_PAUSE (rc=2)
  - JSON parse error / missing fields / self-stamp / empty tools_used
    → HARD_PAUSE
  - Happy path: domain paths + valid review file → rc=0

Tests use isolated temp git repos (via _IsolatedRepo) to control the
staged-file snapshot that `_staged_files()` reads. Monkeypatched
REPO_ROOT for the duration of the check.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "devkit"))

import subagent_review as sr  # noqa: E402


# ---- pure helpers (no git interaction) -------------------------------

class TestDomainPath:
    def test_scripts_path(self) -> None:
        assert sr._is_domain_path("scripts/kunglao.py")

    def test_hooks_path(self) -> None:
        assert sr._is_domain_path("hooks/dispatch_gate.py")

    def test_docs_path(self) -> None:
        assert sr._is_domain_path("docs/quality_gates.md")

    def test_tests_path(self) -> None:
        assert sr._is_domain_path("tests/test_subagent_review.py")

    def test_references_path(self) -> None:
        assert sr._is_domain_path("references/_INDEX.md")

    def test_skills_path(self) -> None:
        assert sr._is_domain_path("skills/kunglao-agent/SKILL.md")

    def test_openspec_not_domain(self) -> None:
        # openspec/ is NOT in DOMAIN_PREFIXES — Gate 5 N/A
        assert not sr._is_domain_path("openspec/changes/issue-462/spec.md")

    def test_pyproject_not_domain(self) -> None:
        assert not sr._is_domain_path("pyproject.toml")

    def test_root_readme_not_domain(self) -> None:
        assert not sr._is_domain_path("README.md")

    def test_devkit_itself_not_domain(self) -> None:
        # devkit/ scaffolding is where the rule lives, not what it
        # guards; tests for the rule live under tests/ which IS domain
        assert not sr._is_domain_path("devkit/quality_gates.py")


class TestValidateOne:
    def _write(self, tmp_path: Path, name: str, payload: dict) -> Path:
        rev = tmp_path / ".subagent-review"
        rev.mkdir(exist_ok=True)
        p = rev / name
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_valid_full(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, "ok.json", {
            "agent": "ghidra-light",
            "plan": "Decompile c-409",
            "status_sync": "runs/worker-status-c409.md",
            "tools_used": ["scripts/re/pseudo_c_extractor.py"],
            "verified_by": "verifier-subagent-2026-08-19"})
        ok, msg = sr._validate_one(p)
        assert ok is True, msg

    def test_missing_fields(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, "missing.json", {
            "agent": "ghidra-light",
            "plan": "x"})
        ok, msg = sr._validate_one(p)
        assert ok is False
        assert "missing" in msg.lower()

    def test_empty_tools_used(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, "empty.json", {
            "agent": "ghidra-light",
            "plan": "x",
            "status_sync": "runs/x.md",
            "tools_used": [],
            "verified_by": "verifier-x"})
        ok, msg = sr._validate_one(p)
        assert ok is False
        assert "tools_used" in msg.lower()

    def test_self_stamp_verifier(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, "self.json", {
            "agent": "ghidra-light",
            "plan": "x",
            "status_sync": "runs/x.md",
            "tools_used": ["scripts/re/x.py"],
            "verified_by": "kunglao-agent"})
        ok, msg = sr._validate_one(p)
        assert ok is False
        assert "self-stamp" in msg.lower()

    def test_self_stamp_anthropic(self, tmp_path: Path) -> None:
        p = self._write(tmp_path, "self2.json", {
            "agent": "ghidra-light",
            "plan": "x",
            "status_sync": "runs/x.md",
            "tools_used": ["scripts/re/x.py"],
            "verified_by": "anthropic-claude"})
        ok, msg = sr._validate_one(p)
        assert ok is False
        assert "self-stamp" in msg.lower()

    def test_malformed_json(self, tmp_path: Path) -> None:
        rev = tmp_path / ".subagent-review"
        rev.mkdir(exist_ok=True)
        p = rev / "bad.json"
        p.write_text("{ not json", encoding="utf-8")
        ok, msg = sr._validate_one(p)
        assert ok is False
        assert "json" in msg.lower()

    def test_top_level_not_dict(self, tmp_path: Path) -> None:
        rev = tmp_path / ".subagent-review"
        rev.mkdir(exist_ok=True)
        p = rev / "list.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        ok, msg = sr._validate_one(p)
        assert ok is False
        assert "not a dict" in msg.lower()

    def test_general_purpose_with_real_verifier(self, tmp_path: Path) -> None:
        # general-purpose is allowed IF verified_by is a real (independent)
        # handle and tools_used is populated. The current rule does NOT
        # block general-purpose explicitly — that's a separate tighter
        # policy #462 evidence 3. For now: empty tools_used fails;
        # non-empty passes.
        p = self._write(tmp_path, "gp.json", {
            "agent": "general-purpose with justification",
            "plan": "cross-cutting refactor",
            "status_sync": "runs/worker-status-gp.md",
            "tools_used": ["scripts/kunglao.py"],
            "verified_by": "verifier-subagent-gp"})
        ok, _ = sr._validate_one(p)
        assert ok is True


# ---- end-to-end via tmp git repo ------------------------------------

class _IsolatedRepo:
    """Stage a synthetic repo with .subagent-review/ at a temp location
    and run subagent_review.check() against it via monkeypatched REPO_ROOT."""

    def __init__(self, tmp_path: Path, files: list[str], review: dict | None):
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "--initial-branch=main"],
                       cwd=self.repo, check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "t@t"],
                       check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "T"],
                       check=True)
        for f in files:
            p = self.repo / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        if review is not None:
            rev = self.repo / ".subagent-review"
            rev.mkdir(exist_ok=True)
            (rev / "ok.json").write_text(json.dumps(review), encoding="utf-8")
            subprocess.run(["git", "-C", str(self.repo), "add", ".subagent-review"],
                           check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        self._monkey = sr.REPO_ROOT

    def run(self) -> int:
        sr.REPO_ROOT = self.repo
        try:
            return sr.check()
        finally:
            sr.REPO_ROOT = self._monkey


def _review_dict() -> dict:
    return {
        "agent": "ghidra-light",
        "plan": "Decompile c-409",
        "status_sync": "runs/worker-status-c409.md",
        "tools_used": ["scripts/re/pseudo_c_extractor.py"],
        "verified_by": "verifier-subagent-2026-08-19",
    }


class TestEndToEnd:
    def test_no_domain_paths_trivially_passes(self, tmp_path: Path) -> None:
        # Touching only openspec/ and devkit/ — N/A
        isolated = _IsolatedRepo(tmp_path, ["openspec/x.md", "devkit/x.py"], None)
        rc = isolated.run()
        assert rc == 0

    def test_domain_paths_without_review_hard_pauses(self, tmp_path: Path) -> None:
        isolated = _IsolatedRepo(tmp_path, ["scripts/kunglao.py"], None)
        rc = isolated.run()
        assert rc == 2

    def test_domain_paths_with_valid_review_passes(self, tmp_path: Path) -> None:
        isolated = _IsolatedRepo(tmp_path, ["scripts/kunglao.py"], _review_dict())
        rc = isolated.run()
        assert rc == 0

    def test_hooks_path_without_review_hard_pauses(self, tmp_path: Path) -> None:
        isolated = _IsolatedRepo(tmp_path, ["hooks/dispatch_gate.py"], None)
        rc = isolated.run()
        assert rc == 2

    def test_multiple_domain_paths_one_review_suffices(self, tmp_path: Path) -> None:
        isolated = _IsolatedRepo(
            tmp_path,
            ["scripts/a.py", "hooks/b.py", "tests/c.py"],
            _review_dict())
        rc = isolated.run()
        assert rc == 0

    def test_invalid_review_blocks_commit(self, tmp_path: Path) -> None:
        bad_review = _review_dict()
        del bad_review["tools_used"]  # missing field
        isolated = _IsolatedRepo(
            tmp_path, ["scripts/a.py"], bad_review)
        rc = isolated.run()
        assert rc == 2
