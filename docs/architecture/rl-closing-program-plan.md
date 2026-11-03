# RL 收官实施计划（closing program plan v1）

- 日期：2026-10-19。批准：owner（"ok听你的。你写个计划, 计划要写清楚要运行subagent并行（最大3），并且按照devkit工具和标准来施工"）。
- 上游：`rl-value-experiment-plan.md`（四门实验）、`kunglao-technical-doc.md`（as-built + 偏离分析）、#779（三面根因卡 + 统一方案）。
- 终局判据（不可协商）：四臂对照（H0/H-notes/H1/H2）按预注册规则裁决 RL 层留或砍；负结果同样交付价值。

---

## 0. 并行与施工纪律（对所有 subagent 生效）

**Subagent 编制**：最大并行 **3**（并发≤3 且 ≤200k tokens/min）；每个 subagent 绑定一个 issue 分支 + 独立 worktree（`.worktrees/<branch>`）；产出必须落文件再汇报（≤15 行摘要回传）。

**devkit 施工标准**（每个 PR 的硬门槛，缺一不合）：

1. TDD：先钉测试后实现；`uv run pytest <受影响套件> -q` 绿。
2. 十门：`uv run python devkit/quality_gates.py --quick` 过；`lint-hygiene`（含 comment-hygiene/formal-code/silent-except 基线——**新增注释/标记必须同 PR emit 基线**）。
3. 新脚本三登记：README 目录 / ext-scan / `deploy_manifest.py --write`（**必须最后一步**）。
4. PR body 必带 `## Verification` 块（命令+真实输出）——`verification_gate` 会拦。
5. 延期必须开阻塞 issue——`deferral_guard` 会拦。
6. 变更 spec 必须引用不变量 id + 集成契约节——`spec_coverage` 会拦。
7. review-gate：stage → sha → evidence → mint → commit（两 shell；stale 即重 mint）。
8. uv-only；咽喉点纪律（#432）；EMIT 词表 sorted+unique；`method_family` 字面量不进 dispatch_gate。
9. 活体指纹：触碰 rlvr/hooks 的 PR 必须声明影响哪些指纹；`liveness_gate --ledger` 不降级。

**Subagent 通用 brief 模板**：工作树绝对路径 / issue 号 / 验收引用本计划条目 / 产出文件 / 禁改清单（其他 worktree、dev 分支）。

---

## Phase 1 — 观测与桥（并行 3）

### T1 【subagent A：观测工程师】WS-1 观测统一面（#779 面一 + #769）

- 分支 `feat/779-observation`（off dev）。
- **1a 子代理 hook 语义探针**（先验证再修）：最小实验判定 Task 子代理会话是否触发工作区 PreToolUse/PostToolUse hooks（合成 ws + 探针 hook 记录事件）。两个结论两条路：(a) 触发但不完整 → 修继承缺口；(b) 根本不触发 → 编排侧代偿：Task 完成面从 worker 转录提取步记录（settle 面已会解析 worker_status——复用）。
- **1b policy-state 投影**：轮闭合写 `runs/policy-state.json`（schema policy-state/1：round/candidates/admitted/chosen/posterior 摘要/ts）；`statusline_snapshot` 增消费；TUI 指引更新。
- **1c 指纹扩展**：新增 `policy-state-fresh` 指纹（liveness_fingerprints.json）。
- 验收：1a 探针报告（结论+证据）；投影三方消费钉；#769 关闭条件达成。
- 涉及指纹：rl-admission-consumed（读模型面）。

### T2 【subagent B：学习桥工程师】WS-2 学习-决策桥（#779 面二+三）

- 分支 `feat/779-bridge`（off dev）。
- **2a 信用入池桥**：settle 面解析 dispatch 的 method_family（method-family-log usage 行 by cid）→ 无步记录时 claim 级 `observe_step_credit` 兜底入池（credit=claim 终态信用）。
- **2b 案例后验第四源**：`method_sample` 先验链 `proposal_prior_labeled()` 增 case 源——读 `runs/posteriors.yaml` 案例 Beta 按 update_map 关联家族折权重（label `prior_source: "case"`，SHRINK cap 同法）。
- **2c 熔断接线复验**：#778 的 breaker 在桥上继续生效（桥产观察也计入退化序列）。
- 验收：合成战役回放（win-kdf 三单位账本）四指标复测——后验位移>0、usage 行 sampled_family 非空、指纹 rl-posterior-moved/rl-sampler-exit 翻绿。
- 涉及指纹：全部 rl-*。

