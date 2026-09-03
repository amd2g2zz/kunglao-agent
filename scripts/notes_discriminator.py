#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notes_discriminator.py — #834 notes 结构判别器。

机械三规则（判定本身 fail-closed；调用方 completion_gate shim 负责
双笼 fail-open，异常永不 deadlock 会话）：
  R1 复制即拒：note 词集对 facts/ 全语料的包含率 > max_overlap
  R2 零引用即拒：note 正文无任何 fact-id 引用（叙事无证据锚）
  R3 悬空即拒：引用的 fact id 在 facts/ 不存在

fact id 约定：文件名 F<digits>-slug.md 或 F-<digits>-slug.md；引用与
文件名均规范化为 F<digits>（去横线）后比较——F-011 文件与 F011 引用互认。
frontmatter（文件头 --- 块）不计入正文词集。
"""
from __future__ import annotations

import re
from pathlib import Path

DEFAULT_MAX_OVERLAP = 0.6

_FACT_FILE_RE = re.compile(r"^F-?(\d+)", re.IGNORECASE)
_FACT_REF_RE = re.compile(r"\bF-?\d+\b")
_WORD_RE = re.compile(r"[a-z0-9]+")
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)


def fact_ids(files) -> set:
    """规范化 fact id 集合：F-011-write.md → F011；F0karat 不匹配。"""
    ids = set()
    for p in files:
        m = _FACT_FILE_RE.match(Path(p).name)
        if m:
            ids.add("F" + m.group(1))
    return ids


def _words(text: str) -> set:
    return set(_WORD_RE.findall(text.lower()))


def _body(text: str) -> str:
    """剥掉文件头 frontmatter 块，正文词集不含 id/claim_id/verify_status。"""
    return _FRONTMATTER_RE.sub("", text, count=1)


def check(notes_dir, facts_dir, max_overlap: float = DEFAULT_MAX_OVERLAP) -> dict:
    """判别 notes/*.md 全体。返回 {ok, violations[], checked}。

    不可读输入（note/fact 为目录、IO 错误）直接抛异常——"无法判定"不等于
    "通过"，fail-open 与否是调用方（completion_gate 双笼）的决策。
    """
    notes_dir, facts_dir = Path(notes_dir), Path(facts_dir)
    violations: list[str] = []
    if not notes_dir.exists():
        return {"ok": True, "violations": [], "checked": 0}
    note_files = sorted(notes_dir.glob("*.md"))
    fact_files = sorted(facts_dir.glob("*.md")) if facts_dir.exists() else []

    if not fact_files:
        # 没有证据就没有合法叙事——存在 notes 即拒（#834 R0）
        for n in note_files:
            violations.append(
                f"{n.name}: no fact files in facts/ - narrative cannot "
                f"be grounded without any evidence unit")
        return {"ok": False, "violations": violations,
                "checked": len(note_files)}

    ids = fact_ids(fact_files)
    corpus: set = set()
    for f in fact_files:
        corpus |= _words(_body(f.read_text(encoding="utf-8")))

    checked = 0
    for n in note_files:
        body = _body(n.read_text(encoding="utf-8"))
        checked += 1
        words = _words(body)
        if not words:
            continue
        # R1 复制即拒
        overlap = len(words & corpus) / len(words)
        if overlap > max_overlap:
            violations.append(
                f"{n.name}: copied fact body (word-set overlap "
                f"{overlap:.2f} > max_overlap {max_overlap:.2f})")
            continue
        # R2/R3 引用检查
        refs = {t.replace("-", "").upper() for t in _FACT_REF_RE.findall(body)}
        if not refs:
            violations.append(
                f"{n.name}: no fact-id reference - narrative is ungrounded")
            continue
        dangling = sorted(refs - ids)
        if dangling:
            violations.append(
                f"{n.name}: unknown fact id {', '.join(dangling)} "
                f"(not present in facts/)")
    return {"ok": not violations, "violations": violations, "checked": checked}
