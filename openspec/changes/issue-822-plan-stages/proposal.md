# proposal: issue-822-plan-stages

## Why

计划工件缺阶段层（真实缺口 #822 body v2）：
1. stage 计划工件不存在——global_plan.txt 为 init 一行 stub，无 stage 模板与正文约定
2. 盘点仪式不存在——无"stage 边界或每 K 轮：战果×成本×斜率 → maintain/adjust/replan 三选一裁决并落盘"回路
3. 正向重规划触发缺失——#634 熔断只到 PARK，drift HARD_PAUSE 只阻断；重规划应先于 PARK

## What Changes

新增 `scripts/plan_stages.py`（自包含模块+CLI，不触 convergence_check 以避免与并行 W3 fork 冲突；PARK 前置重规划的 convergence 接线在 proposal 记录为后继 hook 点）：

1. **stage 计划工件** `runs/plan-stages.yaml`：stages[]（id/name/goal/claims/expected_evidence/exit_criteria/next_candidates/status），机器可校验（必填字段/唯一 id/合法 status 枚举）
2. **BIG_BANG_PLAN 检测**（校验面 fail-closed）：plan-stages.yaml 缺失/单 stage 活跃/global_plan.txt 仍为 init stub → BIG_BANG_PLAN 违规，`--check` 非零退出
3. **盘点裁决回路**：`review()` —— verdict ∈ maintain/adjust/replan；adjust/replan 必须带 trigger reason（缺即拒）；裁决追加进 yaml reviews[] + 落 runs/plan-review-<ts>.md + ledger `plan_review` 事件（EMIT_ACTIONS 注册，字母序）
4. CLI：`--check <ws>`（校验面）、`--review <ws> --stage <id> --verdict <v> --reason <r>`

## Impact

- 新文件：scripts/plan_stages.py、tests/test_plan_stages_822.py
- 修改：scripts/event_taxonomy.py（+plan_review）、scripts/README.md（catalog 行）、manifests（如 sha 变）
- 不做：convergence_check/heartbeat 接线（后继 hook 点已记录）、PARK 前置重规划的自动触发（需 #634/#711 稳定后接入）
