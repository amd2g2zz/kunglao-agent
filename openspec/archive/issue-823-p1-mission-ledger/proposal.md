# Proposal: #823-P1 mission_ledger — 主线欠账表 + V_m（shadow）

## Why

v0.1.3 的主线停滞病理：边角料 claim 全 PROVEN 而主问题零覆盖，系统不知情（审计 §9"从未建造评估函数"、蓝图 §7 前提条件 1）。#823 的值函数必须**锚定主线欠账表而非活动量**——这是本卡的核心验收（防傻断言）。

## What Changes

- 新 `scripts/mission_ledger.py`（shadow 形态：只计算+落盘，不改任何决策路径）：
  - `init(ws, task_spec)`：从 task_spec.primary_questions 机械生成 `runs/mission_ledger.yaml` 欠账表（PQ 三态 answered/blocked/unattempted；blocked 必带 blocker+wake_condition 否则拒绝）
  - `update(ws)`：PROVEN claim 的 answers_question 归属 → PQ coverage/state 刷新（机械 0/1 覆盖，ρ_t 语义覆盖属 P2）
  - `mark_blocked(ws, pq, blocker, wake)` / `load(ws)` 只读
  - `value_m(ws)`：`V_m = Σ w_i·coverage_i·[answered] + β·Σ w_i·[blocked]`（β=0.3 默认）+ `A_t = V_m−prev`（历史存 ledger 文件）
  - `emit_snapshot(ws)`：mission 覆盖快照走 #818 schema（action=mission_snapshot，arm/epoch/version 沿用）
- `scripts/event_taxonomy.py`：EMIT_ACTIONS 注册 `mission_snapshot`（sorted 位置）
- `scripts/README.md`：catalog 行

## 防傻断言（本卡验收核心）

1. 合成"边角料 claims 全 PROVEN、与 PQ 零关联"workspace → update() 后 coverage 全 0，V_m 增量**严格 =0**
2. "PROVEN claim 命中 PQ" → V_m 上升
3. blocked 信用只随合法（blocker+wake）标记出现

## Out of Scope

ρ_t verifier（P2）· Q 表喂 priority（P3）· 系数重拟合（P4）· decide/priority 行为改动 · 主线停滞指纹（#634）· THINK（#711）
