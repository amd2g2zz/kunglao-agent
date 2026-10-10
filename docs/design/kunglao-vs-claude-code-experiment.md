# Kunglao RL 与 Claude Code 基线对照实验

状态：预注册实验协议，尚未产生能力结论  
版本：`exp-cc-rl-v1`  
日期：2026-10-06

本文回答一个具体问题：在相同基础模型、工具供应、时间和 token 预算下，Kunglao 的验证闭环与 RL 策略层是否比普通 Claude Code 带来可重复的净收益。

## 1. 先固定比较对象

“超过”必须拆成两个问题：

1. **解题能力**：能否在未知任务上得到更多正确、可复核的答案。
2. **运行价值**：在相同正确率下，能否减少错误证明、提前收敛、时间、token、dispatch 和重复失败。

这不是比较两个不同模型。所有臂使用同一个 Claude Code 版本、同一个模型别名、同一套任务提示、同一工具供应和同一预算。基础模型仍然负责新方法的推理；Kunglao 只额外提供证据验证、状态记忆、claim 排序、method-family 采样和失败路径记忆。

## 2. 待证伪假设

主假设 `H1`：在 held-out 任务上，warm Kunglao 的证据支持解题率不低于 `CC+guard`，同时 false-proven、premature-closure 或单位成本至少有一项达到预注册的优势门槛，且没有另一项出现不可接受退化。

零假设 `H0`：加入 Kunglao 的验证和学习层不会改善净运行价值；观察到的差异来自模型随机性、任务顺序、工具可用性或预算不平等。

探索性假设：

- `K-cold` 在单个全新任务上的优势小于 `K-warm`。
- 如果 `K-warm` 只是把历史知识注入 prompt，那么它不会稳定超过 `CC+warm-context`。
- RL 只在同一机制族反复出现后改善 method-family 选择，不能显著改善 extrapolation 任务的首轮解题率。
- `CC+guard` 与 `K-cold` 的差异主要来自调度和证据闭环，`K-warm` 相对 `CC+warm-context` 的差异才是可归因于 RL 策略的部分。

## 3. 五个主实验臂

每个臂使用独立工作区、独立 transcript、独立 ledger 和独立 posterior。任何臂都不能读到另一个臂的运行产物。

| 臂 | 配置 | 用途 |
|---|---|---|
| `CC` | 原生 Claude Code，关闭 Kunglao 插件和策略注入；保留同一工具集 | 通用基线 |
| `CC+guard` | Claude Code 加任务 checker、证据归档和最终机械复核；method 选择固定为 uniform，不读 posterior | 测量验证器和证据协议收益 |
| `K-cold` | 完整 Kunglao runtime，但 `runs/` 中没有历史 posterior、pattern 或 strategy card | 测量冷启动开销和固定编排收益 |
| `K-warm` | 完整 Kunglao runtime；只用 train split 形成的 posterior，held-out 阶段禁止继续污染先验 | 测量 RL、记忆和失败复用收益 |
| `CC+warm-context` | 原生 Claude Code 或 `CC+guard`，接收与 `K-warm` 完全相同的 train-derived cards、失败路径摘要和冻结 prior 的纯文本渲染；不启用 Kunglao 策略、hooks 或 posterior 采样 | 分离“历史知识/上下文收益”和“RL 策略收益” |

额外负控制不计入主胜负：

- `K-shuffle`：保留完整流程，但将 settlement credit 在同一 train stream 内打乱；如果它仍然优于 `K-warm`，说明指标或泄漏有问题。
- `K-uniform`：完整验证器和 ledger，但关闭 method-family 学习；用于定位收益是否确实来自 Q-cell。

`CC+warm-context` 是主比较臂，不是可选消融；没有它，`K-warm` 的优势无法归因于 RL，因为 pattern card、失败路径和 prior 本身可能已经把答案策略传给了模型。

## 4. 数据集和拆分

只使用可重放、可机械评分的构造任务，不在宿主机执行恶意样本。需要真实样本时，动态执行必须走现有 VM 通道，宿主机只处理静态 fixture 和评分结果。

### 任务组成

至少覆盖四类：

