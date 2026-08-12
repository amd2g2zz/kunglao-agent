# kunglao-agent v2.0 重构计划书(目标驱动)

> **HISTORICAL (2026-08-11)**: 本文档写成时名为 `kong-agent`;技能已更名为 `kunglao-agent`,文中 `kong.py` 为历史名称,当前实现见 `scripts/kunglao*.py`(8 CLI 已按此档案落地)。此档案仅用于追溯设计意图。

> 计划书的第一性: 重构目标是什么(成功画像) + 怎么证明达到了(验收标准)。机制清单只是手段, 不是计划本身。
> 本版重构: 先定义可测量的成功画像, 再从目标反推实施。
> 修订 2026-08-06(实验裁定): 阶段 4 原"资源选择层 + 反馈闭环(kong-select CLI + resource-registry 动态注册 + 多路召回 + 反馈固化)"经真实 worker dispatch 实验**证伪 → CUT**。证据: LLM agent 在 C-401/C-402 dispatch 全程自选/失败自换工具(pefile/xxd/capstone/bcrypt_hook),路由层 ~0 价值;telemetry 见 `runs/gate-telemetry.jsonl` + `progress.txt` [2026-08-06 · GATE-TELEMETRY EXPERIMENT]。阶段 4 收窄为 **priority 比值键 + DAG 拓扑派发**。CLI 清单**保持 8**(不加 kong-select)。下方原"资源选择层/反馈闭环/kong-select/9 CLI"字样为历史设计,已被本裁定 supersede。
> 修订 2026-08-06(价值口径定稿): **打分者 = 机械函数,LLM 永不进分数**。原"价值/成本比"的"价值"由**静态语义标签**(PRIMARY=1.0/competitor=0.6/else=0.2,权重 0.4)构成 —— 它是 LLM 语义判断的冻结快照,full-state 下退化(C-401=C-402=0.696 实测同分)。定稿为 **VoI 代理/成本**: `score = [0.45·L(leverage 拓扑) + 0.30·D(discriminator 结构字段) + 0.25·N(novelty 覆盖熵)] / TIER_COST`(T1:1/T2:3/T3:10)。L/D/N 全从 registry+依赖图读出,打分零 LLM 调用。LLM 仅在 claim-seed(写假设/判别组)与结果(写 fact)两接缝出现。权重为起点值,阶段 7 回放标定。详见 design-spec §3.2。

---

# 第一部分 重构目标(成功画像)

## 1.1 目标陈述

**重构目标**:把 kong-agent 从"补丁堆叠的被动 orchestrator"改造为**"可证明的自主逆向引擎"**——能够无人监督地完成一份 RAT 类样本的完整逆向(到可交付报告),且每一步的可靠性、效率和正确性都是**可测量的**,不是"感觉变好了"。

## 1.2 五个目标维度(每个都可测量)

### G1 自主性:能自己跑完, 不等人
- **现状**:21 ticks 空转、12 次 DISPATCH 却 0 worker、43% 时间 ≤1 槽、92% 空转是会话间隙
- **目标**:冷启动首 tick 自动铺开 T1;完成事件驱动补位;无人监督完成 init→dispatch→verify→converged
- **测量**:启动空转 ticks、DISPATCH-w=0 次数、用户干预次数

### G2 智能性:会选高价值动作, 不乱打
- **现状**:52 个 ORPHAN_CLAIM(claim 与计划 100% 脱节);动作同等对待无优先级
- **目标**:动作按 VoI 代理/成本比排序(机械打分: leverage 拓扑 + discriminator 结构 + novelty 覆盖 / tier 成本), 高价值(C2 配置/命令表)先于低价值被做;每轮证据到达即重排;LLM 永不进分数(见顶部价值口径定稿)【2026-08-06 实验裁定: 原"动作附带资源组合选择(kong-select: 多路召回 → top-k → 依赖序组合)"CUT — LLM agent 自选/自换工具, 路由 ~0 价值, 见顶部裁定】
- **测量**:动作执行顺序对照价值序的符合率;低价值动作占比

### G3 长任务:多天分析不漂移不遗忘
- **现状**:冷启动 76K tokens/轮(progress 158KB 全读);失败记忆靠 LLM 自述(会 confabulate)
- **目标**:digest 2-4KB 机械生成, 冷启动减半;失败记忆结构化常驻(不靠 LLM 记得)
- **测量**:冷启动 tokens、失败复犯率(RRR)、digest 完整性(新增 fact 1 轮内进 digest)

