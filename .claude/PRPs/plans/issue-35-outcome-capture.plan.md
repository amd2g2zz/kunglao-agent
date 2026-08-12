# Plan: #35 outcome-capture — verify/red-team 输出落盘 + reward 聚合

## Summary
kunglao 感知层无 outcome 信号（r3 实测 75.6% 轮次零 fact delta）。验证信号已存在（verify-note passes/partial/fails + red-team CONFIRMED/REFUTED/UNVERIFIED）但未落盘。本计划新增 `outcome_capture.py`：读 runs/*.md overall verdict + note verify_status → ledger 独立 OUTCOME 行，`aggregate_reward()` 纯函数聚合，reward 仅作 soft 信号（priority 因子/prompt 注入），不 gate 任何机械门。

## User Story
作为 kunglao-agent 的 orchestrator，我希望每次外部验证（verify-note / red-team）的结果以独立事件行落盘并能聚合出 reward 标量，这样我能在空转时感知"验证信号仍在产生"，而不把陈旧快照误当信号。

## Problem → Solution
`.convergence_ledger.jsonl` 现有行全是 SNAPSHOT（ts/decision/open_count/...），无验证事件 → `outcome_capture.py` 把 verify/red-team 结果写成 `{"type":"outcome", ts, claim_id, result, checker}` 行（契约已冻结于 status_defs.py），`aggregate_reward()` 纯函数按结果值映射聚合，幂等去重（同 claim 同 checker 不重复累计）。

## Metadata
- **Complexity**: Medium
- **Source PRD**: GitHub issue #35（无独立 PRD）
- **PRD Phase**: N/A（standalone）
- **Estimated Files**: 4（scripts/outcome_capture.py、scripts/test_outcome_capture.py、hooks/worker_pulse.py、scripts/status_defs.py[仅 docstring 引用]）

---

## UX Design

### Before
```
verify-note → runs/<ts>-verify-<note>.md "## Overall verdict: passes"
red-team    → runs/verify-redteam-<target>.md "CONFIRMED"
                ↑ 结果只存在于文件，从不进 ledger → 感知层看不见
```

### After
```
verify-note → runs/<ts>-verify-<note>.md → outcome_capture.py
red-team    → runs/verify-redteam-<target>.md → outcome_capture.py
                ↓
    .convergence_ledger.jsonl 追加 {"type":"outcome", ts, claim_id, result, checker}
                ↓
    aggregate_reward() → 0.0~1.0 标量 → priority/prompt soft 信号
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| ledger | 只有 snapshot 行 | 混入 outcome 行 | status_defs 契约已冻结（additive） |
| worker_pulse | BLOCKED/SATURATED → stderr+rc2 | 不变（另加 quarantined 在 #36） | 本计划不加 gate |
| priority.py | 不读 outcome | 不读（reward 是软信号，留给 prompt/后续） | 本计划不接线 priority |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `scripts/status_defs.py` | 38-47, 71-84 | LedgerLineType 契约 + ledger_line_type()（OUTCOME 行字段 type/ts/claim_id/checker/result） |
| P0 | `scripts/convergence_health.py` | 40, 68-81 | `_read_ledger` 容错读法（逐行 json.loads、跳过空行/坏行）— 聚合可镜像 |
| P0 | `scripts/kunglao_record.py` | 53-69, 89-112 | record_event 幂等 append + event_id=sha256(event_type+payload) |
| P1 | `scripts/convergence_check.py` | 279-300 | note frontmatter verify_status 机械读取（`_re.search(r"^verify_status:\s*(\S+)", fm)`） |
| P1 | `C:/Users/hr/.claude/skills/malware-veri-notes/scripts/verify-note.py` | 83, 106-117 | runs/<ts>-verify-<note>.md 的 `## Overall verdict` 节 + passes/partial/fails 取值 |
| P2 | `scripts/kunglao_verify.py` | 271-277 | runs/verify-<fact_id>-<ts>.json 的 overall ∈ {VERIFIED, REJECTED, PARTIAL} |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| N/A | — | 纯内部——契约已在 status_defs.py 冻结 |

---

## Patterns to Mirror

### LEDGER_READ（容错逐行读）
```python
def _read_ledger(workspace: Path):
    p = workspace / LEDGER_NAME
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
```
// SOURCE: `scripts/convergence_health.py:68-81`

### IDEMPOTENT_APPEND（幂等 append 写）
```python
    event_id = sha256(event_type + canonical(payload))
    ...
    events.append(...)  # 同 event_id 存在 → 跳过（不重复）
```
// SOURCE: `scripts/kunglao_record.py:44-45, 89-112` — 用 event_id 去重

### NOTE_VERIFY_STATUS（frontmatter 机械读取）
```python
    vs = _re.search(r"^verify_status:\s*(\S+)", fm, _re.M)
    cid_m = _re.search(r"^claim_id:\s*([^\n]+)", fm, _re.M)
    if vs.group(1).strip().lower() != "passes": continue
```
// SOURCE: `scripts/convergence_check.py:290-296`

### OVERALL_VERDICT（verify-note 产物格式）
```python
        "## Overall verdict",
        "To be filled by Claude after collecting all subagent outputs:",
        "`passes` (all facts reproduce) / `partial` (some reproduce) / `fails` (any cannot)",
```
// SOURCE: `C:/Users/hr/.claude/skills/malware-veri-notes/scripts/verify-note.py:106-110`

### PURE_FUNCTION（聚合纯函数风格）
```python
def aggregate_reward(outcome_rows) -> float:  # 同输入同输出
```
// 本计划新建；风格镜像 `priority_ratio.py:203-258` 的纯函数排序（LLM 永不进分数）

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `scripts/outcome_capture.py` | CREATE | 核心：读 runs/*.md → OUTCOME 行 + aggregate_reward() |
| `scripts/test_outcome_capture.py` | CREATE | TDD RED 先写 |
| `hooks/worker_pulse.py` | UPDATE | 加 quarantined=N（#36 协同；本计划可先不加，留给 #36） |
| `scripts/status_defs.py` | UPDATE | docstring 引用（OUTCOME 行字段契约已存在，无需改代码） |

## NOT Building

- 不 gate 任何机械门（reward 只作 soft 信号）
- 不动 priority.py / convergence_check（reward 接线留给后续，等 ≥2 样本防过拟合——issue R6 前提）
- 不改 SNAPSHOT 行语义（additive 兼容：无 type 字段仍视为 snapshot）
- 不写 ledger.jsonl（另一本账本——只写 .convergence_ledger.jsonl）

---

## Step-by-Step Tasks

### Task 1: RED — test_outcome_capture.py
- **ACTION**: 先写测试（TDD RED），覆盖 issue 三条：outcome 行独立 type 可聚合 / 重复 verify 不重复累计 / 无数据返回中性
- **IMPLEMENT**:
```python
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import outcome_capture as oc

def test_capture_writes_outcome_row(tmp_path):
    """verify-note passes → ledger outcome 行（独立 type）"""
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "2026-08-11T00-00-00-verify-01-draft.md").write_text(
        "## Overall verdict\npasses\n", encoding="utf-8")
    n = oc.capture(tmp_path)
    rows = oc.read_outcome_rows(tmp_path)
    assert n == 1
    assert rows[0]["type"] == "outcome"
    assert rows[0]["result"] == "passes"
    assert rows[0]["checker"] == "verify-note"

def test_aggregate_reward_values(tmp_path):
    """passes=1.0 / partial=0.5 / fails=0.0；CONFIRMED=1.0 / REFUTED=0.0 / UNVERIFIED=0.5"""
    rows = [{"type": "outcome", "claim_id": "C-1", "result": "passes", "checker": "verify-note"},
            {"type": "outcome", "claim_id": "C-2", "result": "partial", "checker": "verify-note"},
            {"type": "outcome", "claim_id": "C-3", "result": "fails", "checker": "verify-note"},
            {"type": "outcome", "claim_id": "C-4", "result": "CONFIRMED", "checker": "red-team"}]
    assert oc.aggregate_reward(rows) == (1.0 + 0.5 + 0.0 + 1.0) / 4

def test_dedup_same_claim_checker(tmp_path):
    """重复 verify 不重复累计（幂等：同 claim 同 checker 结果不变则跳过）"""
    runs = tmp_path / "runs"
    runs.mkdir()
    for name in ("a-verify-01-draft.md", "b-verify-01-draft.md"):
        (runs / name).write_text("## Overall verdict\npasses\n", encoding="utf-8")
    oc.capture(tmp_path)
    oc.capture(tmp_path)  # 第二次调用
    assert len(oc.read_outcome_rows(tmp_path)) == 1  # 不重复

def test_no_data_neutral(tmp_path):
    """无数据 → 中性值（None，不误报 0 信号）"""
    assert oc.aggregate_reward([]) is None

def test_snapshot_rows_ignored(tmp_path):
    """snapshot 行（无 type）不参与聚合"""
    _ledger_rows(tmp_path, [{"ts": "2026-08-11T00:00:00Z", "decision": "DISPATCH", "open_count": 3}])
    assert oc.read_outcome_rows(tmp_path) == []
```
- **MIRROR**: LEDGER_READ + IDEMPOTENT_APPEND + OVERALL_VERDICT
- **IMPORTS**: json, sys, pathlib
- **GOTCHA**: `## Overall verdict` 取值要 strip 空白行（`passes\n` 后取第一非空行）
- **VALIDATE**: 先跑全红（RED）

### Task 2: GREEN — outcome_capture.py
- **ACTION**: 实现 capture() / read_outcome_rows() / aggregate_reward()
- **IMPLEMENT**:
```python
"""outcome_capture.py - external-checker verification results → ledger OUTCOME rows (#35).

R6 前提: 感知层 outcome 信号。verify-note / red-team 的结果目前只存在于
runs/*.md 文件, 从不进 ledger → 循环分不清"在生产"还是"空转"(r3: 75.6% 轮次
零 fact delta)。本脚本把验证结果落为 .convergence_ledger.jsonl 的独立 OUTCOME
行(契约: status_defs.LedgerLineType), aggregate_reward() 纯函数聚合。

reward 仅是 soft 信号(priority 因子/prompt 注入), 不 gate 任何机械门。

用法:
  python outcome_capture.py <workspace>            # capture runs/*.md → OUTCOME 行
  python outcome_capture.py <workspace> --reward   # 打印聚合 reward 标量
  python outcome_capture.py <workspace> --json     # 机器可读
"""
from __future__ import annotations
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from status_defs import LedgerLineType, ledger_line_type

LEDGER_NAME = ".convergence_ledger.jsonl"
VERDICT_RE = re.compile(r"## Overall verdict\s*\n+\s*(\S+)", re.IGNORECASE)
REDTEAM_RE = re.compile(r"RED-TEAM VERDICT\s*[:\-]?\s*(CONFIRMED|REFUTED|UNVERIFIED(?:\s*-\s*WITH-GAP)?)", re.IGNORECASE)
RESULT_SCORE = {
    "passes": 1.0, "partial": 0.5, "fails": 0.0,
    "CONFIRMED": 1.0, "REFUTED": 0.0, "UNVERIFIED": 0.5, "UNVERIFIED-WITH-GAP": 0.5,
}


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def read_outcome_rows(workspace: Path) -> list[dict]:
    """只返回 type==outcome 的行（status_defs 契约：聚合必须只消费 outcome 行）。"""
    p = workspace / LEDGER_NAME
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ledger_line_type(row) == LedgerLineType.OUTCOME:
            out.append(row)
    return out


def _seen_key(row: dict) -> str:
    """幂等键: claim_id + checker + result（同 claim 同 checker 同结果 → 不重复累计）。"""
    return f"{row.get('claim_id')}|{row.get('checker')}|{row.get('result')}"


def capture(workspace: Path) -> int:
    """扫 runs/*.md → 追加 OUTCOME 行（幂等：已存在的 seen_key 跳过）。返回新增行数。"""
    runs = workspace / "runs"
    if not runs.exists():
        return 0
    rows = read_outcome_rows(workspace)
    seen = {_seen_key(r) for r in rows}
    added = 0
    ledger_path = workspace / LEDGER_NAME
    new_lines: list[str] = []
    for p in sorted(runs.glob("*.md")):
        if "-verify-" not in p.name and "verify-redteam" not in p.name:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        entry = None
        if "verify-redteam" in p.name:
            m = REDTEAM_RE.search(text)
            if m:
                entry = {"type": "outcome", "ts": utc_now_iso(),
                         "claim_id": _claim_from_redteam(text, p.name),
                         "result": m.group(1).strip(), "checker": "red-team"}
        else:
            m = VERDICT_RE.search(text)
            if m:
                entry = {"type": "outcome", "ts": utc_now_iso(),
                         "claim_id": _claim_from_note(workspace, text, p.name),
                         "result": m.group(1).strip().lower(), "checker": "verify-note"}
        if not entry:
            continue
        key = _seen_key(entry)
        if key in seen:
            continue
        seen.add(key)
        new_lines.append(json.dumps(entry, ensure_ascii=False) + "\n")
        added += 1
    if new_lines:
        with open(ledger_path, "a", encoding="utf-8") as f:
            f.write("".join(new_lines))
    return added


def _claim_from_note(workspace: Path, text: str, name: str) -> str:
    fm = text.split("---", 2)
    if len(fm) >= 3:
        m = re.search(r"^claim_id:\s*([^\n]+)", fm[1], re.M)
        if m:
            return m.group(1).strip()
    return name  # fallback: 文件名作 claim 标识


def _claim_from_redteam(text: str, name: str) -> str:
    m = re.search(r"(?:claim\s*[:=]?\s*|target\s*[:=]?\s*)(C-\d+)", text, re.IGNORECASE)
    return m.group(1) if m else name


def aggregate_reward(rows: list[dict]) -> float | None:
    """纯函数: 结果值映射平均。无 OUTCOME 行 → None（中性，不误报 0 信号）。"""
    scores = [RESULT_SCORE.get(r.get("result"), 0.0) for r in rows
              if r.get("type") == LedgerLineType.OUTCOME]
    return sum(scores) / len(scores) if scores else None


def main() -> int:
    ap = argparse.ArgumentParser(prog="outcome_capture.py", description="external-checker outcomes → ledger")
    ap.add_argument("workspace")
    ap.add_argument("--reward", action="store_true", help="print aggregate reward scalar")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    ws = Path(args.workspace)
    added = capture(ws)
    rows = read_outcome_rows(ws)
    reward = aggregate_reward(rows)
    if args.reward:
        print(json.dumps({"reward": reward, "outcome_rows": len(rows)}) if args.json
              else f"reward={reward} (over {len(rows)} outcome row(s))")
    else:
        print(f"captured {added} new outcome row(s); {len(rows)} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
- **MIRROR**: LEDGER_READ + IDEMPOTENT_APPEND + OVERALL_VERDICT + PURE_FUNCTION
- **IMPORTS**: `from status_defs import LedgerLineType, ledger_line_type`（依赖 #34 已合并）
- **GOTCHA**: 两本账本不要混——只写 `.convergence_ledger.jsonl`；SNAPSHOT 行无 type 字段，`read_outcome_rows` 必须排除
- **VALIDATE**: `python scripts/test_outcome_capture.py` → 全绿

### Task 3: 回归 + PR
- **ACTION**: 跑全量测试，提交 PR
- **VALIDATE**: `python scripts/test_v1_8_enforcement_gates.py` 31/31；`python scripts/test_status_defs.py` 26/26；`python scripts/test_outcome_capture.py` 全绿；`python -m pytest tests/ -q` 无回归

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| test_capture_writes_outcome_row | verify-note passes 文件 | 1 行 type=outcome result=passes | 首行 |
| test_aggregate_reward_values | 4 行混合结果 | (1+0.5+0+1)/4 | 值映射 |
| test_dedup_same_claim_checker | 同 claim 两文件 + 两次 capture | 1 行 | 幂等 |
| test_no_data_neutral | 空 | None | 中性值 |
| test_snapshot_rows_ignored | 无 type 行 | [] | additive 兼容 |

### Edge Cases Checklist
- [x] runs/ 不存在 → capture 0（不炸）
- [x] 坏行（JSONDecodeError）→ 跳过
- [x] verify 文件无 verdict 节 → 跳过
- [x] red-team 无 claim 标识 → fallback 文件名
- [ ] concurrent capture（两个会话同时写）→ append 非原子；低风险，可用 tmp→replace 优化（不阻塞本计划）

---

## Validation Commands

### Unit Tests
```bash
cd C:/Users/hr/.claude/kunglao-remote-dev
python scripts/test_outcome_capture.py
```
EXPECT: 全绿

### Full Test Suite
```bash
python scripts/test_v1_8_enforcement_gates.py   # 31/31
python scripts/test_status_defs.py               # 26/26
python -m pytest tests/ -q
```
EXPECT: 全绿

### Manual Validation
- [ ] 构造 runs/ 一个 verify 文件 → `python scripts/outcome_capture.py <ws> --reward` 输出 reward 标量
- [ ] 重复跑两次 → outcome 行数不增（幂等）

---

## Acceptance Criteria
- [x] passes/partial/fails 三种 ledger 行 → 聚合输出正确标量
- [x] 重复 verify 不重复累计
- [x] 无数据返回中性
- [x] smoke 31/31 无回归
- [x] 零新 LLM 调用（纯机械）

## Completion Checklist
- [x] 契约只认 status_defs.LedgerLineType（不另造 type 常量）
- [x] 聚合只消费 OUTCOME 行（snapshot 永不参与）
- [x] reward 不 gate 任何门（软信号）
- [x] 幂等去重（同 claim 同 checker）

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `## Overall verdict` 格式漂移 | Medium | 漏 capture | 正则宽松（`\s*\n+\s*`）+ fallback 文件名 |
| ledger 并发 append 竞态 | Low | 坏行 | 低风险；后续可 tmp→replace（非本计划阻塞） |
| verify-note 产物在 malware-veri-notes（外部 skill） | Low | 跨仓依赖 | 只读该 skill 的产物格式，不 import |

## Notes
- `ledger_line_type()` 目前零生产调用者（explore agent A4 实测）——本计划是第一消费者，顺带把 #34 的契约用上
- 有两本账本：`.convergence_ledger.jsonl`（本计划）vs `ledger.jsonl`（kunglao_record 用）——**不要混写**
- reward 接线 priority 是 R6 的下一步（等 ≥2 样本），本计划只落盘 + 聚合
