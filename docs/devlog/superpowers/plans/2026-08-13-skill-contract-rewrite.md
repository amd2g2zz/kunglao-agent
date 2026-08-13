# #226 SKILL.md 契约化重写 — 任务级计划（TDD）

> 权威规格 = issue #226。本文给出内容映射 + 契约测试代码 + 逐任务步骤。
> 执行者：DEV（tdd-guide）在独立 worktree，分支 `fix/226-skill-contract`。

## 现状 → 目标结构映射（26 个 section → 8 个）

| 新 section | 吸收的旧 section | 处理方式 |
|---|---|---|
| Phase 0 Environment Probe | Input contract / Arguments / Local defaults / Phase 0 SETUP / guardrails §3 path-reachability | 全英文；Local defaults 值全部占位符化（`<WORKSPACE>` `<VM_IP>` `<SAMPLE_SHA>`），加"环境发现"措辞（与 #228 契约一致） |
| Phase 1 Activate | Hook + heartbeat activation（Phase 0 SETUP 尾部） | 命令序列保留（机器枚举），MUSTs 保留 |
| Phase 2 Dispatch Loop | The convergence loop / 5 behaviors / Is it converging / dispatch contract / isolation-first / Budget & enforcement / §7 self-cap / Dispatch policy / External memory / guardrails §2 矩阵、§4 fallback、§4.1 self-drive、§6 monitoring | 决策表保留（machine enum）；5 behaviors 压成一行一条（完整版在 references/convergence-loop.md）；删除自我叙事（"Every prior 傻等 complaint..."） |
| Phase 3 Verify | BLIND redteam / failed attempt → failure_analysis_gate / verify-static-vs-dynamic / tool-use boundary §1+§1a-d | 四门（redteam/provenance/contradiction/inference）按门列步骤；§1a-d 压缩保留（完整版 references/guardrails.md） |
| Phase 4 Completion Transaction | Loop semantics / CONVERGED 两段式契约（#205） | 矛盾重算 + discovery 消费 + 校准交付（calibration_gate：confidence + falsifier）步骤化 |
| Phase 5 Delivery | completion_gate / receipt / Downstream contract | oracle 判定 + release receipt 指针 |
| Failure Routing | F-row 症状（failure-modes-* 三文件索引） | 表：症状 → 对策 + 强制门脚本路径 |
| Operator Boundaries | What the orchestrator is NOT / You are the ORCHESTRATOR / Hard prohibitions / System boundary / Decision rights | 机器 8 / LLM 6 / 用户 5 决策矩阵指针；prohibitions 保留编号列表；删除重复（"NOT analyst" 现出现 3 次 → 1 次） |

**删除（自我叙事，不回迁）**："WHY=..."、"The single most-violated rule"、Maintenance 节的"NEVER rewrote the whole skill"条款（#226 就是用户的显式重写指令，该条款已被用户指令取代；替换为一行维护指针）。

**迁移到 references/**：worker self-drive 中文段落 → 翻译为英文并移 `references/operational-mechanics.md`（SKILL.md 只留一行指针）；其余已有 references 的内容不再重复叙述。

## 契约测试（tests/test_skill_contract.py，先写先红）

```python
# -*- coding: utf-8 -*-
"""SKILL.md contract (#226): the skill file is a machine-checkable contract.

Rules: <400 lines; English-only body (CJK allowed in frontmatter triggers);
no hardcoded instance values (Windows paths / VM IPs) in the body; every
markdown link target exists; the 8 workflow sections appear in order;
no duplicated narrative sections.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
SECTIONS = [
    "Phase 0 Environment Probe",
    "Phase 1 Activate",
    "Phase 2 Dispatch Loop",
    "Phase 3 Verify",
    "Phase 4 Completion Transaction",
    "Phase 5 Delivery",
    "Failure Routing",
    "Operator Boundaries",
]
CJK = re.compile(r"[一-鿿]")
HARDCODED = re.compile(...)  # drive-letter paths | VM-subnet IPs | home dirs | kong-refactor — same regex as tests/test_skill_contract.py
NARRATIVE = ["WHY=", "single most-violated", "traces to violating", "case-book"]


def _body() -> str:
    text = SKILL.read_text(encoding="utf-8")
    parts = text.split("---", 2)  # frontmatter | body
    return parts[2] if len(parts) == 3 else ""


def test_skill_md_under_400_lines():
    assert len(SKILL.read_text(encoding="utf-8").splitlines()) < 400


def test_skill_md_body_english_only():
    body = _body()
    assert not CJK.search(body), "CJK characters found in SKILL.md body"


def test_skill_md_no_hardcoded_instance_values():
    body = _body()
    assert not HARDCODED.search(body), "hardcoded path/IP found in SKILL.md body"


def test_skill_md_sections_in_order():
    body = _body()
    positions = [body.find(s) for s in SECTIONS]
    assert all(p >= 0 for p in positions), "missing section(s)"
    assert positions == sorted(positions), "sections out of order"


def test_skill_md_links_resolve():
    body = _body()
    broken = []
    for m in re.finditer(r"\]\(([^)#]+)(?:#[^)]*)?\)", body):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (SKILL.parent / target).exists():
            broken.append(target)
    assert not broken, f"broken links: {broken}"


def test_skill_md_no_narrative_phrases():
    body = _body()
    hits = [w for w in NARRATIVE if w in body]
    assert not hits, f"self-narrative phrases remain: {hits}"
```

## 任务步骤

1. **RED**：写 `tests/test_skill_contract.py`（上表全文）→ 运行确认 6 项全红
2. **GREEN**：按映射表重写 `SKILL.md`（frontmatter name/description/triggers 保留不变；正文全英文命令式）
3. 运行契约测试 → 全绿
4. 回归：`uv run python -m pytest tests/test_skill_invocation.py tests/test_suite_health.py -q`（skill 引用与 golden 重放不受影响）
5. **IMPROVE**：检查行数余量（<380 目标）、每 section 有 fail-closed 失败语义标注（exit non-zero → Failure Routing）
6. 提交 `docs(#226): SKILL.md contract rewrite — sequential workflow, imperative, placeholders`
7. push + PR（body: Fixes #226 + RED 输出 + GREEN 摘要）

## 验收（issue #226 口径）

- <400 行；契约测试 6 项全绿；无中英混杂（frontmatter 触发短语除外）
- 每个 section 是工作流步骤；无同一主题双处叙述（narrative 契约测试强制）
- 占位符：正文无内网 VM IP、无盘符绝对路径（hardcoded 契约测试强制）
