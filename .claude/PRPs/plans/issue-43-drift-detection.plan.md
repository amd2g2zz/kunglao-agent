# Plan: drift detection — ledger signature rotation（#43）

## Summary
为 `external_kicker.should_kick` 加**漂移检出**：ledger signature rotation（≥3 连续相同 snapshot = 活呆）。时间法（`ledger_stalled`）检不出活呆——session 心跳新鲜、ledger 在写，但状态签名连续不变（F2 非线性退化 + F3 SED step-local-invisible）。

## 问题 → 方案
- **问题**：#39 的 `should_kick` 只检死（heartbeat stale）+ 死呆（ledger stalled >25min）。活呆（心跳新鲜 + 签名冻结）漏检。
- **方案**：加 `signature_rotation` 检出 + `workers_progressing` 豁免。drift 在 `[ROTATION_WINDOW=3, ESCALATE=6)` 区间只触发 hook 重锚（#44 治本），`≥6` 才 kick（治本先于恢复）。

## Metadata
- **Complexity**: Small（3 函数 + `should_kick` 加分支 + 常量）
- **Source issue**: #43（parent #39, blocked-by #39）
- **Research**: F2（非线性 regime shift）、F3（SED step-local-invisible）→ `.claude/PRPs/research/long-horizon-agent-failure.md`

## Mandatory Reading
| Priority | File | Why |
|---|---|---|
| P0 | `issue-39-external-kicker.plan.md` Task 2 的 `_state_signature` / `signature_rotation` / `workers_progressing` / `drift_detected` 段 + `should_kick` drift 分支 | 完整函数代码（逐字移植） |
| P0 | `research/long-horizon-agent-failure.md` F2/F3 | 漂移检出根因 |
| P1 | `scripts/convergence_check.py` `_append_ledger`（snapshot 字段） | signature tuple 来源 |
| P1 | `scripts/backtrack_gate.py:64-128` | `workers_progressing` mtime 同源阈值 |

## Patterns to Mirror
见总设计 plan 的 `LEDGER_SIGNATURE` / `LEDGER_READ` / `STALE_WORKERS_MTIME` / `OPEN_CLAIMS` section。

## Files to Change
| File | Action | scope |
|---|---|---|
| `scripts/external_kicker.py` | UPDATE（#39 已 CREATE 骨架） | 加常量 `ROTATION_WINDOW=3` / `DRIFT_ESCALATE_ROWS=6` / `WORKER_PROGRESS_MINUTES=20`；加 `_state_signature` / `signature_rotation` / `workers_progressing` / `drift_detected`；`should_kick` 加 drift 分支；`main` / `--check` 输出 rotation/drift |
| `tests/test_drift_detection.py` | CREATE | TDD RED 先行 |

## Step-by-Step Tasks

### Task 1: RED — `test_drift_detection.py`
4 用例（见 issue #43 body TDD）：构造 fixture ledger（rotation=3/2/变化）+ worker-status 文件（mtime 豁免场景）。

### Task 2: GREEN — `external_kicker.py` 加 drift
代码见总设计 plan Task 2 对应函数段（常量 + 4 函数 + should_kick 分支 + main 输出）。逐字移植。

### Task 3: 验证
`python tests/test_drift_detection.py` 全绿；`--check` 对漂移 fixture 报 `drift=YES kick_needed=True`（rotation≥6 时）。

## Acceptance Criteria（= issue #43 验收）
- [ ] 活呆 session（心跳新鲜 + ledger 签名冻结）被检出
- [ ] `workers_progressing` 不误伤合法 SATURATED
- [ ] 阈值常量化、可调
- [ ] RED → GREEN → PR → dev

## Risks
| Risk | Mitigation |
|---|---|
| signature tuple 字段选错（漏 blockers → 假阴性） | 严格按 `_append_ledger` 的 snapshot 字段（decision/open_ids/partial_count/active_workers/blockers/facts_total，排 ts） |
| workers_progressing 误判（worker 卡但仍 in-progress） | mtime <20min 才豁免；>20min 的 in-progress = 真卡（backtrack_gate 同源） |
