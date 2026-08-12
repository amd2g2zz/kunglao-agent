# Plan: #36 DLQ — DEAD 状态 + quarantine 隔离毒 claim

## Summary
3 次尝试耗尽后 claims 悬空污染 open 集（实测 claim-register 85 个 status 无 DEAD/POISON，存在脏值 `PASS-` 1 条与终态枚举混杂）。本计划把 DEAD 加入 status_defs.TERMINAL（#34 单一源，只加一处），耗尽 claim（promotion_attempts>=3）→ DEAD + `blockers/dead-letter-<claim>.md` 隔离 artifact，从 dispatchable 集排除（convergence_check._open_claims 自动生效），worker_pulse 加 quarantined=N 行，并顺手规范化终态枚举（PASS- 类脏值检测）。

## User Story
作为 kunglao-agent 的 orchestrator，我希望 3 次尝试耗尽仍未闭环的 claim 进入 DEAD 终态并被隔离，这样它们不再污染 open 集（不无限重试、不占 dispatch 名额），失败历史有据可查。

## Problem → Solution
`promotion_attempts>=3` 的 claim 目前仍可能 OPEN（悬空）→ 把 DEAD 加入 TERMINAL（status_defs 一处）+ `mark_dead` 写入 claim-register + `blockers/dead-letter-<claim>.md` 隔离 artifact + `_open_claims` 排除（TERMINAL 含 DEAD 自动生效）+ worker_pulse quarantined 行 + `PASS-` 脏值检测脚本。

## Metadata
- **Complexity**: Medium
- **Source PRD**: GitHub issue #36（无独立 PRD）
- **PRD Phase**: N/A（standalone）
- **Estimated Files**: 5（scripts/status_defs.py、scripts/dead_letter.py、scripts/test_dead_letter.py、hooks/worker_pulse.py、scripts/test_status_defs.py）

---

## UX Design

### Before
```
promotion_attempts=3 + status=OPEN → 悬空（priority 每轮重推，重试循环浪费成本）
脏值 PASS- → 既非终态也非 OPEN，状态机混乱
```

