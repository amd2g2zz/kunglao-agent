# Kunglao RLVR 收官计划（本版本）：从经验路由器到可学习的策略控制器

状态：owner 裁定 2026-10-07——WS1-WS5 全部是本版本范围（无 v0.1.7/v0.2 顺延；发版三件套在 WS5 证据之后）；取代 external-smdp-phase-b.md 作为总纲
前置裁决（全部已锁定）：
- 基础模型**永远冻结**——外部 RL/记忆/搜索/验证/调度是超越 model+CC 的唯一来源
- **critic 出局**（不具备条件；bandit 级方法覆盖信用分配，数据证明不够再议）
- **RAG 是地板不是产品**：卡壳/冷启动召回有用（防反复无效探索），但全是 RAG = reverse-skill 实测零提升
- ε-greedy 是**对照组**，不是产品功能；离线先行（SNIPS），在线 A/B 仅当离线结果值得
- 蒸馏（在线/混合）和召回都是**动作**——策略决定何时用，不是背景事件

## 0. 目标与验收（不变）

赢 = 同模型、同工具、同 token/墙钟/并发、无泄漏上下文下：
**K-warm > CC+warm-context**（不是只赢裸 CC），且 held-out + extrapolation 集上
success / time-to-correct / token 效率 / false-proven 同时改善，且三层消融各有预测：
- 去 L1（检索）→ 冷启动变慢但不死
- 去 L2（posterior store）→ 新任务退化到均匀
- 去 L3（扩展算子）→ 历史外障碍卡死

## 1. 三层能力架构（本次讨论的核心校准）

```
L1 检索层（地板）   卡壳/冷启动召回历史经验。reverse-skill 已做到，价值=0（实测）。
                   形态：recall-history 作为动作，策略调度
L2 学习层          跨任务持久 posterior store：检索的是"什么方法在什么状态有效"
                   的分布，不是文本。uniform 消融可证。
L3 发现层          障碍→生成历史里没有的新臂（expansion move）+ 主动蒸馏固化。
                   唯一能超越历史经验的来源。
```

执行原则：**RAG 从管道降级为策略调度的工具**。策略为「探索新方法 vs 复用历史」
付真实机会成本（预算+奖励归因），学出来的才是调度策略。

## 2. 现状基线（截至 2026-10-07）

已落地（dev）：
- kernel dispatcher（#528）、supply OR（#535）、completion contract（#536）
- transition 记录 + 增量奖励（#540）：runs/transitions.jsonl，每 act 一行 (s,a,o,s',r)
- propensity 落盘修正 + SNIPS 策略对照（fix/act-budget 分支，PR #543）
- ACT BUDGET 注入（#543）：G3 矩阵第一轮 6/6 BLOCKED 的根因——worker 不知道墙在哪

已测：
- G1: ICC 0.478 GO（奖励可靠）；Phase B 诚实零（当前难度层臂可互换）
- smoke pilot: CC 3/3 checker PASS vs K-cold 3/3 PASS 但 0/3 session 完成（harness 缺陷已修）
- H2H: reverse-skill = 零提升 + 46% 成本（L1-only 路线的实测死刑）
- G3 round-1: 6/6 BLOCKED（worker 不终止）；round-2 跑动中（ACT BUDGET 生效待验证）

文献对齐（2026-10 检索）：
- Agentic RL 综述（arXiv:2509.02547）：POMDP 框架与我们外部 SMDP 同构
- context-optimization-rl（arXiv:2607.25415）：冻结模型+harness 策略 lane 已验证，
  评测方法论与我们逐项对应
- EnIGMA（ICML 2025）：动作界面质量≈策略质量 → 七元组投资有据
- LLM-generated bandit priors：冷启动先验可由模型生成 → 修 compose 静默
- 记忆=攻击面（后门>90%）：holdout/red-team 防火墙是安全边界不只是实验卫生

## 3. 工作流（优先级序）

