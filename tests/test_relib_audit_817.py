# -*- coding: utf-8 -*-
"""tests/test_relib_audit_817.py — #817 re-library 审查器测试。

三类问题检出 + quarantine 可逆性 + 度量。夹具用 tmp_path 仿 references/
结构（素材文件 + _index-*.md 目录），不触真实库内容。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import relib_audit  # noqa: E402


def _mk(tmp_path, files: dict, indexes: dict) -> Path:
    for name, body in files.items():
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
    for name, body in indexes.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_orphan_detected(tmp_path):
    d = _mk(tmp_path, {"a.md": "content about tools\n"},
            {"_index-tools.md": "catalog: b.md\n"})
    r = relib_audit.audit(d)
    assert r["orphans"] == ["a.md"], r
    assert r["counts"]["orphans"] == 1


def test_indexed_file_not_orphan(tmp_path):
    d = _mk(tmp_path, {"a.md": "x\n"},
            {"_index-tools.md": "catalog: a.md\n"})
    r = relib_audit.audit(d)
    assert r["orphans"] == [], r


def test_tracker_residue_detected(tmp_path):
    d = _mk(tmp_path, {"a.md": "see #692 and #662 for history\n"},
            {"_index-tools.md": "catalog: a.md\n"})
    r = relib_audit.audit(d)
    assert r["trackers"] == {"a.md": ["#662", "#692"]}, r
    assert r["counts"]["trackers"] == 1


def test_clean_file_no_tracker_violation(tmp_path):
    d = _mk(tmp_path, {"a.md": "no ticket ids here\n"},
            {"_index-tools.md": "catalog: a.md\n"})
    r = relib_audit.audit(d)
    assert r["trackers"] == {}, r


def test_missing_declaration_detected(tmp_path):
    d = _mk(tmp_path, {"a.md": "no declaration line\n"},
            {"_index-tools.md": "catalog: a.md\n"})
    r = relib_audit.audit(d)
    assert "a.md" in r["missing_decl"], r
    assert r["counts"]["missing_decl"] == 1


def test_declaration_present_passes(tmp_path):
    d = _mk(tmp_path,
            {"a.md": "body\n\nrecall_useful: pending\n"},
            {"_index-tools.md": "catalog: a.md\n"})
    r = relib_audit.audit(d)
    assert "a.md" not in r["missing_decl"], r
    assert r["counts"]["missing_decl"] == 0


def test_quarantine_reversible(tmp_path):
    d = _mk(tmp_path, {"a.md": "orphan content\n"},
            {"_index-tools.md": "catalog: b.md\n"})
    src = d / "a.md"
    dest = relib_audit.quarantine(d, "a.md", reason="orphan-audit")
    assert not src.exists()
    assert dest.exists()
    assert "orphan content" in dest.read_text(encoding="utf-8")
    manifest = d / "archive" / "quarantine-manifest.yaml"
    assert manifest.exists()
    text = manifest.read_text(encoding="utf-8")
    assert "a.md" in text and "orphan-audit" in text


def test_quarantine_rejects_indexed_file(tmp_path):
    d = _mk(tmp_path, {"a.md": "x\n"},
            {"_index-tools.md": "catalog: a.md\n"})
    try:
        relib_audit.quarantine(d, "a.md", reason="should-refuse")
        raised = False
    except ValueError:
        raised = True
    assert raised, "quarantine must refuse indexed (non-orphan) files"


def test_metrics_counts_consistent(tmp_path):
    d = _mk(tmp_path, {
        "a.md": "body x\n",
        "b.md": "see #123\nrecall_useful: yes\n",
    }, {"_index-tools.md": "catalog: b.md\n"})  # a.md 未被目录化 → 孤儿
    r = relib_audit.audit(d)
    assert r["counts"] == {"orphans": 1, "trackers": 1, "missing_decl": 1}
    assert r["metrics"]["files_total"] == 2