- smoke：分钟级、低成本，验证 harness 和协议；
- release：静态、native、web、APK 等不同工具链；
- misdirection：诱导错误归因、decoy、环境误判和错误 marker；
- toolflex：同一目标需要多个工具或多步证据链，防止单工具捷径。

每个机制族生成参数不同但语义等价的实例。实例 seed、目标构造配置、checker 版本和 ground truth hash 必须进入 manifest。

### 推荐规模

正式实验使用 8 个已知机制族，每族 20 个实例，再加入 4 个训练中不存在的新机制族，每族 10 个实例：

- train：已知族的 10 个实例；仅 `K-warm` 顺序运行并更新自己的 posterior；
- validation：已知族的 5 个实例；只用于冻结超参数和检查 harness；
- interpolation holdout：已知族的 5 个新实例；禁止写入 posterior；
- extrapolation holdout：4 个全新机制族各 10 个实例；禁止使用族名、常量、identity key 或训练期 artifact。

每个实例使用 5 个固定 paired seeds。五个主臂因此产生相同的任务-seed 配对，随机顺序由预注册 seed 生成。warm 训练期必须串行，否则并发更新会让学习顺序不可复现；其他阶段可以并行，但并发数必须写入 receipt。

当前 `eval/v1/split.yaml` 的 `extrapolation` 为空，因此不能直接把现有 split 当成泛化结论；正式运行前必须补齐非空的 extrapolation holdout。

## 5. 公平性控制

运行前固定以下内容并写入每个 receipt：

```text
claude_code_version
model_alias_and_resolved_model
system_prompt_hash
task_prompt_hash
plugin_revision
tool_manifest_hash
max_turns
max_budget_usd
wall_cap_seconds
temperature_or_sampling_settings
parallel_worker_limit
dataset_manifest_hash
prior_store_hash
random_seed
```

五个主臂必须使用相同的：

- 模型调用预算、最大 turn、墙钟上限和重试上限；
- MCP/tool 可见性和工具超时；
- 任务说明、目标材料和 checker；
- 终止条件。`CC` 没有 Kunglao 的停止钩子，但必须接受同样的墙钟和 turn 上限；`CC+guard`、`K-cold`、`K-warm` 的机械 checker 不能替模型完成答案。
- `CC+warm-context` 的历史材料必须通过与 `K-warm` 相同的 train-only 导出器生成，再由独立的 plain-text renderer 渲染；不得把 Kunglao 的动态决策结果或 held-out 事实带入上下文。

禁止以下泄漏：

- held-out 的 task id、常量、答案、ground truth 或 transcript 出现在 train posterior、pattern card 或 prompt；
- warm 运行把 held-out 结果写回同一 posterior 后再评估后续 held-out；
- 用最终答案文本决定 method-family credit；
- 只给 Kunglao 并行 worker，而基线没有等价的 token 和 wall-clock 预算。

## 6. 运行流程

### 阶段 A：harness 自检

先对每个任务运行 reference candidate、故意错误 candidate、checker replay 和 budget refusal。任何 checker 不能区分正确与错误的任务都从本轮排除并记录原因。

```bash
uv run python -m pytest -q
uv run python scripts/eval_split_lint.py
uv run python scripts/eval_smoke_runner.py --tier smoke --arm self-check --baselines
```

### 阶段 B：冷启动和基线

对每一个任务-seed，创建四个全新工作区，然后分别调用：

```bash
uv run python scripts/eval_loop_runner.py \
  --tasks <task-id> --tier <tier> --arm cc-default \
  --budget-usd <fixed> --wall-cap-s <fixed> --out <out-dir>

uv run python scripts/eval_loop_runner.py \
  --tasks <task-id> --tier <tier> --arm loop \
  --budget-usd <fixed> --wall-cap-s <fixed> --plugin-dir <repo> \
  --out <out-dir>
```

`cc-default` 记录 `CC`，`loop` 在空的 workspace store 下记录 `K-cold`。`CC+guard` 使用相同的任务候选和 checker，但冻结策略为 uniform；不能把它和 `CC` 的最终答案混在一个结果文档里。

### 阶段 C：warm-start 和上下文匹配

