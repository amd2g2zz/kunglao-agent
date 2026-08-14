# specs/ — 可执行 spec 层(阶段 0 建立)

## 双层 spec 规则

- **层 1 master spec(只读)**: `.research-tree-alignment/` 的
  `kong-agent-refactor-plan.md`(目标/验收) / `kong-agent-design-spec.md`(架构/算法) /
  `kong-agent-module-design.md`(子模块契约)。冲突仲裁: design-spec 为准。
- **层 2 可执行 spec(本目录 + schemas/)**: 每阶段 `phase-N/contract.md` 从
  module-design.md **摘录**(带出处行号, 不转录) + `schemas/*.json`(JSON Schema 即代码)。

## 冻结仪式(每阶段 Step 0)

contract.md 头部写:
`FROZEN @ phase-N, 变更条件: ① 先写一条 RED 测试证明现状不满足新契约 ② 改 contract.md + schemas/ ③ 同步回写 master 三份文档之一 ④ 同一 commit 内完成`

**契约变更的唯一合法入口 = RED 测试。** 没有测试背书, spec 不许改。

## golden master 变更流程

`tests/fixtures/golden/expected/` 是重构前的行为基线, 权威。

- 用例行为**合法改变**(新契约允许) → 走冻结仪式: RED 测试 → 改 spec → `python tools/auxiliary/capture_golden.py --refresh` 重新采集 → 同 commit。
- 用例行为**非预期改变**(回归) → 不允许 --refresh, 必须修复实现。

## 阶段 0 明确不做的决定(防反复)

1. **旧测试零迁移**: 10 个 test_*.py 留在 `scripts/`, 用 pytest.ini `testpaths = scripts tests` 双目录覆盖; `if __name__ == "__main__"` 直跑模式保留(手动运行兼容)。
2. **不引入 OpenSpec**: 契约是 CLI stdout JSON + YAML 状态文件, 非 HTTP API; 双层 spec 零转录。若多人协作评审期需要 change 生命周期再评估。
3. **时间戳归一化**: golden 重放对 `(ISO-UTC)` 时间戳做 `<TS>` 归一化(采集/重放跨秒), 其余逐字节。