### G4 可靠性:不死等/不漂移/不自满
- **现状**:heartbeat 门被自毁、三源账本漂移、self-promotion 空壳、反思 confabulate
- **目标**:机械监控(heartbeat 二分 + TEMP mtime 权威信号源);验证双层门禁;决策权三分(机械 8/LLM 6/用户 5)
- **测量**:F1-F18 回归全绿;假 PROVEN 被拦率;心跳门判别力(A 触发/B 不触发)

### G5 可证明性:重构有效不是感觉
- **现状**:无评测 harness;业界无先例附可复现评测
- **目标**:三臂评测(A 机制全开/B 全关/C 单 agent)+ 故障注入 + 防污染,证明 A ≥ B 且不劣化
- **测量**:三臂通过标准、过度宣称率 <5%、字节验证通过率

---

# 第二部分 验收标准(怎么证明达到)

## 2.1 验收总纲

**重构完成的定义**:五个目标维度全部达到其验收判据。**任一维度不达标 = 重构未完成**,即使所有机制都实现了。

## 2.2 每个目标的验收判据 + 证据来源

| 目标 | 验收判据(数字) | 证据来源 |
|---|---|---|
| **G1 自主性** | 启动空转 ≤3 ticks(现 21);DISPATCH-w=0 = 0 次(现 12);端到端无人监督 run 收敛 | runs/ledger.jsonl + 端到端验收记录 |
| **G2 智能性** | 动作执行顺序与价值序符合率 ≥70%;ORPHAN_CLAIM 数 ≤10(现 52);低价值动作占比 <30% | 动作执行日志 vs 价值序对照 |
| **G3 长任务** | 冷启动 tokens ≤38K(-50%, 现 76K);RRR(复犯率)≤0.3;digest 完整性 100% | token 计数 + RRR 统计 + 完整性门禁 |
| **G4 可靠性** | F1-F18 回归 29/29 全绿;假 PROVEN 被拦率 100%;心跳门 A 触发/B 不触发 | test 套件 + 故障注入 |
| **G5 可证明性** | 三臂: A ≥ B(收敛轮数/字节通过率)且不劣化;过度宣称率 <5%;评测 harness oracle 自检 10/10 | eval_harness 报告 |

## 2.3 验收的执行方式

**端到端验收**(最终证明):在真实样本上跑一轮完整 /kong-agent,对照 96-tick 历史基线:
- 收敛轮数 ≤ 历史
- 用户干预次数减少
- 冷启动 tokens ≤38K
- 动作选择:高价值动作先于低价值(对照价值序)
- 事实字节验证通过率 100%(无错误结论)

**评测 harness**(持续证明):三臂 A/B/C 预注册,每个重构阶段后跑一轮,证明机制增益持续存在。

**回归套件**(防退化证明):F1-F18 29/29 + 行为快照 10/10 + 24/24 smoke,每次 commit 后全绿。

---

# 第三部分 从目标反推的实施计划

> 每个阶段标注服务哪些目标(G1-G5)。阶段完成的判据 = 该阶段服务的目标的可测量子指标,不是"代码写完了"。

## 阶段 0:基线固化(服务 G5, 1 commit)

**目标**:建立"改之前"的可测量基线,任何重构都有对照。

**步骤**:
1. F1-F18 回归 29/29 落盘为 golden master fixture(命令 + 输入 + 基线输出字节)
2. 记录 ≥3 轮冷启动 token 方差(现 76K)
3. 状态文件 git tag + 快照

**完成判据**:fixture 全绿可重放 + token 基线记录完成。
**回滚**:无代码, 不适用。

## 阶段 1:状态统一(服务 G4/G3, 已完成 Phase 2)

**目标**:单一状态源,消除账本漂移;heartbeat 语义二分。

**已完成**:loop_state.py(TEMP mtime 权威信号源)/ heartbeat 二分(tick_ts/activity_ts)/ lib_kong 单例。
**已验收**:E2.1-E2.4 实验过(对账 0.119s / 信号源 598/598 / A 触发 B 不触发 / 等价)。

## 阶段 2:循环模块化(服务 G4/G1, 已完成 Phase 3)

**目标**:31 CLI → 独立 CLI 组(非子命令),机械等价。