按 train split 的预注册顺序只运行 `K-warm`，每次 settlement 后保存 posterior hash、round index 和可选 strategy object hash。train 完成后复制一份只读 prior 到 held-out 工作区；评测进程拒绝任何 held-out 写入，直到该任务完成并生成 receipt。

同一份 train-only 导出物再生成 `CC+warm-context` 的静态上下文。导出器、渲染器、输入字节 hash 和上下文 token 数必须进入 receipt。`CC+warm-context` 不得读取 `runs/`，否则它不再是 context-matched baseline。

### 阶段 D：锁定后复跑

对所有主指标进行第二次独立 paired run。第一轮只允许发现 harness 错误；不得根据第一轮结果修改 gamma、shrink cap、任务筛选、阈值或 prompt。修复 harness 后整轮从头重跑并保留废弃 run 的 hash。

## 7. 指标和统计

### 主要指标

每个任务都必须由同一个机械 checker 产生：

- `evidence_supported_solve_rate`：PASS 且 evidence archive 完整的任务比例；
- `answer_rate`：任务得到正确答案的比例；
- `false_proven_rate`：被判定 PROVEN 但 minted probes 或 independent recheck 失败的比例；
- `premature_closure_rate`：声明收敛后重跑失败的比例；
- `cost_per_supported_solve`：token cost 加 wall-clock cost 的预注册线性成本。

### 次要指标

记录 `ttc_seconds`、input/output tokens、dispatch count、tool calls、重试数、首次有效 evidence 的时间、首次成功 act、失败方法重复率、posterior entropy、warm-start adaptation lag 和 extrapolation transfer rate。

### 统计规则

以任务-seed 配对差值为统计单位，而不是把每个 tool call 当独立样本。报告每个 split、任务族和总体的均值、median、p95、paired bootstrap 95% CI，以及 exact permutation/sign test。不得只报告一个总体平均数。

预注册胜出条件：`K-warm` 在 interpolation 和 extrapolation 上都满足以下条件才叫“超过”：

1. evidence-supported solve rate 不低于 `CC+warm-context` 两个百分点以上的退化；
2. false-proven 或 premature-closure 至少相对下降 25%，或者 cost-per-supported-solve 至少下降 15%；
3. 相应 paired 95% CI 不跨零；
4. extrapolation 的 answer rate 不低于 `CC` 五个百分点以上的退化；
5. `CC+warm-context`、`K-shuffle` 和 `K-uniform` 不能复现同等收益。

如果只在 warm train 或 interpolation 成立，结论只能写成“对已见机制族的运行优化”，不能写成通用能力超过。若 `K-warm` 只胜过 `CC` 而胜不过 `CC+warm-context`，结论只能归因于历史知识注入，不能归因于 RL。

## 8. 必做消融和反事实

正式结果同时运行以下消融：

1. `K-uniform`：验证收益是否来自 method-family posterior；
2. `gamma=1`：测量默认 adaptive gamma 是否过度遗忘；
3. 无 hierarchical shrinkage：测量全局 anchor 是否造成 state aliasing；
4. 无 option-death：测量 dead-path floor 是否真的减少浪费；
5. shuffled reward：检测 reward attribution 和 data leakage；
6. delayed credit：把 settlement 延迟到完整 round 后，检查 credit assignment 是否崩溃；
7. no-guard：将机械 verifier 去掉，分离 RL 对答案率和 RL 对可靠性的影响。

每个消融都必须保留相同的任务顺序、seed、预算和模型版本。

## 9. 风险、失效判据和解释边界

- **冷启动偏差**：策略注入在证据数不足时静默；如果大部分任务在两次 settlement 前结束，RL 没有有效暴露面。
- **状态别名**：state signature 是离散 bucket，互不相同的分析状态可能落入同一个 cell；若跨族失败率上升，应优先检查 state key。
- **proposal ceiling**：Q-cell 只能重排 LLM 已提出的 method-family；新方法发现能力不属于该学习器。
- **知识注入混淆**：warm posterior、pattern card 和失败路径本身可能是有价值的 few-shot context；必须由 `CC+warm-context` 吸收这部分收益后，才可把残差称为 RL 收益。
- **信用分配**：一次 dispatch 可能落地多个事实，round credit 不是纯粹的边际因果收益；late-cite amendment 不应重复入账。
- **非平稳性**：adaptive gamma 可能快速遗忘，导致长期重复失败；应报告 adaptation lag，而不是只看最终均值。
- **评测不公**：Kunglao 若使用 checker、并行 worker 或额外上下文，而 `CC` 没有等价资源，结果只能称为产品流程比较，不能称为算法比较。
- **安全边界**：任何样本执行都只能经 VM channel；实验脚本、transcript 和 receipt 不得包含 API key、token 或宿主机样本执行记录。

