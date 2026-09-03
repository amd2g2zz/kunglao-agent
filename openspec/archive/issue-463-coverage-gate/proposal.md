# Proposal — 4-Gate Quality Framework (issue #463, v0.1.2 修正版)

## Why

issue #463 原始提案是"测试覆盖率门 ≥75%"。**这是错的优化目标**。

光提升覆盖率、测试数、Unit Test 数量 → 形成 Test → Test Test → Test Test Test
的递归膨胀。Unit Test 是手段,不是指标。Coverage 和 Test Case Count 只能观测,
不得作为优化目标。

真实 KPI:**First-Pass Acceptance / Defect Escape / Regression / Rework**。

## What

实施 4 质量门框架,作为所有 Agent 代码变更的强制验证流程:

| Gate | 验证什么 | 用什么验证 |
|---|---|---|
| **1. 需求正确性** | Agent 是否真完成需求 | Acceptance / Contract / Schema / Invariant / Critical Scenario |
| **2. 回归安全** | 是否破坏已有功能 | Regression / Integration / E2E / Historical Bug Cases |
| **3. 工程质量** | 是否恶化代码质量 | Build / Lint / Security / Architecture / Complexity / Change Size |
| **4. 测试有效性** | 测试真能发现错误 | Mutation / Critical Path / Property / Boundary |

## Coverage 重新定位

- **Global Coverage**:仅长期监控
- **Changed Code Coverage**:辅助判断本次变更(不是门槛)
- **Critical Path Coverage**:核心路径必须覆盖
- **禁止** Coverage 70%→80%→90% 作主目标
- **禁止** 为 Coverage 写低价值测试

## Test Case Count 重新定位

- 只统计,不 KPI
- 不作 Agent 优化目标
- 不因测试少就默认差
- 不因测试多就默认好

## Why this PR

1. 把 4-gate 框架文档化(`devkit/docs/quality_gates.md`)
2. 配套 mutation testing 工具接入(mutmut,P2 才上 CI,P1 本地)
3. CI 不再以 Coverage 为 fail 门槛(改成报告 + 观测)
4. KPI 跟踪:`devkit/docs/defect_escape_rate.md` 已建,继续扩展 First-Pass / Rework
5. **不**新增 Unit Test 凑数 — 这是反模式

## Acceptance

- [ ] `devkit/docs/quality_gates.md` 框架文档
- [ ] pytest.ini:`--cov-fail-under` **删除**(只保留 `--cov` 报告)
- [ ] CI:coverage 不再 fail;新增 mutation step(本地跑,CI 上传结果)
- [ ] `devkit/docs/defect_escape_rate.md` KPI 跟踪(扩展 First-Pass / Rework Rate)
- [ ] `devkit/pass_rate_metric.py` 降级为观测(不 fail CI)
- [ ] log_setup + test_log_setup 保留(独立基础设施,不是测试质量)

## Out of scope(明确不做)

- 不写"凑 Coverage"测试
- 不引入测试数量 KPI
- 不以"测试全过"判定需求正确
- 不为 Mutation Score 设硬阈值(P2 才考虑)

Refs: user directive "测试是手段不是指标"
