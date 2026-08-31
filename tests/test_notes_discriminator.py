# -*- coding: utf-8 -*-
"""tests/test_notes_discriminator.py — #834 单元测试。

#834 notes 结构判别器三条机械规则：
  R1 重叠率: note 词集对 facts/ 全体词集的包含率 > max_overlap → 拒（复制即拒）
  R2 零引用: note 无任何 fact-id 引用 → 拒
  R3 悬空引用: 引用的 fact id 在 facts/ 不存在 → 拒

fact id 约定：facts/F<digits>-slug.md 或 F-<digits>-slug.md，引用规范化
（去横线）后比较——F-011 文件与 F011 引用互认。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import notes_discriminator as nd  # noqa: E402


def _mk(tmp_path, facts: dict, notes: dict) -> tuple:
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir(exist_ok=True)
    for name, body in facts.items():
        (facts_dir / name).write_text(body, encoding="utf-8")
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir(exist_ok=True)
    for name, body in notes.items():
        (notes_dir / name).write_text(body, encoding="utf-8")
    return facts_dir, notes_dir


def test_copied_fact_note_rejected(tmp_path):
    fact_body = (
        "# F001 crash context\n\n"
        "the payload registers its exception handler at 0x14002abcd and "
        "allocates 0x150 bytes via a size gate comparison before the write "
        "in the worker thread.\n"
    )
    note_body = (
        "---\nid: C-001\nclaim_id: C-001\nverify_status: pending\n---\n\n"
        "# C-001 durable result\n\n" + fact_body
    )
    facts_dir, notes_dir = _mk(
        tmp_path, {"F001-crash.md": fact_body}, {"C-001.md": note_body})
    r = nd.check(notes_dir, facts_dir)
    assert r["ok"] is False
    assert any("copied" in v for v in r["violations"]), r["violations"]
    assert any("C-001.md" in v for v in r["violations"]), r["violations"]


def test_reference_note_passes(tmp_path):
    fact_body = (
        "the payload registers its exception handler at 0x14002abcd and "
        "allocates 0x150 bytes via a size gate comparison before the write.\n"
    )
    note = (
        "---\nid: C-001\nclaim_id: C-001\nverify_status: pending\n---\n"
        "\n# C-001 durable result\n\n"
        "Crash timing analysis: the size-gate allocation happens BEFORE the "
        "handler registration, so the primitive is a pre-handler write.\n"
        "Evidence: F001 (handler @0x14002abcd, allocation gate).\n"
        "Residual risk: the gate comparison value may differ under alternate "
        "payload shapes, so the conclusion is provisional.\n"
    )
    facts_dir, notes_dir = _mk(
        tmp_path, {"F001-crash.md": fact_body}, {"C-001.md": note})
    r = nd.check(notes_dir, facts_dir)
    assert r["ok"] is True, r["violations"]


def test_zero_fact_reference_rejected(tmp_path):
    note = (
        "---\nid: C-001\nclaim_id: C-001\nverify_status: pending\n---\n"
        "This note narrates conclusions without citing any evidence id.\n"
        "It has plenty of distinct words: quixotic velvet thunderstorm.\n"
    )
    facts_dir, notes_dir = _mk(
        tmp_path,
        {"F001-crash.md": "payload registers handler 0x14002abcd allocates 0x150 size gate"},
        {"C-001.md": note},
    )
    r = nd.check(notes_dir, facts_dir)
    assert r["ok"] is False
    assert any("no fact-id" in v for v in r["violations"]), r["violations"]


def test_dangling_reference_rejected(tmp_path):
    note = (
        "---\nclaim_id: C-001\n---\n"
        "Story: the handler at 0x14002abcd implies pre-handler write; "
        "see F999 for the allocation detail. quixotic velvet thunderstorm.\n"
    )
    facts_dir, notes_dir = _mk(
        tmp_path,
        {"F001-crash.md": "handler 0x14002abcd allocates 0x150"},
        {"C-001.md": note},
    )
    r = nd.check(notes_dir, facts_dir)
    assert r["ok"] is False
    assert any("unknown fact id" in v for v in r["violations"]), r["violations"]


def test_empty_facts_rejects_notes(tmp_path):
    """facts 空目录：存在 notes 即拒——没有证据就没有合法叙事。"""
    facts_dir, notes_dir = _mk(
        tmp_path, {}, {"C-001.md": "text without refs quixotic velvet thunderstorm"})
    r = nd.check(notes_dir, facts_dir)
    assert r["ok"] is False
    assert any("no fact files" in v for v in r["violations"]), r["violations"]


def test_missing_notes_dir_passes(tmp_path):
    """notes 目录缺失 → 无可判对象，ok（义务面归 NOTES_DUE 管）。"""
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir()
    r = nd.check(tmp_path / "no-notes-here", facts_dir)
    assert r["ok"] is True
    assert r["checked"] == 0


def test_threshold_configurable(tmp_path):
    """0.0 → 任何重叠即拒；1.0 → 重叠规则不触发（引用+叙事充足仍过）。"""
    fact_body = (
        "handler 0x14002abcd allocates 0x150 bytes via size gate comparison "
        "before write\n"
    )
    note = (
        "---\nclaim_id: C-001\n---\n" + fact_body +
        "\nEvidence: F001.\n"
    )
    facts_dir, notes_dir = _mk(
        tmp_path, {"F001-crash.md": fact_body}, {"C-901.md": note})
    r_def = nd.check(notes_dir, facts_dir)
    assert r_def["ok"] is False
    assert any("copied" in v for v in r_def["violations"]), r_def["violations"]
    r_hi = nd.check(notes_dir, facts_dir, max_overlap=1.0)
    assert r_hi["ok"] is True, r_hi["violations"]
    r_lo = nd.check(notes_dir, facts_dir, max_overlap=0.0)
    assert r_lo["ok"] is False
    assert any("copied" in v for v in r_lo["violations"]), r_lo["violations"]


def test_normalizes_dash_forms(tmp_path):
    """F-011 文件名 vs F011 引用规范化后互认。"""
    facts_dir, notes_dir = _mk(
        tmp_path,
        {"F-011-write.md": "the write primitive lands at a fixed offset."},
        {"C-011.md": "Conclusion: pre-handler write confirmed; evidence F011 "
                     "offset detail; plus quixotic velvet thunderstorm words."},
    )
    r = nd.check(notes_dir, facts_dir, max_overlap=0.9)
    assert r["ok"] is True, r["violations"]
    ids = nd.fact_ids(list(facts_dir.glob("*.md")))
    assert "F011" in ids and "F-011" not in ids, ids
    assert "F0karat" not in ids