### After
```
promotion_attempts>=3 → DEAD（TERMINAL）+ blockers/dead-letter-<claim>.md
  → _open_claims 自动排除（TERMINAL 含 DEAD）
  → worker_pulse flags 行 quarantined=N
  → PASS- 脏值被 detect_dirty_statuses 标出
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| status_defs.TERMINAL | 6 值（含 STALE） | 7 值（+DEAD） | #34 操作手册第 1 步已写 |
| _open_claims | TERMINAL 排除 | 自动含 DEAD | 零代码改（#34 设计） |
| priority / convergence_check | 可能重推耗尽 claim | 自动排除 | 同上 |
| claim-register | 无 DEAD | DEAD 可写入 | mark_dead 显式写 |
| worker_pulse | flags 无 quarantined | +quarantined=N | #36 范围 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `scripts/status_defs.py` | 全文 (85 行) | TERMINAL 集合 + docstring 的 DEAD 操作手册（:49-59 明确步骤） |
| P0 | `scripts/convergence_check.py` | 123-130, 74-120 | `_open_claims`（TERMINAL 排除 — DEAD 自动生效）、`_scan_active_workers` |
| P0 | `hooks/worker_pulse.py` | 104-147 | `_build_pulse` flags 组装（stuck/failure-blocked/partial/blockers）— quarantined 加这 |
| P1 | `scripts/priority.py` | 64-68, 148-162 | `_is_open`（TERMINAL 排除）— DEAD 自动排除 |
| P1 | `scripts/test_status_defs.py` | 24-38, 87-112 | TERMINAL 6 值断言（+DEAD 后须改 7 值）、consumer 无自有状态集守卫 |
| P2 | `scripts/claim_expiry.py` | 77-91 | STALE 写入模式（status+stale_at+stale_reason 三字段）— mark_dead 镜像 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| N/A | — | 纯内部——#34 已预留 DEAD 操作手册 |

---

## Patterns to Mirror

### DEAD_PROCEDURE（status_defs docstring 操作手册 — scripts/status_defs.py:49-59 逐字）
```
Adding a new status (operating manual, e.g. #36 DEAD)
1. Add it to the canonical legal set below (and to TERMINAL iff a DEAD
   claim needs no further work — yes for DLQ).
2. Check it against PARTIAL_STATUSES / IN_PROGRESS_STATUSES — a new
   terminal status must NOT be in either.
3. Consider ledger impact: DEAD is a claim status, not a ledger row type —
   no LedgerLineType change needed.
4. Consumers pick it up automatically; the grep guard in
   test_status_defs.py (test_consumer_has_no_own_status_set) prevents a
   hardcoded copy from drifting.
```

### TERMINAL_EXCLUSION（_open_claims — scripts/convergence_check.py:123-130 逐字）
```python
def _open_claims(reg: dict):
    out = []
    for c in (reg.get("claims") or []):
        status = (c.get("status") or "UNKNOWN").upper()
        if status not in TERMINAL and status not in IN_PROGRESS_STATUSES:
            out.append({"id": c.get("id"), "status": status, "blocked": bool(c.get("blocked"))})
    return out
```
// DEAD ∈ TERMINAL → 自动排除，零代码改

### STALE_WRITE（状态写入三字段模式 — scripts/claim_expiry.py:93-100 逐字）
```python
        if apply and stale:
            for s in stale:
                for c in claims:
                    if c.get("id") == s["claim_id"]:
                        c["status"] = "STALE"
                        c["stale_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                        c["stale_reason"] = f"no activity for {s['age_hours']:.1f}h"
                        break
```

### PULSE_FLAGS（flags 组装 — hooks/worker_pulse.py:118-129 逐字）
```python
        flags = []
        if d.get("stuck_workers"):
            flags.append(f"stuck={[w['worker'] for w in d['stuck_workers']]}")
        if d.get("failure_blocked"):
            flags.append(f"failure-blocked={list(d['failure_blocked'])}")
        ...
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `scripts/status_defs.py` | UPDATE | TERMINAL + `"DEAD"`（第 7 值）+ docstring 引用 #36 已落地 |
| `scripts/dead_letter.py` | CREATE | mark_dead（写入 claim-register + dead-letter artifact）+ scan（检测耗尽未 DEAD 的悬空 claim）+ detect_dirty_statuses（PASS- 类脏值） |
| `scripts/test_dead_letter.py` | CREATE | TDD RED 先写 |
| `hooks/worker_pulse.py` | UPDATE | flags 加 `quarantined=N`（来自 dead_letter scan） |
| `scripts/test_status_defs.py` | UPDATE | TERMINAL 6→7 值断言 + DEAD 相关断言 |

## NOT Building

- 不改 convergence_check / priority（DEAD ∈ TERMINAL 自动排除——#34 设计意图）
- 不自动强制 DEAD（只 mark_dead 显式写 + scan 报告悬空）
- 不做 poison claim 自动恢复 / 复活机制（issue 范围外）
- 不引入新 ledger 行类型（DEAD 是 claim 状态，status_defs 手册第 3 步已确认）

---

## Step-by-Step Tasks

### Task 1: RED — test_dead_letter.py + test_status_defs.py 更新
- **ACTION**: 先写测试（TDD RED）
- **IMPLEMENT**:
```python
# test_dead_letter.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import dead_letter as dl

def _mk_reg(ws, claims):
    import yaml
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

def test_dead_excluded_from_open(tmp_path):
    """DEAD 状态从 dispatchable 排除（经 convergence_check._open_claims）"""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "DEAD", "promotion_attempts": 3}])
    import yaml
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import convergence_check as cc
    reg = yaml.safe_load((tmp_path / "claim-register.yaml").read_text(encoding="utf-8"))
    assert cc._open_claims(reg) == []

def test_mark_dead_writes_artifact(tmp_path):
    """耗尽 claim → DEAD + dead-letter artifact"""
    _mk_reg(tmp_path, [{"id": "C-2", "status": "OPEN", "promotion_attempts": 3}])
    r = dl.mark_dead(tmp_path, "C-2", reason="3 attempts exhausted")
    assert r["status"] == "DEAD"
    assert (tmp_path / "blockers" / "dead-letter-C-2.md").exists()

def test_scan_finds_exhausted_open(tmp_path):
    """promotion_attempts>=3 且未 DEAD 的悬空 claim 被 scan 报告"""
    _mk_reg(tmp_path, [{"id": "C-3", "status": "OPEN", "promotion_attempts": 3}])
    assert dl.scan(tmp_path) == ["C-3"]

def test_detect_dirty_statuses(tmp_path):
    """PASS- 类脏值可被检测"""
    _mk_reg(tmp_path, [{"id": "C-4", "status": "PASS-"}, {"id": "C-5", "status": "OPEN"}])
    assert "C-4" in dl.detect_dirty_statuses(tmp_path)
```
test_status_defs.py 更新（:26-29）：
```python
def test_terminal_is_7_valued_with_stale_and_dead():
    assert status_defs.TERMINAL == {
        "PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED", "STALE", "DEAD",
    }
```
- **MIRROR**: TERMINAL_EXCLUSION + DEAD_PROCEDURE
- **IMPORTS**: yaml、convergence_check（sibling import）
- **GOTCHA**: test_status_defs 的 TERMINAL 断言从 6 值改 7 值——`test_terminal_is_6_valued_with_stale` 名字也要改（改名为 is_7_valued）
- **VALIDATE**: 先跑全红

### Task 2: GREEN — status_defs + dead_letter.py
- **ACTION**: TERMINAL 加 DEAD；实现 dead_letter.py
- **IMPLEMENT**:
```python
# status_defs.py TERMINAL（:62）
TERMINAL = {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED", "STALE", "DEAD"}
# docstring 加一行说明 #36 落地（TERMINAL 6 值 → 7 值）
```
```python
# dead_letter.py
"""dead_letter.py - DEAD 状态 + quarantine 隔离毒 claim (#36).

3 次尝试耗尽仍未闭环的 claim 悬空污染 open 集。DEAD 加入
status_defs.TERMINAL（#34 单一源只加一处）→ convergence_check._open_claims /
priority._is_open 自动排除。本脚本提供显式写入 + 隔离 artifact + 悬空检测。

用法:
  python dead_letter.py <workspace>                    # scan：报告耗尽未 DEAD 的悬空 claim
  python dead_letter.py <workspace> --mark C-NN        # mark_dead：写入 DEAD + dead-letter artifact
  python dead_letter.py <workspace> --dirty            # detect_dirty_statuses：PASS- 类脏值
"""
from __future__ import annotations
import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from status_defs import TERMINAL

VALID_STATUS_RE = re.compile(r"^[A-Z][A-Z_ -]*$")  # 终态枚举规范化


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _load_reg(workspace: Path) -> tuple[list, dict, Path]:
    p = workspace / "claim-register.yaml"
    if not p.exists():
        return [], {}, p
    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return reg.get("claims") or [], reg, p


def scan(workspace: Path) -> list:
    """promotion_attempts>=3 且未 DEAD/终态的悬空 claim。"""
    claims, _, _ = _load_reg(workspace)
    out = []
    for c in claims:
        status = (c.get("status") or "UNKNOWN").upper()
        if status in TERMINAL:
            continue
        if int(c.get("promotion_attempts") or 0) >= 3:
            out.append(c.get("id"))
    return out


def mark_dead(workspace: Path, claim_id: str, reason: str = "") -> dict:
    """写入 claim-register DEAD + blockers/dead-letter-<claim>.md 隔离 artifact。"""
    claims, reg, p = _load_reg(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if not claim:
        return {"marked": False, "reason": f"claim {claim_id} not found"}
    claim["status"] = "DEAD"
    claim["dead_at"] = utc_now_iso()
    claim["dead_reason"] = reason or "promotion_attempts exhausted (DLQ)"
    p.write_text(yaml.safe_dump(reg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    bdir = workspace / "blockers"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / f"dead-letter-{claim_id}.md").write_text(
        f"# Dead Letter: {claim_id}\n\n"
        f"- status: DEAD\n- dead_at: {claim['dead_at']}\n- dead_reason: {claim['dead_reason']}\n"
        f"- promotion_attempts: {claim.get('promotion_attempts')}\n"
        f"- failure history: see analyses/failure-{claim_id}.yaml\n",
        encoding="utf-8",
    )
    return {"marked": True, "claim_id": claim_id, "status": "DEAD"}


def detect_dirty_statuses(workspace: Path) -> list:
    """终态枚举规范化: 找出 PASS- 类脏值（非合法状态字面量）。"""
    claims, _, _ = _load_reg(workspace)
    legal = TERMINAL.union({"OPEN", "IN_PROGRESS", "PARTIALLY-VERIFIED",
                            "PARTIAL", "PARTIALLY_VERIFIED", "STAMP", "UNVERIFIED"})
    dirty = []
    for c in claims:
        status = (c.get("status") or "").strip()
        if not status:
            continue
        if not VALID_STATUS_RE.match(status) or status not in legal:
            dirty.append(c.get("id"))
    return dirty


def main() -> int:
    ap = argparse.ArgumentParser(prog="dead_letter.py", description="DLQ — DEAD status + quarantine")
    ap.add_argument("workspace")
    ap.add_argument("--mark", metavar="C-NN", help="mark claim as DEAD")
    ap.add_argument("--dirty", action="store_true", help="detect dirty status values")
    args = ap.parse_args()
    ws = Path(args.workspace)
    if args.mark:
        r = mark_dead(ws, args.mark)
        print("MARKED" if r.get("marked") else f"REJECTED: {r.get('reason')}")
        return 0 if r.get("marked") else 1
    if args.dirty:
        dirty = detect_dirty_statuses(ws)
        print(f"{len(dirty)} dirty status value(s): {dirty}")
        return 1 if dirty else 0
    exhausted = scan(ws)
    print(f"{len(exhausted)} exhausted-but-not-DEAD claim(s): {exhausted}")
    return 1 if exhausted else 0


if __name__ == "__main__":
    sys.exit(main())
```
- **MIRROR**: DEAD_PROCEDURE + STALE_WRITE（三字段写入模式）
- **IMPORTS**: `from status_defs import TERMINAL`
- **GOTCHA**: status_defs docstring 的「TERMINAL 6 值」多处文字（:10-19）要同步改成 7 值，否则文档与代码矛盾；consumer 无自有集合守卫（test_status_defs :87-92）继续有效
- **VALIDATE**: `python scripts/test_dead_letter.py` 全绿；`python scripts/test_status_defs.py` 全绿（改后）

### Task 3: worker_pulse quarantined=N
- **ACTION**: _build_pulse flags 加 quarantined
- **IMPLEMENT**: flags 组装处（:118-129）追加：
```python
        if d.get("quarantined"):
            flags.append(f"quarantined={d['quarantined']}")
```
  其中 `quarantined` 来自 convergence_check.json 输出——需要 convergence_check 的 json 里带 quarantined 计数（或 pulse 直接调 dead_letter.scan）。**本计划最小实现**：pulse 里直接 `_run_py(dead_letter.py <ws>)` 解析 stdout 的 count 数字，追加 `quarantined=N`。
- **MIRROR**: PULSE_FLAGS
- **IMPORTS**: 无（_run_py 已有）
- **GOTCHA**: convergence_check 的 json 现无 quarantined 字段——不改它（issue 范围只要求 pulse 加行）。pulse 直接跑 dead_letter scan 更内聚
- **VALIDATE**: 构造 1 个耗尽 claim → pulse flags 含 `quarantined=1`

### Task 4: 回归 + 终态枚举规范化（顺手项）
- **ACTION**: 跑全量测试；对真实 workspace 跑 `dead_letter.py --dirty` 确认 PASS- 检出（不自动修——只报告）
- **VALIDATE**: `python scripts/test_v1_8_enforcement_gates.py` 31/31；`python scripts/test_status_defs.py` 26→27 全绿；`python scripts/test_dead_letter.py` 全绿；`python -m pytest tests/ -q` 无回归

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| test_dead_excluded_from_open | DEAD claim | _open_claims == [] | TERMINAL 自动排除 |
| test_mark_dead_writes_artifact | 耗尽 OPEN claim | DEAD + dead-letter-<id>.md | artifact 写入 |
| test_scan_finds_exhausted_open | attempts=3 OPEN | ["C-3"] | 悬空检测 |
| test_detect_dirty_statuses | PASS- 值 | ["C-4"] | 脏值检测 |
| test_terminal_is_7_valued | status_defs | 7 值含 DEAD | 集合断言 |

### Edge Cases Checklist
- [x] DEAD ∈ TERMINAL → 自动排除（零代码改）
- [x] claim 不存在 → mark_dead REJECT
- [x] attempts<3 → scan 不报
- [x] PASS- 脏值 → detect 检出（不自动修）
- [ ] 已 DEAD → scan 不再报（TERMINAL 短路）
- [ ] dead-letter 目录不存在 → mark_dead mkdir

---

## Validation Commands

### Unit Tests
```bash
cd C:/Users/hr/.claude/kunglao-remote-dev
python scripts/test_dead_letter.py
python scripts/test_status_defs.py
```
EXPECT: 全绿

### Full Test Suite
```bash
python scripts/test_v1_8_enforcement_gates.py   # 31/31
python -m pytest tests/ -q
```
EXPECT: 全绿

### Manual Validation
- [ ] `python scripts/dead_letter.py <ws>` → 报告耗尽未 DEAD claim
- [ ] `python scripts/dead_letter.py <ws> --mark C-NN` → claim DEAD + artifact
- [ ] `python scripts/dead_letter.py <ws> --dirty` → PASS- 检出
- [ ] `grep -rn "DEAD" scripts/ hooks/` → 只有 status_defs 一处定义（验收：全仓 grep DEAD 只认 status_defs）

---

## Acceptance Criteria
- [x] DEAD 状态从 dispatchable 排除（TERMINAL 自动生效）
- [x] 耗尽 claim → dead-letter artifact
- [x] PASS- 脏值可被检测
- [x] worker_pulse 输出含 quarantined=N
- [x] 全仓 grep DEAD 只认 status_defs 一处（consumer 无自有集合守卫兜底）

## Completion Checklist
- [x] DEAD 只在 status_defs 一处定义（#34 手册第 1 步）
- [x] PARTIAL/IN_PROGRESS 不含 DEAD（手册第 2 步）
- [x] 无 ledger 行类型变更（手册第 3 步）
- [x] consumer 自动拾取（手册第 4 步——grep 守卫测试验证）

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| TERMINAL 加 DEAD 影响旧测试断言 | Medium | test_status_defs 红 | Task 1 显式改 6→7 值断言 |
| docstring「6 值」文字残留 | Low | 文档矛盾 | Task 2 GOTCHA 显式同步 |
| 真实 workspace 已有悬空 claim 被 scan 报告 | High | 输出噪声 | scan 只报告不自动修；真实 ws 的悬空按 DLQ 决策处理 |

## Notes
- issue 实测：claim-register 85 个 status 无 DEAD/POISON，存在 `PASS-` 脏值 1 条——本计划 detect_dirty_statuses 只检出不修
- `#34 操作手册`（status_defs docstring :49-59）本就是为 #36 预留——本计划是它的首次落地
- worker_pulse 的 quarantined 直接跑 dead_letter scan（不依赖 convergence_check json 扩展——后者不在本 issue 范围）
