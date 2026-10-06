# Phase B 设计：外部 SMDP 的动作/奖励 schema + ε-greedy 对照 + transition 记录

状态：设计稿，待 owner 审后实施
Issue: #539
前置裁决：冻结模型（永不微调）；critic 出局（不具备条件）；本阶段纯编排层，零新模型调用
日期：2026-10-06

## 0. 范围与不变量

- 只动编排层：dispatch 契约、采样面、记录面。worker 内部、verifier 路径、模型调用全部不动。
- 学习面无新机制：不加 critic、不加 value estimator、不加搜索。本阶段交付的是** schema 与记录**，学习增益由现有 bandit + ε-greedy 对照来度量。
- 超参纪律：全阶段新增超参 ≤3 个，全部声明为策略常数（state.py 先例："documented policy constants, not fitted parameters"）。

## 1. 七元组动作 schema

### 1.1 字段定义

```yaml
# dispatch envelope 扩展（hooks/lib_kunglao.py parse_dispatch 消费）
kunglao_dispatch:
  version: 2          # v1 信封不变，v2 增字段向后兼容
  claim: C-007        # → target_claim
  tier: 1
  method_family: <enum 现值>          # 不变
  context_recipe: minimal | facts_snapshot | facts_anti_hints | full_recall
  tool_sequence: [grep, xxd]          # 现有 tools 字段升格为有序
  verification_mode: none | replay_probe | oracle_case | red_team
  branch_budget: {wall_s: 600, retries: 1}
  control: continue | stop | replan | rollback
```

- `context_recipe` 枚举直接映射**现有** dispatch_context.py 的组装面，不是新发明。
- `verification_mode` 映射现有 verifier 面（oracle_runner / red-team gate），调度层只是把它变成可选项。
- `control` 是编排器记录的决策位，worker 不可见（它不是给模型的指令，是策略的输出记录）。

### 1.2 落点

| 文件 | 改动 |
|---|---|
| hooks/lib_kunglao.py | parse_dispatch 接受 v2（v1 反填默认值，旧会话不破） |
| scripts/checkpoints.py | 派遣时写入 action_key = 7 元组编码进 receipt |
| scripts/rlvr/q_cells.py | append_observation 的 arm 键从 method_family 升为 action_key |

### 1.3 冷启动臂爆炸的防护

7 元组全积的组合数爆炸，q-cell 若按 identity key 存会每个动作都是新臂。防护：**特征键控**（与 eval-split 防过拟合同一原则）——arm 键 = (method_family, context_recipe, verification_mode, tier(bucket)) 四维；tool_sequence/budget/control 作为特征列记录不参与键。三步走：先按 4 维键落 schema，数据起来后再评估是否升维。

## 2. 增量奖励面（potential-based）

### 2.1 形式

```
r_t = α · [Φ(s_{t+1}) − Φ(s_t)] − λ · cost_t + bonus_settle(t)（终态时）
Φ(s) = w_f · verified_facts_frac + w_o · oracle_green_rate
cost_t = tokens_t / 10_000 + tool_seconds_t / 3_600
```

- Φ 是状态势函数——**potential-based shaping**（Ng et al. 1999：势差奖励不改变最优策略序），所以叠加在终态 settlement 上不扭曲任务目标。
- `bonus_settle` = 现有 round credit，原样保留为终态信号，不删不改。
- 新超参仅 3 个：α、λ、（w_f/w_o 沿用 state.py 的 0.3/0.5 现值，不新增）。

### 2.2 落点

新文件 `scripts/rlvr/incremental_reward.py`：纯函数，输入两次连续 situation snapshot + cost_events 增量，输出 r_t。调用点：checkpoints.py 的 settle face（worker 返回时已有 s/s′ 两侧快照）。**不在 dispatch 热路径上**——纯事后计算。

### 2.3 "普通工具成功给零分"问题的解法

现状 round credit 只在 settlement 有值。增量面在每次 worker-return 都产生 r_t（Φ 差可能为 0，但 cost_t 一定记账）——负成本项让"无效动作"至少被记为负收益，正是 owner 指出的归因缺口。

## 3. ε-greedy 对照组（实验面，不是产品面）

**定位修正（owner 2026-10-06）：ε-greedy 是对照组，不是交付功能。** 它不进生产采样路径、不开运行时开关；它属于策略对照实验，与 uniform、DTS 同台，回答同一个问题：学习出的 posterior 相对平凡基线的增益是多少。

### 3.1 对照的运行方式（两级，先离线后在线）

1. **离线先行（首选）**：dispatch 时已记录 propensity（#523 线的 mc_propensity 进 receipt），transition 记录（§4）落地后，离线策略评估（IPS/DR）直接在日志轨迹上比较 DTS / ε-greedy / uniform 的价值估计——零真实任务开销，符合「先离线 replay，再昂贵 E2E」的裁决顺序。
2. **在线 A/B（仅当离线结果值得验证时）**：eval harness 的对照臂——实验 runner 通过测试 seam 注入对照策略选择，生产 orchestrator 代码路径不变。

### 3.2 落点

- 离线对照：`scripts/rlvr/policy_compare.py`（评估器，读 transitions.jsonl + propensity 列，输出三策略价值估计与置信区间）。
- 在线对照臂（需要时）：eval harness 侧的 seam，不在 posteriors.py/checkpoints.py 的生产调用点加开关。
- ε=0.1 是对照组参数，不是系统超参。

## 4. Transition 记录

### 4.1 格式

`runs/transitions.jsonl`（append-only）：

```json
{"ts": "...", "dispatch_id": "...", "s": "<sig_hash>", "a": "<action_key>",
 "o": {"status": "green|red|timeout|refused", "facts": 2},
 "s_prime": "<sig_hash>", "r_incr": 0.42, "r_settle": null, "done": false}
```

settlement 到达时补写该 dispatch 的 `r_settle` 与 `done`（append-only 第二条，不回写）。

### 4.2 Pin 反转引用

triples.py 的 quadruple 拒绝是 2026-09-27 owner pin；2026-10-06 owner 裁决（外部 SMDP、记录 s′）推翻该 pin。实施 PR 的 commit message 与 triples.py docstring 都引用此裁决，pin 注释改写而非删除。

## 5. 交付切分（每片一个 PR，TDD）

1. **PR-1 transition 记录 + 增量奖励**（纯 additive，零行为变化）——最安全先行。
2. **PR-2 离线策略对照**（policy_compare 评估器：DTS vs ε-greedy vs uniform，IPS/DR over 日志轨迹；对照组，不是产品开关）。
3. **PR-3 七元组 schema**（envelope v2 + q-cell 键升级 + 特征键控防护）。
4. 之后视离线结果决定是否花钱跑在线对照（eval harness 对照臂）。

顺序理由：对照实验依赖 PR-1 的 transition 数据做底座；schema 键变更影响面最大放最后；离线对照零真实任务成本，先出数字。

## 6. 风险

| 风险 | 缓解 |
|---|---|
| q-cell 键升级破坏现有 store | 双写期（新旧键并行 N 个 run），读旧写新，向后只读 |
| Φ 差被无关动作污染（别的 worker 并行推进 facts） | transition 记 dispatch_id，分析面按 worker 归因；记录面不试图解决并发归因（那是 credit assignment 问题，本阶段不碰） |
| ε-greedy 在小样本下赢 Thompson 造成"学习无用"误读 | 对照结论只在 n≥阈值后出；协议里写明最小样本量 |
