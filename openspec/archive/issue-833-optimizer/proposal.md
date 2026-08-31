## Proposal

#833 优化器基础设施层（三通道的数值+开关两通道；OPRO verbal 通道与 P4 学费曲线接线留后续卡）。

### 设计

**optimizer_core.py**（θ 数值通道）
- `PARAM_SPEC`：~20 个可优化参数的 schema（名/默认/界），schema_version 固定 `opt-theta-v1`
- **宪法隔离**：`CONSTITUTIONAL_KEYS`（终态门/maker-checker/fail-closed 默认等）不可入 spec、不可入提案——`validate_spec`/`make_proposal` 双重拒绝
- `spsa_step`/`spsa_optimize`：Rademacher ±δ 扰动 → 差分梯度 → 步长 α，界内裁剪；δ/α/迭代数可配
- `replay_loss(missions, θ)`：反事实损失 = cost_weight·cost + false_abandon_weight·false_abandon + gap_weight·gap（规则近似重放，非完整决策复刻——近似边界：不模拟 worker 行为，只对已结算 mission 的结局指标按 θ 重加权）
- `make_proposal`：提案 JSON（schema_version/kind/theta_old/theta_new/evidence/base_sha）；**只出提案不生效**——模块无任何写 value_config/门的路径（结构断言入测试）

**optimizer_bandit.py**（开关通道）
- β-Bernoulli 后验（arm = 机制×泳道），`update`/`posterior`/`record_outcome`（消费 ledger 行的 arm 字段归因）
- `demotion_queue`：min_pulls 后均值低于 floor 的臂入降级队列（四阶段门的降级候选，不直接生效）

**git 底座**：提案文件即分支建议（本批次不实现自动 revert）；版本字段记 base_sha。

### 近似边界（诚实声明）

L(θ) 的回放是规则近似：对已结算 mission 的 (cost, false_abandon, gap) 三元组按 θ 重加权求和，不复刻 worker 决策序列。这使 L(θ) 对"结局已定的重加权"敏感、对"决策序列分叉"不敏感——SPSA 梯度在该近似下的含义是"哪些权重的边际重排能改善历史结局组合"，非完整策略梯度。完整重放模拟器留 P4。

### Impact

- 新文件：scripts/optimizer_core.py、scripts/optimizer_bandit.py、tests/test_optimizer_core_833.py、tests/test_optimizer_bandit_833.py
- 不改：value_config、终态门、priority/convergence 行为
- 验收映射：宪法不可达 → 测试；L(θ) 好<坏 → 测试（豆包=坏样本判负）；回滚演练/元学费曲线 → P4 接线后可跑