**已完成**:kong.py decide/tick(独立入口雏形), F1-F18 补 5 行到 29/29, subagent 契约兼容。
**已验收**:E3.1-E3.4 实验过(逐字节 diff 空 / 同源契约 / 29/29 / 读不写回)。
**修订**: 目标从"kong.py 单入口子命令"改为"8 个独立 CLI"(kong.py 编排入口 + kong-decide/verify/record/monitor/digest/init/eval), 每个单一职责, 不共享 argparse。内部仍按 M0-M5 模块化。【2026-08-06 追加: 阶段 8 曾扩为 9 CLI 加 kong-select——已被实验裁定 CUT(见顶部), 最终保持 8】

## 阶段 3:契约重写(服务 G2/G4, 2 commits)

**目标**:SKILL.md 43KB→<500 行, 文档职责三分;决策权表落盘。

**步骤**:Pass 1 纯结构拆 references;Pass 2 语义(职责三分 + 授权矩阵)。
**完成判据**:SKILL ≤500 行 + 一层深检查 + 决策权表落盘。
**回滚**:git revert 对应 pass。

## 阶段 3.5:kong-init 初始化(服务 G1/G4, 1 commit)【新增】

**目标**:冷启动一次性初始化, 防二次初始化事故(覆盖分析/重复 hook/重复 seed)。

**步骤**(三阶段防重, 详见设计规格 §6.7):
1. 存在性检查([initialized] 标记) → 已初始化则续接模式
2. 全新初始化: scaffold + sample mount + task_spec intake + seed claims + hooks 幂等部署
3. 幂等校验: 重跑 → 续接; --force 才重建(先备份)

**完成判据**:E-init.1 防重(连续 2 次第 2 次续接)+ E-init.2 幂等(hooks 不重复)+ E-init.3 漂移检测 + E-init.4 恢复。
**回滚**:revert commit; [initialized] 标记可删以强制重建。

## 阶段 4:动作选择改造 = 资源选择层 + 反馈闭环(服务 G2, 1-2 commits)【修订 2026-08-06】

**目标**:priority.py 改比值键(score = value/cost)+ 每轮重排 + 探索阶段 + **资源选择层与反馈闭环**(原"方法路由"方向整体替换)。

**步骤**:
1. 按 VoI 代理/成本比排序(`score = [0.45·L + 0.30·D + 0.25·N] / TIER_COST`, 纯机械零 LLM);证据到达重算;早期 cheap+coverage 铺开;低价值不删只降序;同分取 cost 小者。
2. **资源选择层(kong-select CLI)**: 多路召回(嵌入 bge-m3 本地 ollama + 关键词 + description 融合)→ top-k 排序 → 组合选择(依赖序, 如 C2 提取 = ghidra → frida → floss)→ 派发。机械选择器, 不写 rulebase; **LLM 推荐路**: 机械路低置信/模糊/组合需求时 LLM 推荐(推荐本地没有的资源 → gap → 固化)。【修订 2026-08-06: 加 LLM 路】
3. **resource-registry.yaml 动态注册**: kong-init 阶段注册器扫描 skills/ + mcpServers + scripts/ 生成(不写死), 支持增量添加。
4. **反馈闭环**: 消费 fact/verify/ledger 结果(读盘, 不拦截)——失败 → 资源降权 + 换 top-2(熔断); 成功 + 研究兜底发现新资源 → 增量注册固化(下次可选)。
5. claim_deps.yaml 补拓扑派发 + 关键路径优先(实验 E-DAG-1 已过: 生产数据拓扑 OK)。
6. Nginx 式代理取舍: 不引入代理拦截层(RE 工具为长驻进程非 HTTP 后端, 架构错配); 吸收"代理统计成败"思想 → 选择层读盘观察执行结果。

**完成判据**:
- 动作执行顺序与价值序符合率 ≥70%(对 3-5 个历史样本回放测量, 价值序 = VoI 代理/成本序)【修订 2026-08-06】
- **LLM 永不进分数**: 分数仅由 L/D/N/cost 四项机械计算(代码级断言, 打分路径零 LLM 调用)【修订 2026-08-06】
- E-SEM-1 关键词匹配区分 / E-DAG-1 拓扑派发回放绿

**回滚**:revert 单文件/单 commit。

## 阶段 5:M3 VERIFY / M4 RECORD 与状态迁移(服务 G4/G5, 3 commits)

**目标**:验证双层门禁;记录账本化;状态收敛。

**步骤**:Expand(verify 子命令 + ledger 旁路)→ Migrate(回放旧通道, N=3 轮零漂移)→ Contract(旧通道只读)。
**完成判据**:已知 fact 全 PASS / 假 fact 全 FAIL(判别力)+ checksum 零漂移。
**回滚**:停在当前阶段即安全。

