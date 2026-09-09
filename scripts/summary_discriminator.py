#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""summary_discriminator.py — #826 summary 结构合同判别器。

机械三规则（判定 fail-closed；调用方 completion_gate 双笼 fail-open）：
  R1 完成词后果门：完成词 ∧ facts/ 存在非 PROVEN fact ∧ 无暂定节 → 拒
     （完成词：完整/全部闭合/CONVERGED/还原完成/fully reverse/全部 PROVEN）
  R2 不确定性传播：非 PROVEN fact 带 body 不确定性标记 → 其 fact-id 必须
     在 summary 出现或被 WAIVED(<fid>): <理由≥8字>
  R3 未答主问题节：mission_ledger 存在 unattempted/blocked PQ ∧ summary
     无开放问题节 → 拒；ledger 不存在则跳过

合同：交付 summary = workspace 根 summary.md；不存在 → ok（存在性强制
是更大的合同变更，本卡不做）。暂定节/开放问题节 = `##` 级标题带词表词。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

LEDGER_REL = "runs/mission_ledger.yaml"

_COMPLETION_RE = re.compile(
    r"分析收敛完成|全部闭合|CONVERGED|还原完成|fully\s+reverse|全部\s*PROVEN|完整还原")
_PROVISIONAL_SEC_RE = re.compile(
    r"^#{1,6}\s*(?:未独立验证|暂定结论?|provisional|未确认)", re.IGNORECASE | re.MULTILINE)
_OPEN_SEC_RE = re.compile(
    r"^#{1,6}\s*(?:未答|开放问题|open\s+questions?|待答)", re.IGNORECASE | re.MULTILINE)
_OPEN_WORD_RE = re.compile(r"未答|开放问题|open\s+questions?|待答")
_UNCERTAIN_BODY_RE = re.compile(
    r"unconfirmed|pending|hypothesis|T1|暂定|未确认", re.IGNORECASE)
_WAIVED_RE = re.compile(r"WAIVED\s*\(\s*(F-?\d+)\s*\)\s*:\s*(.+)")
_FACT_FILE_RE = re.compile(r"^F-?(\d+)", re.IGNORECASE)
_FM_STATUS_RE = re.compile(r"^status:\s*(\S+)", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
_FACT_REF_RE = re.compile(r"\bF-?\d+\b")


def _fid(name: str) -> str | None:
    m = _FACT_FILE_RE.match(Path(name).name)
    return ("F" + m.group(1)) if m else None


def _frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.match(text).group(0) if _FRONTMATTER_RE.match(text) else ""


def check(summary_path, facts_dir, ledger_path=None) -> dict:
    """校验交付 summary。返回 {ok, violations[], checked}。

    summary 缺失 → ok（无可查对象）。不可读输入抛异常（fail-open 归调用方）。
    ledger_path 缺省时自动发现 summary 同工作区的 runs/mission_ledger.yaml。

    #103: 所有文件读取统一 errors="replace"——一个非法 UTF-8 字节必须降级
    为内容（U+FFFD）继续判定，绝不许升格成 UnicodeDecodeError 把整条判别
    链推进调用方的 fail-open 笼子变成 PASS。
    """
    summary_path = Path(summary_path)
    facts_dir = Path(facts_dir)
    if not summary_path.exists():
        return {"ok": True, "violations": [], "checked": 0}
    text = summary_path.read_text(encoding="utf-8", errors="replace")
    if ledger_path is None:
        cand = summary_path.parent / LEDGER_REL
        ledger_path = cand if cand.exists() else None

    violations: list[str] = []
    non_proven = []
    marker_facts: list[str] = []
    for f in sorted(facts_dir.glob("*.md")) if facts_dir.exists() else []:
        fid = _fid(f.name)
        if fid is None:
            continue
        raw = f.read_text(encoding="utf-8", errors="replace")  # #103
        fm = _frontmatter(raw)
        status = ""
        m = _FM_STATUS_RE.search(fm)
        if m:
            status = m.group(1).strip().upper()
        body = _FRONTMATTER_RE.sub("", raw, count=1)
        if status != "PROVEN":
            non_proven.append(fid)
            if _UNCERTAIN_BODY_RE.search(body):
                marker_facts.append(fid)

    checked = 1
    has_provisional = bool(_PROVISIONAL_SEC_RE.search(text))
    # R1 完成词后果门
    if _COMPLETION_RE.search(text) and non_proven and not has_provisional:
        violations.append(
            "completion claim without provisional section (R1): 完成词与 "
            f"{len(non_proven)} 个非 PROVEN fact 并存但无 '## 未独立验证/暂定' 节")
    # R2 不确定性传播
    waived = {t.replace("-", "").upper()
              for t, reason in _WAIVED_RE.findall(text) if len(reason.strip()) >= 8}
    refs = {t.replace("-", "").upper() for t in _FACT_REF_RE.findall(text)}
    for fid in marker_facts:
        if fid not in waived and fid not in refs:
            violations.append(
                f"uncertainty not conveyed (R2): {fid} 携带不确定性标记 "
                f"但 summary 未提及且未 WAIVED")
    # R3 未答主问题节
    if ledger_path is not None and Path(ledger_path).exists():
        led = yaml.safe_load(Path(ledger_path).read_text(
            encoding="utf-8", errors="replace")) or {}  # #103
        pqs = (led.get("mission") or {}).get("pqs") or []
        open_pqs = [str(p.get("id")) for p in pqs
                    if str(p.get("state")) in ("unattempted", "blocked")]
        if open_pqs and not (_OPEN_SEC_RE.search(text)
                             or _OPEN_WORD_RE.search(text)):
            violations.append(
                "unanswered primary questions (open questions) not "
                "surfaced (R3): "
                f"欠账表有未答/受阻 PQ（{', '.join(open_pqs)}）但 summary "
                "无开放问题节")
    return {"ok": not violations, "violations": violations,
            "checked": checked}