任何一项 checker 不稳定、任务泄漏、预算不等价、模型版本漂移或 held-out posterior 污染，整轮结果标为 `INVALID`，不作能力结论。

## 10. 结果文档格式

每次 run 写一个不可变 receipt，每个 arm 写一个聚合 JSON，最终报告必须包含：

```text
experiment_id
git_revision
dataset_manifest_hash
arm
split
task_seed_rows
model_and_tool_fingerprint
budget_fingerprint
prior_store_hash
metrics
paired_deltas
bootstrap_ci
per_family_breakdown
ablation_links
invalidity_flags
```

报告顺序固定为：有效性检查、主指标、warm/cold 曲线、interpolation、extrapolation、消融、失败案例、成本分析、最终判定。任何“超过”结论都必须能从 receipt 重放到 checker，而不是来自模型自评。

## 11. 本仓库的运行约束审计

当前仓库的标准测试命令由 `release-manifest.yaml` 定义为 `python -m pytest -q`。本次审计没有发现 `.github/workflows/ci.yml`、`Dockerfile`、`.husky/pre-push` 或 `.claude/rules/harness.md`，因此本实验不能假设这些文件提供额外 CI、容器或 harness 约束。实验结果应把命令行、环境变量白名单和版本 fingerprint 写入 receipt。

## 12. 本轮最小试跑

在完整矩阵开始前，先跑一个不产生能力结论的 smoke pilot：一个 smoke task、一个固定 seed、五个主臂各一次。目的只检查四件事：

1. 两个 Claude Code 入口都能在 headless 模式结束；
2. `K-cold` 的 strategy object 和 ledger 能被收集；
3. `K-warm` 确实从 train prior 读取而不是空启动；
4. checker 能对五个主臂生成相同 schema 的 receipt。

pilot 失败只能修 harness，不能调整算法参数或把 pilot 数字写成性能结论。

## 13. 已执行 smoke pilot（不构成能力结论）

2026-10-06 在同一 checkout、同一三个 smoke family、同一 `1.0 USD / 180s` 预算下执行了 `cc-default` 与 `loop` 两臂。两个臂都让机械 checker 对 `go-arx-v1`、`js-sign-v1`、`py-derive-v1` 得到 `3/3 PASS`，所以这轮没有观察到答案正确率差异。

| 臂 | checker PASS | session 完成 | session 墙钟 | loop 状态 |
|---|---:|---:|---:|---|
| `CC` | 3/3 | 2/3 | 1 个任务触达 180s | 1 exhausted、2 completed |
| `K-cold`（`loop`） | 3/3 | 0/3 | 3 个任务触达 180s | 3 exhausted，均 `BLOCKED` |

`CC` 的聚合 receipt：`runs/exp-cc-rl/smoke-cc-1usd/eval-results-20261006T113929Z-32059.json`。Kunglao 的聚合 receipt：`runs/exp-cc-rl/smoke-kunglao-1usd/eval-results-20261006T114904Z-44228.json`。

这轮只能说明：Kunglao 在三个构造任务上仍能产出可验证候选，但当前 loop 的 session 完成率和墙钟表现弱于 `CC`。它没有运行 `K-warm`、`CC+warm-context`、extrapolation 或消融，因此不能证明 RL 优越，也不能证明最终产品比较成立。

另外，三个 `K-cold` workspace 没有产出可用的 `q-cell-log`、`posterior-store` 或 `round-strategy` 学习输入；这轮实际测到的是完整 loop 的编排和验证开销，而不是 warm RL 的学习增益。
