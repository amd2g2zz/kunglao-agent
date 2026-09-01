# -*- coding: utf-8 -*-
"""tests/test_summary_discriminator_826.py — #826 单元测试。

summary 结构合同三规则：
  R1 完成词后果门：完成词（完整/全部闭合/CONVERGED/还原完成/fully reverse/
     全部 PROVEN）∧ facts/ 存在非 PROVEN 盖章 fact ∧ 无暂定节 → 拒
  R2 不确定性传播：非 PROVEN fact 带 body 不确定性标记（unconfirmed/pending/
     hypothesis/T1/暂定/未确认）→ 其 fact-id 必须在 summary 出现或被 WAIVED
  R3 未答主问题节：mission_ledger 有 unattempted/blocked PQ ∧ summary 无
     开放问题节（未答/开放问题/open questions/待答）→ 拒

summary 合同：workspace 根 summary.md；不存在 → ok（无可查对象）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import summary_discriminator as sd  # noqa: E402


def _mk(tmp_path, facts: dict, summary: str | None, ledger: str | None = None):
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir(exist_ok=True)
    for name, body in facts.items():
        (facts_dir / name).write_text(body, encoding="utf-8")
    if summary is not None:
        (tmp_path / "summary.md").write_text(summary, encoding="utf-8")
    if ledger is not None:
        runs = tmp_path / "runs"
        runs.mkdir(exist_ok=True)
        (runs / "mission_ledger.yaml").write_text(ledger, encoding="utf-8")
    return tmp_path


F_PROVEN = (
    "---\nid: F001\nstatus: PROVEN\n---\n"
    "handler at 0x14002abcd, allocation 0x150 via size gate.\n")

F_PARTIAL = (
    "---\nid: F002\nstatus: PARTIALLY-VERIFIED\n---\n"
    "payload structure hypothesis: offset 0x150 unconfirmed, pending "
    "dynamic confirmation.\n")

F_INFERRED = (
    "---\nid: F003\nstatus: INFERRED\n---\n"
    "C2 domain inferred from strings: quixotic.exampletracker.net "
    "hypothesis pending verification.\n")


def test_completion_vocab_without_provisional_rejected(tmp_path):
    """R1：完成词 + 存在非 PROVEN fact + 无暂定节 → 拒。"""
    ws = _mk(tmp_path,
             {"F001.md": F_PROVEN, "F002.md": F_PARTIAL},
             "# 分析收敛完成\n\nq1 已全部闭合，协议已完整还原。\n")
    r = sd.check(ws / "summary.md", ws / "facts")
    assert r["ok"] is False
    assert any("completion claim" in v for v in r["violations"]), r
    assert any("F002" in v for v in r["violations"]), r


def test_provisional_section_satisfies_r1(tmp_path):
    """R1：完成词 + 有暂定节 → 过（R2 仍要求 fact-id 传播）。"""
    ws = _mk(tmp_path,
             {"F001.md": F_PROVEN, "F002.md": F_PARTIAL},
             "# 分析收敛完成\n\nq1 已全部闭合。\n\n"
             "## 未独立验证\n\nF002 的偏移为暂定结论，待动态验证。\n")
    r = sd.check(ws / "summary.md", ws / "facts")
    assert r["ok"] is True, r


def test_uncertainty_propagation_requires_id_or_waiver(tmp_path):
    """R2：非 PROVEN + 标记 fact 未被 summary 提及且未 WAIVED → 拒。"""
    ws = _mk(tmp_path,
             {"F001.md": F_PROVEN, "F003.md": F_INFERRED},
             "# 分析小结\n\nhandler 位置已定位（F001）。\n")
    r = sd.check(ws / "summary.md", ws / "facts")
    assert r["ok"] is False
    assert any("F003" in v and "not conveyed" in v
               for v in r["violations"]), r


def test_waiver_line_satisfies_r2(tmp_path):
    """R2 waiver：WAIVED(F003): 理由 ≥8 字 → 该 fact 不再要求传播。"""
    ws = _mk(tmp_path,
             {"F001.md": F_PROVEN, "F003.md": F_INFERRED},
             "# 分析小结\n\nhandler 位置已定位（F001）。\n\n"
             "WAIVED(F003): 调查范围外，不进入交付叙事。\n")
    r = sd.check(ws / "summary.md", ws / "facts")
    assert r["ok"] is True, r


def test_r3_unanswered_pq_section_required(tmp_path):
    """R3：ledger 有 unattempted PQ + summary 无开放问题节 → 拒。"""
    ledger = (
        "mission:\n  pqs:\n"
        "    - id: q1\n      state: answered\n      coverage: 1.0\n"
        "    - id: q2\n      state: unattempted\n      coverage: 0.0\n")
    ws = _mk(tmp_path,
             {"F001.md": F_PROVEN},
             "# 分析小结\n\nq1 已闭合。\n", ledger=ledger)
    r = sd.check(ws / "summary.md", ws / "facts")
    assert r["ok"] is False
    assert any("open questions" in v for v in r["violations"]), r


def test_r3_open_section_satisfies(tmp_path):
    """R3：有开放问题节 → 过。"""
    ledger = (
        "mission:\n  pqs:\n"
        "    - id: q1\n      state: answered\n      coverage: 1.0\n"
        "    - id: q2\n      state: blocked\n      coverage: 0.0\n"
        "      blocker: VM\n      wake: VM 可达后继续\n")
    ws = _mk(tmp_path,
             {"F001.md": F_PROVEN},
             "# 分析小结\n\nq1 已闭合。\n\n"
             "## 开放问题\n\nq2 blocked（VM），wake：VM 可达后继续。\n")
    r = sd.check(ws / "summary.md", ws / "facts")
    assert r["ok"] is True, r


def test_all_proven_no_provisional_needed(tmp_path):
    """全 PROVEN facts：完成词不需要暂定节。"""
    ws = _mk(tmp_path,
             {"F001.md": F_PROVEN},
             "# 分析收敛完成\n\n协议已完整还原。\n")
    r = sd.check(ws / "summary.md", ws / "facts")
    assert r["ok"] is True, r


def test_no_summary_skipped(tmp_path):
    """summary.md 不存在 → ok checked=0（存在性强制是更大的合同变更）。"""
    ws = _mk(tmp_path, {"F001.md": F_PROVEN}, None)
    r = sd.check(ws / "summary.md", ws / "facts")
    assert r["ok"] is True and r["checked"] == 0


def test_ledger_absent_skips_r3(tmp_path):
    """ledger 不存在 → R3 跳过。"""
    ws = _mk(tmp_path, {"F001.md": F_PROVEN}, "# 小结\n\n无完成词。\n")
    r = sd.check(ws / "summary.md", ws / "facts")
    assert r["ok"] is True, r
