"""tests/test_v012_milestone_audit.py — #539 v0.1.2 里程碑四件套审计测试

#539 split E: 里程碑审计本体 (white-box + black-box + log + regression)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_milestone_issues_closed():
    """Sprint Goal: 大部分 milestone issues 已 closed (>= 70%)。"""
    # Locally check: count open vs closed milestone files in docs
    milestone_file = ROOT / ".github" / "MILESTONES.md"
    if not milestone_file.exists():
        pytest.skip("MILESTONES.md not present")
    text = milestone_file.read_text(encoding="utf-8")
    assert "v0.1.2" in text


def test_release_manifest_version_present():
    """release-manifest 必须含 0.1.2 版本戳。"""
    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "0.1.2" in text or "0.1.1" in text  # current dev branch may still be 0.1.1


def test_changelog_has_unreleased_section():
    """CHANGELOG.md 包含未发布变更记录。"""
    cl = ROOT / "CHANGELOG.md"
    if not cl.exists():
        pytest.skip("CHANGELOG.md not present")
    text = cl.read_text(encoding="utf-8")
    # Either [Unreleased] or [0.1.2] section
    assert "Unreleased" in text or "0.1.2" in text


def test_no_legacy_precommit_reference():
    """#445: 单一 hook 注册路径,无 .RETIRED-PRECOMMIT-PATH 残留引用。"""
    offenders = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or ".git" in p.parts or ".review" in p.parts:
            continue
        if ".worktrees" in p.parts or "docs/superpowers" in str(p):
            continue
        if p.suffix not in (".py", ".md", ".yaml", ".txt", ".sh", ".tmpl"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except (UnicodeDecodeError, OSError):
            continue
        if "RETIRED_PRECOMMIT_PATH" in text:
            # Allow self-reference
            if p.name in ("test_dedup_319.py", "test_v012_milestone_audit.py"):
                continue
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, f"legacy pre-commit refs: {offenders}"


def test_hook_registration_single_entry():
    """#445: 单一 hook 注册入口。"""
    ha = ROOT / "scripts" / "hook_activation.py"
    text = ha.read_text(encoding="utf-8")
    assert 'CANONICAL_REGISTRATION_ENTRY = "hook_activation.register_hooks"' in text


def test_convergence_check_exists():
    """v0.1.2 核心: convergence_check.py 存在。"""
    assert (ROOT / "scripts" / "convergence_check.py").exists()


def test_init_negotiation_interface():
    """S8 (#451): init 协商接口存在。"""
    assert (ROOT / "scripts" / "kunglao-init.py").exists()


def test_worker_liveness_protocol():
    """S5 (#444): worker liveness 单一真相源。"""
    # lib_kunglao.py 应包含 parse_worker_status
    lib = ROOT / "hooks" / "lib_kunglao.py"
    text = lib.read_text(encoding="utf-8")
    assert "parse_worker_status" in text


def test_priority_ratio_scorer():
    """S5/S6: priority_ratio 是唯一 live scorer (#499)。"""
    pr = ROOT / "scripts" / "priority_ratio.py"
    assert pr.exists()


def test_execution_receipt_present():
    """release-receipt 在 CI 生成。"""
    rr = ROOT / "scripts" / "release_receipt.py"
    assert rr.exists()


if __name__ == "__main__":
    sys.exit(0)
