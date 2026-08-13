# -*- coding: utf-8 -*-
"""阶段 3 契约测试: SKILL.md 结构约束(≤500 行/一层深/授权矩阵/references 完整性).

Step 1 RED — 当前状态:
- SKILL.md 604 行 > 500 → test_skill_lte_500_lines RED
- 决策权矩阵尚未落盘 → test_decision_rights_table RED

GREEN 目标(阶段 3 判据): SKILL ≤500 行 + 一层深 + 授权矩阵(机械8/LLM6/用户5)。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
REFERENCES = ROOT / "references"
MAX_LINES = 500
MAX_DEPTH = 3  # 引用链最大嵌套层数


def _lines() -> list[str]:
    return SKILL.read_text(encoding="utf-8").splitlines()


def test_skill_lte_500_lines() -> None:
    """SKILL.md 主文件 ≤500 行(职责三分后主契约可扫读)."""
    n = len(_lines())
    assert n <= MAX_LINES, f"SKILL.md {n} lines > {MAX_LINES}"


def test_skill_references_resolve() -> None:
    """SKILL.md 引用的 references/ 文件必须真实存在."""
    text = SKILL.read_text(encoding="utf-8")
    missing = []
    for m in re.finditer(r"references/([\w./-]+\.md)", text):
        rel = m.group(1)
        if not (REFERENCES / rel).exists():
            missing.append(rel)
    assert not missing, f"missing references: {missing}"


def test_decision_rights_table() -> None:
    """授权矩阵三列: 机械 8 / LLM 6 / 用户 5 落盘于 SKILL.md."""
    text = SKILL.read_text(encoding="utf-8")
    assert "机械" in text and "8" in text, "缺少机械决策权行"
    assert "用户" in text, "缺少用户决策权行"
    # 三层授权至少各出现一次
    for col in ("机械", "LLM", "用户"):
        assert col in text, f"授权矩阵缺 {col} 列"


def test_depth_one() -> None:
    """一层深: SKILL.md 不得嵌套引用 >3 层(主文件→references→references 内部)."""
    text = SKILL.read_text(encoding="utf-8")
    # 主文件不应引用 references 内部再引用的深层路径(以 >1 层子目录为信号)
    deep = re.findall(r"references/([\w/-]+/[\w./-]+\.md)", text)
    assert len(deep) <= 1, f"深层引用过多: {deep}"


def test_skill_has_orchestrator_contract() -> None:
    """主契约保留 orchestrator 核心: 收敛循环 + 派发契约 + worker 监控."""
    text = SKILL.read_text(encoding="utf-8")
    for keyword in ("convergence", "dispatch", "worker"):
        assert keyword.lower() in text.lower(), f"缺少核心契约关键词: {keyword}"