### T3 【subagent C：spec 书记】六处 MISMATCH 的 spec 增补（§8.2 全表）

- 分支 `docs/spec-amendments`（off dev，纯文档）。
- 六个 openspec 变更目录增补修正案（496/691/753×2/loop-engineering/#764）：每处 = 日期 + owner 裁决引文 + 新语义原文 + 指向实现 file:line。
- 同步：`liveness_fingerprints.md`/`rl-signal-contract.md` 若有措辞滞后一并修。
- 验收：`spec_coverage` 对六个变更目录的违规清零；文档测试绿。

**Phase 1 出口**：三 PR 绿并；W4 冒烟（$15，owner 已批预算）——五指纹在真战役翻绿 = **回路活体证明成立**。

## Phase 2 — 准入与账本驱动（并行 ≤3，按 Phase 1 出口启动）

### T4 【subagent A'】WS-4 注入准入（#771 余项）

- 分支 `feat/771-need-driven`。需求驱动查询（claim 问题关键词，删 WEB_QUERIES/GO_SIGNALS 类别默认扩展）；段落级定位（`path:L120~L180`，查询时锚定标题新鲜计算）；注入预算 ≤3 文件 ≤1200 字符；25 个旧默认钉迁移（opt-in 夹具）。
- 验收：注入 ≤5 条带行号、默认关、需求门钉；`test_recall_default_771` 绿。

### T5 【subagent B'】#770 watchdog 账本驱动终止

- 分支 `feat/770-ledger-watchdog`。基线周期 25min（常量降为冷启动兜底）；条件收紧 = 进度账本静默（观测间隔 N 倍无新行）或轮次失败信号；双向钉（活跃 worker 永不被收、静默 worker 早于旧窗口被收）。
- 验收：双向钉 + 基线 25min 常量替换的迁移钉。

### T6 【subagent C'】#767 供应链门 + camoufox 裁决执行

- 分支 `feat/767-supply-gate`。CI 门：每个声明面（mcpServers/agents/env 表行）必须 resolve 到 in-tree 工件或 pinned 可安装源，否则 build 红（camoufox 蒸发表编译期死，附 owner 裁决引文位）。蒸发表三选一执行（owner 预裁决授权：vendor / re-point / cut——按源码搜寻结果）。
- 验收：供应链门红于蒸发表（演示钉）+ 裁决后绿。

## Phase 3 — 事务原语（T7，单 subagent 串行大件）

### T7 【subagent D：事务工程师】#774 升级七步事务

- 分支 `feat/774-transaction`。七步一次实现（快照→删老→铺新→配置→selfcheck→reload 提示/回滚），init/upgrade/deploy 共享原语；selfcheck 进 upgrade 路径（hook_activation:597 复用）；注入失败回滚钉。
- 验收：七步全通 + 注入失败回滚钉 + as-built vs 合同对账图全绿（§11 Mermaid 复测）。

## Phase 4 — 终局四臂对照（owner 预算批准后）

四臂 H0/H-notes/H1/H2 × 六单位家族簇 × per-arm 累积；预注册判据不变（H2>H-notes>H0 才算 RL 机制挣得存在；H2≈H-notes → 砍机器留笔记）。产出终审报告 → owner 裁决保留/退役。

## 里程碑与预算

| 阶段 | 内容 | 预算 | 里程碑 |
|---|---|---|---|
| Phase 1 | T1+T2+T3 并行 | ~$20（W4 冒烟） | 回路活体证明 |
| Phase 2 | T4+T5+T6 并行 | ~$10（回归冒烟） | 注入/终止/供应链闭环 |
| Phase 3 | T7 | — | 事务闭环 |
| Phase 4 | 四臂终局 | $150-240 | RL 留砍终审 |
| 收尾 | v0.1.6 收口 + rc2 重发 | — | 发版 |

## 治理

- 每 PR：十门 + verification block + review-gate mint + 指纹不降级声明。
- 每阶段出口：liveness_gate --ledger 复测 + 逃逸率行追加。
- spec_coverage：新变更必须引不变量（INV-001..008）+ 集成契约节。
- 负结果即结果：任何门失败按判据处置，不解释性保留。
