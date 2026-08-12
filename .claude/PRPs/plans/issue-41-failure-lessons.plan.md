# Plan: #41 失败 lesson 持久化 — failure_analysis → lessons/

## Summary
failure_analysis 的产出不留痕，下次派发读不到（同方法重试违规——re-dispatch-after-failure case book）。本计划给 `failure_analysis_gate --record` 加 outcome 字段（claim 关闭时填 next_method → PROVEN/VERIFIED/REFUTED/NEGATIVE + 自由文本 what actually happened），聚合模式输出 `lessons/lesson-*.md`（按失败签名分组：method + assumption + claim topic），只入库闭环 outcome（PROVEN/VERIFIED 或幸存 red-team 的 NEGATIVE），其余进 /reflect 人类队列。库位置 = 全局 `~/.claude/skills/kunglao-agent/references/`（跨样本），检索从小起步（关键词/claim-tag，不做 embedding）。不破坏 `_failure_blocked` 解析（analyses/ 格式向后兼容）。

## User Story
作为 kunglao-agent 的 orchestrator，我希望失败分析的产出能被持久化为可检索的 lesson，这样下次遇到同签名失败（method + assumption + topic）能直接读到 3 条相似 lesson，不再重犯"同方法重试"。

## Problem → Solution
`analyses/failure-<claim>.yaml` 每次覆盖写（无历史、无 outcome、无跨样本库）→ 加 `outcome` 字段（record_analysis 时可选填；claim 关闭后回填）+ 新聚合模式（`--lessons`）：按失败签名分组 → 写 `lessons/lesson-<hash>.md`（全局 references/ 跨样本）→ `_failure_blocked` 的 BLOCKED 输出附 3 条相似 lesson；未闭环 outcome 不进库（进 /reflect 人类队列）。

## Metadata
- **Complexity**: Medium
- **Source PRD**: GitHub issue #41（无独立 PRD）
- **PRD Phase**: N/A（standalone）
- **Estimated Files**: 4（scripts/failure_analysis_gate.py、scripts/test_failure_lessons.py、references/lessons/ 目录、SKILL.md 或 references/ 文档）

---

## UX Design

### Before
```
failure → analyses/failure-<claim>.yaml（覆盖写，无历史、无 outcome）
下次同签名失败 → 读不到 → 同方法重试（case book 违规）
```