### WS0 交付线（进行中，不改算法）
- G3 round-2 终局 + 80/20 初测（regret-weighted decision points，诚实报数）
- 发版三件套移至 WS5 证据之后（owner 2026-10-07：这个版本就要解决）
- CI 管道病（#538）：checkout TLS 波次 + pull_request 事件丢失，观察项不阻塞

### WS1 动作空间升级（PR-3a，schema 层）
envelope v2 七元组：`(action_type, method_family, context_recipe,
tool_sequence, target_claim, verification_mode, branch_budget)`
- action_type ∈ {dispatch, verify, recall-history, distill-online,
  distill-hybrid, replan, rollback, stop}——蒸馏/召回入动作面
- 臂键 4 维（method_family, context_recipe, verification_mode, tier bucket），
  其余为特征列——防冷启动臂爆炸
- v1 信封兼容（旧字段反填）
- q-cell 键升级带双写期

### WS2 跨任务持久 store（PR-3b，L2 的载体）
- posterior store 脱离 per-workspace：按 (family, feature-key, fingerprint) 持久化
- 特征键控（非身份键控）+ eval/v1/split.yaml holdout 防火墙（已有，#518）
- 指纹回火 λ=0.25 已在 meta_arms（接线即用）

### WS3 冷启动 LLM 先验（修 compose 静默，文献直移植）
- intake 时让冻结模型自评 method family 先验（弱 Beta 播撒 + 校准）
- evidence_count < n_min 不再静默：模型先验代替 Beta(1,1) 平面
- 这是「找不到资料」时策略层仍非均匀的最小实现

### WS4 扩展算子 + blocked-path 实验单元（L3 的载体与度量）
- expansion move：obstacles 达 K 次 + 已试臂 posterior 全塌缩 → 触发一次
  "生成 N 个不在已失败集合内的新攻击假设" 的 dispatch
- 准入：score = log P_LLM + λ·policy + novelty bonus（新臂冷启动 = 模型自评先验）
- blocked-path 单元（toolflex #356 基因）：构造所有已知 family 必死的任务，
  裸 CC 为基线——「能否自我探索」的数字答案
- 验收：扩展算子前/后各跑一轮 blocked-path，差值即 L3 的贡献

### WS5 对照实验矩阵（终局审判）
五臂：CC / CC+warm-context / K-cold / K-warm / K-warm-no-L1（去检索消融）
- 先离线（SNIPS over transitions，underpowered 门槛 40 决策）再在线
- 统计口径：bootstrap CI，四指标同向才计胜

## 4. 明确不做（钉死，防机制堆砌）

- 不训 critic / value estimator / actor（数据量百级，跳级必翻车）
- 不微调模型、不做 LoRA（无权重访问，Layer-3 出局）
- 不加生产采样开关（ε-greedy 只活在实验面）
- 超参纪律：每阶段新增 ≤3 个，全部策略常数
- 蒸馏频率不增（克制裁定）：distill 入动作面后由预算约束，不新增后台节奏

## 5. 风险

| 风险 | 缓解 |
|---|---|
| G3 round-2 仍 BLOCKED（ACT BUDGET 无效） | 墙钟提额或 act 粒度细化（claim 拆小），逐级 |
| 扩展算子 novelty-hacking（发明"新方法名"刷探索分） | 特征键控计数 + 验证器裁决准入 |
| 跨任务 store 污染（坏经验固化） | 蒸馏质量公理不变（泛化+自启才固化）+ holdout 防火墙 |
| 小样本误读（ε-greedy 假赢） | underpowered 门槛 + CI 重叠不判胜 |
| 记忆面后门 | red-team 门 + provenance DAG 不变 |

## 6. 排序逻辑

度量先行：每个 WS 落地前先有它的测量面（blocked-path 单元先于扩展算子合入、
消融臂先于 store 声称生效）。代码顺序 = WS0 → WS1 → WS3（小，先行）→ WS2 →
WS4 → WS5；实验顺序与代码解耦，数据够了就跑。
