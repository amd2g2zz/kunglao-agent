# Quality Gates — 质量门框架 (issue #463, v0.1.2;门清单见 devkit/quality_gates.py GATES 注册表)

> **核心原则**:质量门验证**交付结果**,不验证 Agent 做了多少工作。
> 禁止通过无限增加测试证明测试质量。Unit Test 是手段,不是指标。
> 覆盖率与测试数只能作为观测,不得作为优化目标。
> 最终以 First-Pass Acceptance / Defect Escape / Regression / Rework 衡量交付质量。

## The Gates

> 本页图示为 #463 初版门集(初版门数见 git 史)。后续门按注册表追加:Gate 5
> Subagent Review(#462)、Gate 6 Agents Contract(#492)、Gate 7 Doc Sync
> (#446)。**门清单的唯一来源是 `devkit/quality_gates.py` 的 GATES
> 注册表** — 本文不复制计数(派生不复制,#446 G 类)。

```
Agent 代码变更
       │
       ▼
 ┌─ Gate 1 ─┐   需求正确性 — Agent 是否真正完成需求?
 │  Acceptance / Requirement Contract / API Contract / Schema /
 │  Business Invariant / Critical Scenario
 │
 │  ◆ 核心需求必须通过验收
 │  ◆ 不允许仅凭 Unit Test 全部通过就判定需求正确
 │  ◆ Agent 自己生成的 expected result 不应作为唯一 Oracle
 └────┬─────┘
      │ Pass
      ▼
 ┌─ Gate 2 ─┐   回归安全 — 此次修改是否破坏已有功能?
 │  Existing Regression Tests / Integration Tests / E2E Tests /
 │  Historical Bug Cases
 │
 │  ◆ 已知历史缺陷必须持续回归
 │  ◆ 发现 Regression 时直接进入返工
 │  ◆ 不通过新增大量 Unit Test 来掩盖 Regression
 └────┬─────┘
      │ Pass
      ▼
 ┌─ Gate 3 ─┐   工程质量 — Agent 是否显著恶化代码质量?
 │  Build / Compile / Type Check / Lint / Static Analysis /
 │  Critical Security / Architecture Violations / Complexity Increase /
 │  Duplication Increase / Abnormal Change Size
 │
 │  ◆ Critical Security Issue = 0
 │  ◆ Build / Type Check 必须通过
 │  ◆ 明显架构违规不得交付
 │  ◆ 异常大的变更进入额外 Review
 │  ◆ Change Size 用于风险识别,不是评分
 └────┬─────┘
      │ Pass
      ▼
 ┌─ Gate 4 ─┐   测试有效性 — 现有测试是否真正具备发现错误的能力?
 │  Mutation Testing / Critical Path Tests / Property / Invariant Tests /
 │  Boundary / Error Cases
 │
 │  ◆ 不为了提高 Coverage 而无限增加测试
 │  ◆ Mutation Testing 优先针对本次修改代码 + 核心模块 + 高风险代码
 │  ◆ 高 Coverage + 低 Mutation Score = 测试有效性不足
 │  ◆ 测试数量增加但错误发现能力未增 = 停止扩张
 └────┬─────┘
      │ Pass
      ▼
  允许交付
       │
       ▼
  持续统计真实缺陷 / First-Pass Acceptance / Rework Rate
```

## KPI 体系(长期)

| 指标 | 含义 | 数据源 | 阈值 |
|---|---|---|---|
| **First-Pass Acceptance Rate** | Agent 首次提交即通过验收的比例 | PR 状态(无需变更即 merge) | 持续提升 |
| **Defect Escape Rate** | 交付后才发现的真实缺陷比例 | `post-release-bug` label + release tag | < 10% |
| **Regression Rate** | Agent 修改导致已有功能损坏的比例 | Gate 2 fail count / total PR | 持续下降 |
| **Rework Rate** | 交付前需要人工返工的比例 | PR review comment 数量 / total PR | 持续下降 |

**这些 KPI 优先级高于** Coverage / Test Case Count / Test LOC / Unit Test 数量。

## 故障注入 — 横跨质量门的验证技术

故障注入验证"系统在故障下是否仍满足需求"。它不是新增的 Gate,而是**验证
既有 Gate 的手段**:Gate 1 用它验证容错需求,Gate 2 用它复现历史故障,
Gate 4 用它暴露测试盲区。

### 故障类型与注入方式

| 故障类型 | 注入方式 | 验证什么 |
|---|---|---|
| 网络失败 | mock timeout / disconnect / drop | 重试/降级路径 |
| 进程失败 | SIGKILL mid-execution / crash 模拟 | worker 重新派发 / 恢复 |
| API 失败 | mock 5xx / malformed / slow | 错误分类 + 兜底 |
| 文件系统失败 | missing file / permission / full | fail-closed 路径 |
| 资源耗尽 | memory limit / CPU cap / fd 限制 | checkpoint + 优雅退出 |
| 工具失败 | subprocess 崩溃 / MCP bridge drop | 降级 + 自恢复 (L1-L3) |

### 故障注入原则

- **每个容错需求至少一条故障注入测试**(Gate 1 的验收方式之一)
- **每个历史故障有一个回归性注入**(Gate 2)
- **注入不通过的路径 → 发现真实缺陷**,不是"测试写得不好"
- 与 Mutation Testing 互补:Mutation 改代码看测试是否敏感;故障注入
  改运行时环境看系统是否健壮

## 错误 vs 正确设计

| 错误:递归测试 | 正确:交付验证 |
|---|---|
| Test | Agent Implementation |
| → Test Quality Test | → Requirement Acceptance |
| → Test Quality Test Test | → Regression |
| → 无限增加测试 | → Engineering Quality |
| | → Test Effectiveness |
| | → Delivery |

## 永远不要犯的判断错误

| 错误判断 | 正确判断 |
|---|---|
| Test Quantity ↑ = Test Quality ↑ | 不一定(看 Mutation Score) |
| Coverage ↑ = Software Quality ↑ | 不一定(看 Acceptance Rate) |
| Test Pass ↑ = Requirement Correctness ↑ | **错!** Unit Test 全过 ≠ 需求正确 |

## 最终判断标准

> Agent 交付的软件是否正确、稳定、可维护,并且能够减少真实缺陷与人工返工?

如果测试数量快速增长,但 First-Pass Acceptance 没有提升、Defect 没有下降、
Regression 没有下降或 Rework 增加 — 当前测试策略正在产生**低价值测试膨胀**,
必须停止并重新评估。

## Quality check 输出顺序(强制)

每次 Agent 代码变更必须按以下顺序输出:

1. **是否通过全部 Quality Gates(GATES 注册表,Pass/Fail + 证据)**
2. **发现的真实风险**(具体 + 可量化)
3. **是否存在测试膨胀**(对照"测试数量 vs KPI"曲线)
4. **是否需要返工**(明确范围)
5. **对最终交付质量的影响**(定性判断 + KPI 走向)

不要把"测试数量更多""Coverage 更高""生成了更多测试"描述成质量提升,
除非有证据证明它们改善了 Requirement Acceptance / Defect / Regression / Rework。