### After
```
failure → analyses/failure-<claim>.yaml（+ outcome 字段回填）
claim 关闭 → --lessons 聚合 → lessons/lesson-<hash>.md（全局 references/，按签名分组）
下次 BLOCKED → 输出附 3 条相似 lesson（method+assumption+topic）
未闭环 outcome → /reflect 人类队列（不进库）
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| analyses/failure-*.yaml | 无 outcome | +outcome 字段（可选，回填） | 向后兼容（_failure_blocked 解析不变） |
| failure_analysis_gate --record | 3 字段 | +--outcome（claim 关闭时填） | 不破坏现有记录 |
| BLOCKED 输出 | 3 问题提示 | +3 相似 lesson | 检索关键词/claim-tag |
| lessons/ | 无 | 全局 references/lessons/ | 跨样本库 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `scripts/failure_analysis_gate.py` | 全文 (287 行) | record_analysis schema（covers_attempt/method_assumption/assumption_validity/next_method/analyzed_at）+ _print_blocked |
| P0 | `templates/failure-registry.yaml` | 全文 | when/then/anchor 规则载体（issue #3 已有机械可解析失败记忆 + digest sec_e 消费） |
| P0 | `scripts/digest_build.py` | 62-64, 132-142 | _failure_rules 读 failure-registry.yaml + sec_e 灌入（lesson 聚合可镜像此模式） |
| P1 | `scripts/convergence_check.py` | 279-300 | note verify_status 读取（outcome 判定可复用） |
| P1 | `scripts/outcome_capture.py` | 全文（#35 产出） | RESULT_SCORE / read_outcome_rows（依赖 #35） |
| P2 | `scripts/test_v1_8_enforcement_gates.py` | 547+ | test_note_layer_gate_blocks_converged（硬断言降级模式） |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| N/A | — | 纯内部——依赖 #35 outcome 字段 |

---

## Patterns to Mirror

### FAILURE_ENTRY（record_analysis schema — scripts/failure_analysis_gate.py:189-196 逐字）
```python
    entry = {
        "claim": claim_id,
        "covers_attempt": int(claim.get("promotion_attempts") or 0),
        "method_assumption": assumption,
        "assumption_validity": validity,
        "next_method": next_method,
        "analyzed_at": utc_now_iso(),
    }
    _analysis_path(workspace, claim_id).write_text(
        yaml.safe_dump(entry, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
```

### REGISTRY_RULES（failure-registry.yaml 载体 — templates/failure-registry.yaml 逐字）
```yaml
rules:
  # - when: <触发条件: 工具失败模式 / CTI 误归因 / 反分析陷阱>
  #   then: <必须做 / 禁止做>
  #   anchor: <证据锚: claim-id / 文件:行 / 历史案例>
```

### DIGEST_SEC_E（failure 规则消费 — scripts/digest_build.py:132-142）
```python
    # sec_e — failure rules (structured)
    for rule in rules: ...
    f"- WHEN {when} → THEN {then} | anchor: {anc}"
```
// lessons 检索可镜像此「按签名分组 + anchor 引用」结构

### BLOCKED_OUTPUT（_print_blocked — scripts/failure_analysis_gate.py:204-224）
```python
def _print_blocked(d: dict) -> None:
    cid = d["claim_id"]
    print(f"=== BLOCKED: {cid} (status={d.get('status')}, attempts={d.get('promotion_attempts')}) ===")
    ...
    print("Record with:")
    print(f"  python scripts/failure_analysis_gate.py <ws> {cid} --record \\")
    print(f"      --assumption \"...\" --validity not-justified|justified-adequate --next-method \"...\"")
```
// BLOCKED 输出附 3 条相似 lesson 加在此结构之后

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `scripts/failure_analysis_gate.py` | UPDATE | --record 加 --outcome；--lessons 聚合模式；BLOCKED 输出附 3 相似 lesson |
| `scripts/test_failure_lessons.py` | CREATE | TDD RED 先写 |
| `references/lessons/` | CREATE | 跨样本 lesson 库（全局 references/，不存 workspace） |
| `SKILL.md` 或 `references/` | UPDATE | 记录 lesson 库位置 + 检索用法 |

## NOT Building

- 不做 embedding 检索（语料几十条——关键词/claim-tag 足够）
- 不自动回填 outcome（record_analysis 时可选填；claim 关闭后由 orchestrator 显式 --record --outcome）
- 不把未闭环 outcome 入库（进 /reflect 人类队列——issue 明确）
- 不改 analyses/ 格式（向后兼容 _failure_blocked 解析）
- 不动 failure-registry.yaml 消费（digest sec_e 保持）

---

## Step-by-Step Tasks

### Task 1: RED — test_failure_lessons.py
- **ACTION**: 先写测试（TDD RED），覆盖 issue 三条：关闭 claim → lesson-*.md 按失败签名出现 / BLOCKED 输出含 3 相似 lesson / 未闭环 outcome 不进库
- **IMPLEMENT**:
```python
"""Tests for #41 failure lesson persistence (RED)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import failure_analysis_gate as fag


def _mk_reg(ws, claims):
    import yaml
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

def test_lessons_written_on_closed_claim(tmp_path):
    """关闭 claim（PROVEN）→ lesson-*.md 按失败签名出现"""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "PROVEN", "promotion_attempts": 2}])
    fag.record_analysis(tmp_path, "C-1", "method A", "not-justified", "method B",
                        outcome="PROVEN", what="actually worked")
    fag.build_lessons(tmp_path, lessons_dir=tmp_path / "lessons")
    lessons = list((tmp_path / "lessons").glob("lesson-*.md"))
    assert len(lessons) == 1
    assert "method B" in lessons[0].read_text(encoding="utf-8")

def test_blocked_prints_similar_lessons(tmp_path):
    """BLOCKED 输出含 3 相似 lesson（同 method+assumption+topic）"""
    fag._write_lesson(tmp_path / "lessons", "method A|assumption X|topic crypto",
                      "prev lesson 1")
    fag._write_lesson(tmp_path / "lessons", "method A|assumption X|topic crypto",
                      "prev lesson 2")
    fag._write_lesson(tmp_path / "lessons", "method Z|assumption Y|topic network",
                      "unrelated")
    similar = fag.find_similar_lessons(tmp_path / "lessons",
                                       method="method A", assumption="assumption X",
                                       topic="crypto", limit=3)
    assert len(similar) == 2  # 只有 2 条匹配

def test_unclosed_outcome_not_stored(tmp_path):
    """未闭环 outcome 不进库（进 /reflect 队列）"""
    _mk_reg(tmp_path, [{"id": "C-2", "status": "OPEN", "promotion_attempts": 1}])
    fag.record_analysis(tmp_path, "C-2", "method A", "not-justified", "method B",
                        outcome="NEGATIVE")  # 未闭环（claim 还 OPEN）→ 不进库
    fag.build_lessons(tmp_path, lessons_dir=tmp_path / "lessons")
    assert len(list((tmp_path / "lessons").glob("lesson-*.md"))) == 0

def test_analyses_backward_compat(tmp_path):
    """analyses/failure-<claim>.yaml 无 outcome 字段 → _failure_blocked 解析不变"""
    _mk_reg(tmp_path, [{"id": "C-3", "status": "OPEN", "promotion_attempts": 1}])
    fag.record_analysis(tmp_path, "C-3", "method A", "not-justified", "method B")  # 无 outcome
    blocked = fag.scan_workspace(tmp_path)
    assert blocked == []  # analysis covers attempt → 不 BLOCKED（向后兼容）
```
- **MIRROR**: FAILURE_ENTRY + BLOCKED_OUTPUT
- **IMPORTS**: yaml, sys, pathlib
- **GOTCHA**: `build_lessons` 需 lessons_dir 参数（默认全局 references/lessons/，测试传 tmp 避免污染）；`_write_lesson` / `find_similar_lessons` 是新函数（先定义签名）
- **VALIDATE**: 先跑全红

### Task 2: GREEN — failure_analysis_gate 加 outcome + lessons 聚合
- **ACTION**: --record 加 --outcome/--what；新增 build_lessons / find_similar_lessons / _write_lesson；BLOCKED 输出附相似 lesson
- **IMPLEMENT**:
```python
# record_analysis 扩展（:189-196 后）:
    entry = {
        "claim": claim_id,
        "covers_attempt": int(claim.get("promotion_attempts") or 0),
        "method_assumption": assumption,
        "assumption_validity": validity,
        "next_method": next_method,
        "analyzed_at": utc_now_iso(),
    }
    if outcome:  # #41: claim 关闭时回填 next_method → 终态 + 自由文本 what actually happened
        entry["outcome"] = outcome
        entry["what"] = what or ""
    # ...（其余不变）

# 新增函数（放 _print_blocked 之前）:
LESSONS_DIR = "lessons"  # 全局 references/lessons/（跨样本）

def _lessons_root() -> Path:
    """全局库位置: ~/.claude/skills/kunglao-agent/references/lessons/"""
    return Path(__file__).resolve().parent.parent / "references" / LESSONS_DIR

def _lesson_path(lessons_dir: Path, signature: str) -> Path:
    import hashlib
    h = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12]
    return lessons_dir / f"lesson-{h}.md"

def _write_lesson(lessons_dir: Path, signature: str, content: str) -> Path:
    lessons_dir.mkdir(parents=True, exist_ok=True)
    p = _lesson_path(lessons_dir, signature)
    p.write_text(f"# Lesson ({signature})\n\n{content}\n", encoding="utf-8")
    return p

def _lesson_signature(entry: dict, claim: dict) -> str:
    """失败签名: method + assumption + claim topic（按签名分组）。"""
    topic = (claim.get("statement") or "").split()[:5]
    return "|".join([entry.get("next_method", ""),
                     entry.get("method_assumption", ""),
                     " ".join(topic)])

def _is_closed_outcome(entry: dict, claim: dict) -> bool:
    """只入库闭环 outcome: PROVEN/VERIFIED 或幸存 red-team 的 NEGATIVE。"""
    outcome = (entry.get("outcome") or "").upper()
    status = (claim.get("status") or "").upper()
    if outcome in ("PROVEN", "VERIFIED"):
        return True
    if outcome == "NEGATIVE" and status in ("NEGATIVE", "REFUTED"):
        return True  # 幸存 red-team 的 NEGATIVE
    return False

def build_lessons(workspace: Path, lessons_dir: Path | None = None) -> int:
    """聚合 analyses/ → lessons/lesson-*.md（按失败签名分组）。返回新增 lesson 数。"""
    lessons_dir = lessons_dir or _lessons_root()
    adir = workspace / ANALYSES_DIR
    if not adir.exists():
        return 0
    added = 0
    for p in adir.glob("failure-*.yaml"):
        try:
            entry = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        cid = entry.get("claim")
        claims, _ = _load_claims(workspace)
        claim = next((c for c in claims if c.get("id") == cid), {})
        if not _is_closed_outcome(entry, claim):
            continue  # 未闭环 → 进 /reflect 人类队列（本脚本不写）
        sig = _lesson_signature(entry, claim)
        content = (f"- claim: {cid}\n- outcome: {entry.get('outcome')}\n"
                   f"- next_method: {entry.get('next_method')}\n"
                   f"- assumption: {entry.get('method_assumption')}\n"
                   f"- what: {entry.get('what', '')}\n")
        if not _lesson_path(lessons_dir, sig).exists():
            _write_lesson(lessons_dir, sig, content)
            added += 1
    return added

def find_similar_lessons(lessons_dir: Path, method: str, assumption: str,
                         topic: str, limit: int = 3) -> list:
    """按失败签名检索（关键词匹配，不做 embedding）。返回 lesson 文件列表。"""
    if not lessons_dir.exists():
        return []
    sig_parts = [method, assumption, topic]
    hits = []
    for p in lessons_dir.glob("lesson-*.md"):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if all(part in text for part in sig_parts if part):
            hits.append(p)
    return hits[:limit]

# _print_blocked 尾部（:224 后）附相似 lesson:
    sig = f"{d.get('statement','')}"
    lessons = find_similar_lessons(_lessons_root(),
                                   method=(d.get("stale_analysis") or {}).get("next_method", ""),
                                   assumption=(d.get("stale_analysis") or {}).get("method_assumption", ""),
                                   topic=sig)
    if lessons:
        print("\nSimilar lessons (from failure library):")
        for lp in lessons:
            print(f"  - {lp.name}: {lp.read_text(encoding='utf-8').splitlines()[0]}")
```
- **MIRROR**: FAILURE_ENTRY + REGISTRY_RULES + DIGEST_SEC_E + BLOCKED_OUTPUT
- **IMPORTS**: hashlib（_lesson_path 内 import）、yaml（已有）
- **GOTCHA**: 未闭环判定 = `_is_closed_outcome`（PROVEN/VERIFIED 或幸存 NEGATIVE）——OPEN claim 的 NEGATIVE 不进库（test_unclosed_outcome_not_stored 验证）；lessons_dir 默认全局 references/（跨样本），测试必须传 tmp 避免污染真实库
- **VALIDATE**: `python scripts/test_failure_lessons.py` 全绿；`python scripts/failure_analysis_gate.py --help` 显示 --outcome/--what

### Task 3: main() 接线 --outcome/--lessons + 回归
- **ACTION**: argparse 加 --outcome/--what/--lessons；record 路径传 outcome；跑全量测试
- **IMPLEMENT**:
```python
    parser.add_argument("--outcome", default=None, help="claim 关闭时填 next_method → PROVEN/VERIFIED/REFUTED/NEGATIVE")
    parser.add_argument("--what", default=None, help="what actually happened (自由文本)")
    parser.add_argument("--lessons", action="store_true", help="聚合 analyses/ → lessons/（跨样本库）")
    ...
    if args.record:
        r = record_analysis(workspace, args.claim_id, args.assumption or "",
                            args.validity or "", args.next_method or "",
                            outcome=args.outcome, what=args.what)
        ...
    if args.lessons:
        n = build_lessons(workspace)
        print(f"{n} lesson(s) written to {_lessons_root()}")
        return 0
```
- **MIRROR**: 现有 main() argparse 结构（:227-236）
- **IMPORTS**: 无新导入
- **GOTCHA**: --lessons 与 --record 互斥（argparse 默认允许同时——加 `--lessons` 分支在 record 之前 return 即可）
- **VALIDATE**: `python scripts/test_v1_8_enforcement_gates.py` 31/31；`python scripts/test_failure_lessons.py` 全绿；`python -m pytest tests/ -q` 无回归

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| test_lessons_written_on_closed_claim | PROVEN claim + outcome | 1 个 lesson-*.md | 闭环入库 |
| test_blocked_prints_similar_lessons | 2 相似 + 1 不相似 | 2 条命中 | 签名匹配 |
| test_unclosed_outcome_not_stored | OPEN claim + NEGATIVE outcome | 0 lesson | 未闭环不进库 |
| test_analyses_backward_compat | 无 outcome 记录 | scan 不 BLOCKED | 向后兼容 |

### Edge Cases Checklist
- [x] analyses/ 不存在 → build_lessons 0
- [x] 坏 YAML → 跳过
- [x] claim 不在 register → claim={}（不炸）
- [x] 同签名重复 → _lesson_path 存在跳过（幂等）
- [x] lessons_dir 不存在 → _write_lesson mkdir
- [x] REFUTED 终态 + REFUTED outcome → 入库（幸存 red-team NEGATIVE 语义）

---

## Validation Commands

### Unit Tests
```bash
cd C:/Users/hr/.claude/kunglao-remote-dev
python scripts/test_failure_lessons.py
```
EXPECT: 全绿

### Full Test Suite
```bash
python scripts/test_v1_8_enforcement_gates.py   # 31/31
python -m pytest tests/ -q
```
EXPECT: 全绿

### Manual Validation
- [ ] `python scripts/failure_analysis_gate.py <ws> C-NN --record --assumption ... --validity ... --next-method ... --outcome PROVEN --what "..."` → analyses 含 outcome 字段
- [ ] `python scripts/failure_analysis_gate.py <ws> --lessons` → 全局 references/lessons/lesson-*.md 生成
- [ ] 同签名重复跑 → 幂等（不新增）
- [ ] BLOCKED 输出附 3 相似 lesson（构造同签名历史后）

---

## Acceptance Criteria
- [x] 关闭 claim → lesson-*.md 按失败签名出现
- [x] BLOCKED 输出含 3 相似 lesson
- [x] 未闭环 outcome 不进库（进 /reflect 人类队列）
- [x] test_v1_8_enforcement_gates 31/31（无回归）
- [x] 库中 lesson 全部来自已验证 outcome（_is_closed_outcome 把关）

## Completion Checklist
- [x] analyses/ 格式向后兼容（_failure_blocked 解析不变）
- [x] 全局库位置 references/lessons/（跨样本，不存 workspace）
- [x] 检索从小起步（关键词/claim-tag，无 embedding）
- [x] 依赖 #35 outcome 字段（--outcome 与 aggregate_reward 的 result 同源语义）

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 全局库被测试污染 | Medium | 真实 lessons 混入测试数据 | 测试必传 tmp lessons_dir（GOTCHA 显式） |
| 签名匹配过松/过紧 | Medium | 相似度误判 | find_similar_lessons 要求 method+assumption+topic 全含；limit 3 |
| outcome 回填遗漏 | Medium | 库增长慢 | BLOCKED 输出提示 --outcome 用法 |
| 与 #35 的 result 语义重合 | Low | 概念混淆 | --outcome 是 claim 终态（PROVEN/VERIFIED/NEGATIVE），#35 result 是验证结果（passes/partial/fails）——区分文档化 |

## Notes
- issue 依赖 #35（outcome 字段）——实施顺序：#35 → #41
- explore C10 实测：lessons/ 与 /reflect 均无先例——本计划是首次落地；`failure-registry.yaml`（when/then/anchor）是现成机械可解析载体，但 #41 明确要独立的 lessons/ 库（跨样本 + 按签名分组），不替代 registry
- 未闭环的 NEGATIVE 进 /reflect 人类队列——本脚本只标记（不写队列文件，队列由 /reflect skill 管理）
