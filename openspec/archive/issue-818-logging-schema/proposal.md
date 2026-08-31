# Proposal: issue-818-logging-schema (batch 1)

## Why

豆包现场取证（AUDIT_REPORT §11）：日志是产品生命线，但 v0.1.3 事件行缺 arm/epoch/version/hypothesis_ref——AB 两臂的轨迹无法按臂归因，策略纪元与派发所引用的在押假设不可追溯。这是 #818 schema 部分的 W1 批次（severity 分级、worker 遥测面、覆盖率门属后续批次，见 issue 全文）。

## What Changes

- `scripts/kunglao_log.py` `emit()` 增加向后兼容 kwargs：`arm` / `epoch` / `version`（自动填充 git SHA，subprocess 失败→None）/ `hypothesis_ref`；缺省为显式 null 键（schema 稳定）
- `scripts/event_taxonomy.py` `EMIT_ACTIONS` 新增受控词 `decision_snapshot`
- `scripts/convergence_check.py` `decide()` 每次判定 emit 一条 `decision_snapshot`（actor=convergence_check）：claims 状态计数 + top-5 priority (id, score)；emission fail-open，永不阻断判定
- 新测试 `tests/test_logging_schema_818.py`：5 例（字段落盘、null 键稳定、version 自动填充类型、decide 快照内容、emission 永不破坏判定）

## Impact

- Affected: scripts/kunglao_log.py、scripts/event_taxonomy.py、scripts/convergence_check.py、tests/test_logging_schema_818.py（新增）
- Not affected: ρ/V_m（#823-P2/P3）、severity 分级（#818 后续批次）、worker 遥测面（Part C）
- 消费者兼容：旧行缺键、新行显式 null；tail()/--tail 读侧不变