## 阶段 6:digest + failure-registry(服务 G3, 2 commits)

**目标**:冷启动减半;失败记忆结构化。

**步骤**:digest_build.py 机械生成 2-4KB;failure-registry.yaml 结构化规则;注入顺序新条目在前。
**完成判据**:冷启动 ≤38K(-50%)+ digest 数字保真过 handoff-check + 完整性 100%。
**回滚**:关闭 digest 注入, 回退全量读。

## 阶段 7:评测 harness(服务 G5, 独立轨可并行, 2 commits)

**目标**:可证明重构有效。

**步骤**:三臂 A/B/C + 故障注入(限流/隐式/显式/impossible/adversarial)+ 防污染三道探针。
**完成判据**:oracle 自检 10/10 + golden master 重放绿 + 三臂 A ≥ B 且不劣化 + 过度宣称率 <5%。
**回滚**:harness 附加轨, revert 无副作用。

## 阶段 8:模块收敛迁移收尾(服务 G1, 每模块 1 commit)【修订 2026-08-06】

**目标**:31 CLI → 8 个独立 CLI(kong.py 编排入口 + kong-decide/verify/record/monitor/digest/init/eval, 不加 kong-select — 见顶部裁定)。

**步骤**:剩余 26 CLI 逐模块收敛 + 字节 diff + 影子验证;全部迁移后旧 CLI 降级只读再删。
**完成判据**:每模块 F1-F18 29/29 + 字节 diff 零非预期 + token 不反弹 + 8 CLI 清单(kong.py / decide / verify / record / monitor / digest / init / eval)全部落地(不加 kong-select — 见顶部裁定)。
**回滚**:revert 模块 commit; 旧 CLI 保留到全部验证完成。

## 阶段 9:端到端验收(服务全部 G1-G5, 最终)

**目标**:证明重构达成全部目标。

**步骤**:真实样本跑完整 /kong-agent, 对照历史基线。
**完成判据**(§2.3 端到端验收清单):收敛不劣化 + 干预减少 + 冷启动 ≤38K + 动作选择符合价值序 + 事实验证 100%。

---

# 第四部分 依赖与里程碑

## 阶段依赖图

```
阶段0(基线) → 阶段3(契约) → 阶段4(动作) → 阶段5(状态) → 阶段6(digest) → 阶段8(收尾) → 阶段9(验收)
     └─────── 阶段1✅ 阶段2✅(已完成)     └──── 阶段7(评测, 可并行)
```

## 里程碑验收表

| 里程碑 | 服务目标 | 完成判据 | 当前状态 |
|---|---|---|---|
| 阶段 0 基线 | G5 | fixture 全绿 + token 基线 | ⏳ |
| 阶段 1 状态统一 | G4/G3 | E2.1-E2.4 过 | ✅ |
| 阶段 2 循环模块化 | G4/G1 | E3.1-E3.4 过 | ✅ |
| 阶段 3 契约重写 | G2/G4 | SKILL ≤500 + 授权矩阵 | ⏳ |
| 阶段 4 动作选择 | G2 | 价值序符合率 ≥70% + LLM 永不进分数(代码级断言)【修订 2026-08-06】 | ⏳ |
| 阶段 5 状态迁移 | G4/G5 | 假 fact 全 FAIL + 零漂移 | ⏳ |
| 阶段 6 digest | G3 | 冷启动 ≤38K + RRR ≤0.3 | ⏳ |
| 阶段 7 评测 | G5 | 三臂 A≥B + oracle 10/10 | ⏳ |
| 阶段 8 收尾 | G1 | 31→8 独立 CLI(不加 kong-select, 见顶部裁定) | ⏳ |
| 阶段 9 端到端 | 全部 | §2.3 清单全过 | ⏳ |

**重构完成定义**:阶段 9 通过 = 五个目标(G1-G5)全部验收判据达成。**在此之前, 任何"机制实现了"都不等于"重构完成了"。**

---

# 附录:证据锚

- 现状数字(21 ticks/52 orphan/76K/43%)来自 12 个真实实验(命令在 refactor-experiments.md 可复现)
- 目标数字(-50% tokens/价值序/RRR ≤0.3)来自调研实证(Wave 1-8 + deep-research): Anthropic 冷启动 96.3% file-read / Rothermel 排序 / GK 子模 / Honest Lying confabulate / 三臂消融方法论
- 已剔除(REFUTED/UNVERIFIED): Gauntlet canary oracle / 85.36% 复犯率 / 诊断式"唯一 30 年理论" 等
