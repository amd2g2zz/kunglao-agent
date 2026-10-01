# kunglao-agent

**kunglao-agent 是一套 RLVR 驱动的自主逆向工程系统：自己规划分析路径，无人值守连跑数小时到数天，从故障中自愈；只有当每个答案都扛过机械 oracle 判决之后才收敛交卷 —— 每条 claim 机器校验，每个 verdict 可复现，循环自己度量自己。**

[![release-check](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml/badge.svg)](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml) [![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org) [![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/amd2g2zz/kunglao-agent/pulls)

**简体中文** · [English](README.md)

> **术语约定**：`kunglao-agent`、`PROVEN`、`STAMP`、`oracle`、`RLVR`、`DTS`、`fact`、`claim`、`MCP`、`task_spec.yaml`、`claim-register.yaml`、`evidence/_index.json` 等已建立术语保留英文原文，其余均为中文。

## 它是什么

kunglao-agent 是一套自主逆向工程系统。你给它目标和待解问题；它自己规划
路径、派遣专家 worker、独立验证每条结论，只有当每个答案都被机械检查
落定（而不是模型自说自话）时才停下。

目标光谱是完整的：Windows/Linux 原生二进制、Android APK（含 native
`.so` 层）、Web/JS、协议还原、固件 —— 静态优先设计，驱动你环境里已有的
执行通道（VMware、ssh、docker、adb；纯静态任务一个都不需要）。

它目前以 [Claude Code](https://claude.com/claude-code) 插件形式分发。
Claude Code 是对话界面；产品本体是这套循环和它产出的 fact 库。

## 工作原理

### 循环的通俗版

1. **你提任务。** 分析目标 / 验证逻辑 / 约束 —— 记入 `task_spec.yaml`。
   完成判据（**oracle**）从你写的最终状态机械推导；任务写得含糊，
   oracle 就含糊。
2. **循环把目标拆成 claim**（`C-NN`，一条依赖 DAG）。每个 tick 跑一次
   收敛检查，决定下一步：派 worker、派验证者、等待、自愈、或停止。
3. **专家 worker 采集证据** —— 字节锚定的 `facts/F<NNN>.md`，每条通过
   `evidence/_index.json`（路径 + sha256）引用原始证据，附 `reproduce:`
   命令。
4. **独立验证者盲重推每条 claim**（maker-checker）：验证者只看原始证据
   和问题，永不读 maker 的结论。没有签核，就没有 `PROVEN`。
5. **机械门控落定每条 claim。** oracle 判决 —— 对量化验证契约的机器
   校验决定 —— 是系统里唯一可信的货币。结算落在唯一的只追加账本上，
   带 `rule_id` + 证据引用：每个 reward 都答得出"这个数从哪来"。
6. **循环从结算中学习**（RLVR，见下），并**收敛**：`CONVERGED`
   （退出码 0）表示每个主问题都有已验证的答案、零全局矛盾、完成事务
   干净 —— 全部机械重算，绝不自我宣布。

长时程是设计目标：心跳让循环一直活着，死掉的 worker 被补位、其 claim
重新入队，崩溃后从落盘状态续跑（`resume`），旧工作区向前迁移
（`upgrade`）。

### 学习循环（RLVR）

没有人类给输出打分 —— oracle 判决就是 reward。统计引擎是 **DTS
（Discounted Thompson Sampling，折扣汤普森采样）**：每个臂维护 Beta
后验，用衰减因子 γ 折扣，新近结果权重高于历史结果，γ 调度自适应。
采样决定下一个尝试哪条 claim、哪个方法族；结算回写后验。包表面是
[`scripts/rlvr/`](scripts/rlvr/) —— 单一导入点、单一导出表。

| RLVR 组成 | kunglao 做什么 | 在哪 |
|---|---|---|
| Reward | 每条 claim 由 oracle case 背书 —— 量化验证契约：点名产物、机械判据（无 LLM 可运行）、阈值。语义准入门拒绝含糊判据并强制分解："理解了协议"会被弹回；"14 对里匹配 ≥ 11"才能入账 | [`scripts/oracle_case_admission.py`](scripts/oracle_case_admission.py) |
| Sampling | DTS：自适应 γ 的 Beta 后验，每个可派发 claim 每 tick 采一次；case 面给 claim 排序，Q-cell 面给（状态, 方法族）对排序 | [`scripts/rlvr/posteriors.py`](scripts/rlvr/posteriors.py)、[`scripts/rlvr/q_cells.py`](scripts/rlvr/q_cells.py)、[`scripts/priority_ratio.py`](scripts/priority_ratio.py) |
| 内核算子化 | 结算折入后验存储；学习到的状态每 tick 合成唯一一个 round-strategy 对象，四个出口喂给派发（方法主导 / 反提示 / 预算）、循环监控、hook 卡片与参数修正 —— 模板句从具名账本行填充，零模型调用 | [`scripts/rlvr/compose.py`](scripts/rlvr/compose.py)、[`scripts/rlvr/strategy_store.py`](scripts/rlvr/strategy_store.py) |
| State | 规范化离散的工作区状态带确定性价值锚，喂给 Q cell；格式戳工作区在盘上携带脚手架版本，`upgrade` 向前迁移、不碰用户数据 | [`scripts/rlvr/state.py`](scripts/rlvr/state.py)、[`scripts/kunglao_upgrade.py`](scripts/kunglao_upgrade.py) |
| 障碍归因 | 派生干预产生的失败原因记为障碍对象（`runs/obstacles/`）并读入状态签名 —— 归因是证据，不是判决 | [`scripts/rlvr/obstacles.py`](scripts/rlvr/obstacles.py) |
| Option 终止 | 学出来的"何时止损"：按（障碍类, 方法族）的 Beta 估计一条投资弧是否已死；死掉的 option 被 PARK（降权），永不删除 | [`scripts/rlvr/termination.py`](scripts/rlvr/termination.py) |
| Terminal credit | 主 oracle 全绿收官时，一条结算行回引促成收官的使能链 —— 哪些 case 转绿、哪些 claim 结算产生了它 —— case 检索对这类教训加权 | [`scripts/terminal_settlement.py`](scripts/terminal_settlement.py) |
| 度量 | replay ruler 在备选排序器配置下重放历史账本，报告确定性的收敛时间 | [`scripts/replay_ruler.py`](scripts/replay_ruler.py) |
| Settlement | 每次 rollout 记入唯一的只追加账本；确定性规则表结算，校验器守墙 —— 引用的证据 id 必须可解析（fail-closed）、分数钳在声明轨道内、oracle 判决永不可覆盖 | [`scripts/rlvr/ledger.py`](scripts/rlvr/ledger.py)、[`scripts/rlvr/reward.py`](scripts/rlvr/reward.py)、[`scripts/rlvr/scalar.py`](scripts/rlvr/scalar.py) |
| 经验沉淀 | 每轮溯源学分（创作者署名产物）、工具调用日志、状态签名抽取为经验三元组 `(s, a, r)`（可再生 CSV），附只读的逐格均值 Q 报告 | [`scripts/rlvr/triples.py`](scripts/rlvr/triples.py)、[`scripts/tc_journal.py`](scripts/tc_journal.py) |
| 验证阶梯 | 三级验证：写入门（T0）、去抖于已验证写流的中轮 oracle 探针批（T1）、按解锁价值排序的轮末优先队列（T2） | [`scripts/verification_ladder.py`](scripts/verification_ladder.py)、[`scripts/oracle_cadence.py`](scripts/oracle_cadence.py) |
| 主线决策 | 每条主线决策以 `(s_M, A_M, ΔV)` 行落账 —— 状态签名、封闭动作词表、相对确定性锚的价值增量 —— 机械记录、幂等 | [`scripts/rlvr/state.py`](scripts/rlvr/state.py)、[`scripts/verification_ladder.py`](scripts/verification_ladder.py) |
| Reflection | FAIL 结算发出结构化 gap-note（撞到的诱饵墙、证据缺口、成本超支 —— 仅机器信号，advisory 标记）；同单元重试读取前任的记录，第 N 次尝试不是第 1 次的重复 | [`scripts/gap_notes.py`](scripts/gap_notes.py) |
| 在线蒸馏 | 运行时 shelf-miss 触发一次预算内的蒸馏动作：先重查库，再走 web 面；候选对着锚定样本字节验证、落盘 run-local；频率受预算治理，永不禁止 | [`scripts/online_distill.py`](scripts/online_distill.py) |
| 蒸馏脊柱 | 所有蒸馏知识经单一脊柱通道 + 源信任门入库 —— 跳阶段的产品被大声拒绝；从工作区收割的可复用脚本经同一纪律入图书馆 | [`scripts/distill_spine.py`](scripts/distill_spine.py)、[`scripts/script_harvest.py`](scripts/script_harvest.py) |
| 特征条件先验 | 可选（默认关）：按工作区特征相似度条件化初始后验 —— 启用以它自己的 A/B 重放证据为准 | [`scripts/rlvr/feature_prior.py`](scripts/rlvr/feature_prior.py) |

术语锚点：**step** 是收敛循环的一个 tick；**rollout** 是一次分析轨迹；
**episode** 在主绿处结束；**option** 是跨 claim 的投资弧。

## 实战案例

脱敏的单页实战报告 —— agent 接了什么目标、遇到什么防御面、走了什么
路线、拿到什么机械判决：

- [Android 加固 native crackme](docs/cases/hardened-android-crackme.zh-CN.md) —— 14 层防护（CFF、自修改代码、反 hook/反模拟、加密常量、诱饵车道）；无人值守，常量 3/3，重放 18/18 逐字节一致。
- [Web 请求签名还原](docs/cases/web-request-signing.zh-CN.md) —— 混淆与反爬防护下端到端刻画生产级签名方案，含扣留交互逐字节复现。
- [桌面端 agent 授权协议](docs/cases/desktop-agent-license.zh-CN.md) —— challenge/response 授权握手完整刻画并逐字节重放，每条 claim 独立盲验证。

每个案例在 `docs/cases/` 下同时有中英文两个版本。

## 快速开始

从磁盘上的样本到 verdict：

| 工具 | 作用 | 安装 |
|---|---|---|
| **Claude Code** | kunglao-agent 的运行环境 | 按 Anthropic 官方文档 |
| **Python 3.10+** | 插件自带 `uv` 管理的锁定环境，你不用动 | 系统装或 `uv` 管 |
| **`uv`** | 锁定环境解析器 | `pip install uv` 或 [astral.sh/uv](https://astral.sh/uv) |
| **Ghidra 或 IDA** | 二选一，作为反编译器 | 见[按目标类型分工具链](#按目标类型分工具链) |

### 1. 装插件

在任意目录下，进入 Claude Code：

```
/plugin marketplace add amd2g2zz/kunglao-agent
/plugin install kunglao-agent@kunglao-agent
```

（开发模式也可以：`claude --plugin-dir /path/to/kunglao-agent`。）

### 2. 初始化工作区

```
/kunglao-agent:init ~/cases/synth-dropper --type windows
```

`kunglao-init` 搭好工作区、写好 `CLAUDE.md`、按你选的 `--type` 探测
工具链、生成 `.mcp.json`。你选的类型有 HARD 工具缺失时，init 会
**HARD-reject** —— 修复指引就写在错误块里。

### 3. 提出任务，启动分析

```
/kunglao-agent:analysis ~/cases/synth-dropper
> 分析目标：确认这个 dropper 的持久化手段和网络出口，
>   每条结论都要能从原始证据复现。
> 验证逻辑：关键结论必须由独立验证者盲重推一致才算成立。
> 约束：静态优先，样本不许在宿主机执行。
```

把需求写成一个独立评审者也能评判的简报：**分析目标**（你要知道
什么）、**验证逻辑**（凭什么信答案）、**约束**（不许做什么）。全部记入
`task_spec.yaml`，之后循环自己推进。常见的口头需求怎么写成合格的任务
描述，见[怎么写任务描述](#怎么写任务描述)。

### 4. 看交付物

```
claim-register.yaml   # 每条 claim 都 terminal，带验证者签核
facts/F<NNN>.md       # 字节锚定、可复现、frontmatter 契约
evidence/_index.json  # 每个 fact 对应一份原始证据（sha256 + 路径）
runs/                 # 会话审计轨迹
```

## 怎么写任务描述

循环的完成判据 —— **oracle** —— 是从你写下的最终状态机械推导出来的。
写得含糊，oracle 就含糊，分析就会漂向"能证明什么"，而不是"你要什么"。
四种说法覆盖大部分漂移场景：

| 你说 | 通常的真实含义 | oracle 锚定在 |
|---|---|---|
| "我要纯算" | 离线复现签名/加密算法（unidbg harness 或独立重写）—— 不是"分析这个 App"；App 只是算法的宿主 | 对全部抓包 (input → sign) 对逐字节重放一致 —— 含扣留对 —— 运行时不依赖设备和 App |
| "我要解密" | 先说清是哪个：(a) 解开一段抓到的数据，或 (b) 要一个可复用的解密能力 —— 算法 + 密钥 | (a) 明文与 App 实际渲染的内容对得上；(b) canary 回环与设备产出的密文逐字节一致 |
| "帮我分析这个协议" | 还原线上格式：帧定界、字段语义、外加一个能跑的编解码器 | 编解码器对每一帧抓包逐字节回环一致；扣留帧解出的字段与观察到的 App 行为吻合 |
| "这个 sign 在哪算的" | 要的是"位置 + 证明" | 指名道姓的类/方法/native 函数，加上该点的 hook 能复现抓包值 |

共同点：

- **点名样本和行为** —— 哪个参数、哪个入口、哪条流程 —— 别只报类目。
  "我要纯算"是类目；"给 api.example.com/v2/* 生成 `sign` 头的签名函数"
  才是目标。
- **成功必须是数据。** 附上抓到的输入/输出对；扣留对让检查诚实 ——
  复现没法过拟合没见过的数据。
- **约束改变路线。** 只能静态？有没有设备？走哪个 channel？提前说清楚，
  开工前就把路线定下来（见[自带分析环境](#自带分析环境)）。

## 一次分析长什么样

一个合成示例：小型 Windows dropper 落在 `~/cases/synth-dropper`：

```bash
/kunglao-agent:init ~/cases/synth-dropper --type windows   # 探测 Ghidra、VM 可达性
/kunglao-agent:analysis ~/cases/synth-dropper
> "这个二进制干了什么，回连到哪里？"
```

接下来循环自己跑 —— 路线随样本实际情况调整，不是固定剧本。你可以走
开；死掉的 worker 被补位、其问题重新排队，任何中断之后
`/kunglao-agent:resume` 从落盘状态重建现场。收敛后读上面的交付物。

## 子命令

| 命令 | 什么时候用 | 做什么 |
|---|---|---|
| `/kunglao-agent:init <路径> --type <windows\|linux\|android\|web\|macos> [--lane malware\|algorithm\|protocol\|web\|data\|app]` | 开始一次分析，先建工作区 | 搭建工作区，按类型探测工具链，写 `CLAUDE.md` 和 `.mcp.json`；HARD 工具缺失时 HARD-reject，错误块里带修复指引 |
| `/kunglao-agent:analysis <路径>`（别名 `analyze`） | init 之后，提出任务、开跑分析 | 一次性收集你的分析目标 / 验证逻辑 / 约束，进入收敛循环：派工 / 验证往复，收敛后出报告 |
| `/kunglao-agent:resume <路径>` | 崩溃、重启之后，或任何"我刚才跑到哪了" | 只读的断点简报（健康状态、open claim、在跑 worker、崩溃时间线）加上状态机给出的下一步 |
| `/kunglao-agent:upgrade <路径> [--dry-run]` | 插件升级后打开旧工作区 | 把工作区脚手架（hooks、模板、事件词表）迁移到当前插件版，`--dry-run` 可预览；用户数据（claims、facts、evidence）绝不触碰，字节级漂移即拒绝（RC=4） |
| `/kunglao-agent:help` | 忘了命令 | 打印用法列表 |

典型顺序：`init` 建工作区 → `analysis` 提需求开跑 → （随时用 `resume`
接续进度）→ 收敛读报告 → 插件升级后对旧工作区跑一次 `upgrade`。

## CLI 控制台脚本

在仓库根 `uv sync` 后，路由器注册为 `kunglao` 控制台脚本：
`kunglao --help` 列出全部九个子命令 —— `decide`、`tick`、`verify`、
`record`、`health`、`resume`、`check-stale`、`upgrade`、`analysis` ——
技能里教的每个 `kunglao <子命令> <工作区>` 调用都在 PATH 上。独立入口：
`kunglao-init`、`kunglao-verify`、`kunglao-upgrade`、`heartbeat-tick`、
`convergence-check`（见 pyproject.toml 的 `[project.scripts]`；
`kunglao_agent_cli/` 里的包装只做注册 —— 目标仍是
`scripts/<file>.py`）。

参考的端到端调用（金标准验收 harness —— 对一个 eval 单元跑
init → analysis → 开环 → oracle，全部事件流进统一的审计流
`<ws>/runs/logs/e2e-audit.jsonl`）：

```bash
uv run --project . python scripts/e2e/run.py --unit py-derive-v1 --dry-llm
```

`--auto-llm` 切换为真实无头 LLM 执行；`--resume <run-id>` 接续半程运行。

## 读交付物

一个声明登记加事实库，信任靠机器执行，不靠口头约定：

| 问题 | 去哪看 |
|---|---|
| 做完了吗 | 循环的退出码 —— `CONVERGED`（0）表示每个主问题都有已验证的答案；逐条 claim 状态在 `claim-register.yaml` |
| 找到了什么 | `facts/F<NNN>.md` —— 一条 fact 一个文件，由 `claim-register.yaml` 映射回 claim |
| 怎么复现 | `evidence/_index.json` —— fact → 原始证据（路径 + sha256）；每条 fact 带 `reproduce:` 命令 |
| 具体发生了什么 | `runs/` —— 逐 tick 的 ledger 和 worker 状态 |

fact 样例：

```yaml
id: F061
status: VERIFIED-BY-W01-static-byte-recheck
claim_id: C-401
provenance:
  - {role: sample, path: bins/<sha>}
  - {role: capture_log, path: runs/c329-inner-pe.bin}   # 经 evidence/_index.json 引用
reproduce: python -c "import struct; ..."               # 对着引用的证据跑
verifier_sign_off: {verifier: kunglao-redteam, verdict: CONFIRMED}
```

没有任何 claim 能靠作者自己说了算：必须由独立验证者盲重推一致，并通过
一组机械门控。完整门控设计见
[`docs/design/loop-engineering.md`](docs/design/loop-engineering.md)。

worker 绝不手改工作区 YAML：登记与账本一律经
[`scripts/ws_yaml.py`](scripts/ws_yaml.py) 编辑（点路径 get/set/del +
往返校验 —— 不能往返的写入被拒绝）。

## 看懂运行时的可视化

两张实时面孔把一次运行变成你能盯的东西。

**胜率曲线** —— 结算流上的滚动成功率：

```bash
uv run python scripts/winrate_curve.py <工作区> [--window 5] [--html curve.html]
```

x 轴是只追加账本上的结算序号；y 轴是滚动窗口（默认 5）内的通过率。
`--json` 出机器可读面；`--html` 写单文件图表。健康的运行随循环学会
哪些 case 和方法有效而向上走；贴零的平线说明排序器把预算花在从不结算
的臂上 —— 先查障碍登记再加预算。

**statusline** —— agent 运行时的单行 HUD。
`scripts/statusline_snapshot.py` 按语义事件写快照
（`<ws>/runs/.kunglao-statusline.json`），渲染器（`statusline_render.mjs`，
kunglao-init 接线）零开销显示。你看到的：

| 段 | 含义 |
|---|---|
| 状态字形（`◈ analyzing` / `◇ tossing` / `○ idle` / `◌ stall` / `✖ DOWN` / `◉ flawless`） | 语义状态机，优先级 down > flawless > stall > toss > analyzing > idle；探针短码（`[ledger]` `[hook]` `[stall]` `[audit]`）标出该看哪个文件 |
| `C<closed>/<total>` | claim 进度（已闭合 / 总数） |
| `wr` | 当前胜率 |
| `R:` 排名片 | DTS 采样器此刻把哪个动作排在第一，以及该排名多新鲜 |
| 健康点（×3） | oracle 能力 / 回溯延迟 / 探测器活性，一眼看完 |
| 任务片 | 现在谁在做什么（`claim` + 任务短语） |
| `v` 迷你走势 | 最近的价值锚点 —— 工作区是否在可测地推进 |

策略窗口内的陈旧快照渲染为 idle（诚实：确实没事件）；超出存活策略
渲染为 DOWN。

## 评估与实测结果

能力数据集在 [`eval/`](eval/README.md)：构造目标、机械 oracle、构造即
知的 ground truth。一次运行产出 `METRIC`/`VERDICT` 流并归档带证据条的
结果行。反记忆是设计出来的：目标构造 + 种子变异；checker 铸造候选从未
见过的扣留探针；eval 语料被契约性排除在任何蒸馏源之外。

**分层。** smoke 层（三个构造族，分钟级）、release 层（原生
arm64/PE/x86-64、UPX 壳、自修改代码、网络授权校验、请求签名、web 打包
—— 难度 L0 → L2(+L2p/L3)）、chain 层（2–6 层嵌套防护）、misdirection
层与 tool-flex 层：

```bash
uv run python scripts/eval_smoke_runner.py --tier smoke               # 自检：参考候选必须绿自己的 oracle
uv run python scripts/eval_smoke_runner.py --tier smoke --baselines   # 追加 1/k 瞎猜地板行
```

结果落在 `runs/eval-smoke/`。`--tasks <id,id>` 圈定范围；
`--candidate-for <task_id>=<path>` 把外部臂的产物接进同一 checker。

**控制臂 A/B** —— 裸 LLM 对框架，一条命令：

```bash
uv run python scripts/eval_control_arm.py --ab --manifest bare-candidates.jsonl --framework-manifest framework-candidates.jsonl
```

两臂都从 `kunglao-eval-candidates/1` 清单读候选（`--live` 改为仅提示的
`claude -p` 运行）。五个指标定胜负：`answer_rate`、
`proven_with_evidence_rate`、`premature_closure_rate`、`false_proven_rate`、
`budget`。

**replay ruler** —— 离线排序质量度量。指向一个完成的工作区，它在备选
排序器配置下重放历史账本，按配置报告确定性收敛时间：

```bash
uv run python scripts/replay_ruler.py ~/cases/finished-engagement
```

源工作区只读打开；写入落沙箱。`--configs-json` 给配置集；
`--with-events` 加对历史排名事件的 λ 认识论检查。

**实测结果** —— 内置 12 单元 L1 eval 矩阵（跨 JS、x86/ARM64 ELF、
Windows PE 的静态逆向目标；严格 checker 的 oracle 评分 —— 只要字节锚定
交付物、无部分分、每会话 $15 / 3600s 上限、pass@1）：

| 运行时 | pass@1 | 会话成本 |
|---|---|---|
| kunglao v0.1.5.post2 | 5/12 | ~$135 总计（13 会话） |
| kunglao v0.1.6 | **11/12** | ~$120 总计（4 轮受治理迭代） |
| 裸 Claude Code（默认 harness，无插件） | 12/12 | ~$11.4 总计 |

方法论：所有行同一 harness（同 runner、同 checker、同单元）；pass@1，
k=1；耗尽计为失败；harness 面完整性门生效；度量期间零运行时打补丁。诚
实地读：这 12 个单元是单会话可解的，前沿模型配默认工具以最低成本满分
—— kunglao 的差异化在长时程分层工作、验证纪律（每条 claim 都过
oracle + 盲红队）与动态车道，不在静态单会话速度。reward 通路（结算、
校验、溯源学分、经验记录）在每次运行上都活着；学习策略的消费通路 gated
在它自己的 eval 战役后面，保证基准度量的是冻结行为。

## 按目标类型分工具链

init 时选的 `--type` 决定哪些 HARD 工具必须装。指引默认折叠 —— 展开你
的目标。**所有类型都需要两个 MCP server：** `ghidra`
（`claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe`）和
`sequential-thinking`（`claude mcp add sequential-thinking -- npx -y
@modelcontextprotocol/server-sequential-thinking`）。

<details>
<summary><strong>windows（PE32+ x86-64）</strong> —— Windows 原生二进制</summary>

| Tier | 工具 | 安装 |
|---|---|---|
| HARD | `pefile`（Python） | `uv pip install pefile` |
| HARD | `die`（Detect It Easy） | `KUNGLAO_DIE` 环境变量或在 PATH —— [ntinfo.com](https://ntinfo.com) |
| HARD | `floss`（FLARE FLOSS） | 按 [flare-floss 文档](https://github.com/mandiant/flare-floss) 装 |
| HARD | Ghidra 或 IDA | 二选一；见[内部](#内部) |
| HARD（T2/T3） | VMware + vmr-shell，或 ssh/docker channel | 见[自带分析环境](#自带分析环境) |
| HARD（T2/T3） | `frida-server`（改名，自定义端口） | 设备/VM 侧二进制，默认端口 1337 |

Windows 的 T3 动态还要用 `x64dbg` MCP；`volatility`（内存取证）和
IDA-Pro MCP 可选 —— 见[内部](#内部)的 MCP 清单。

</details>

<details>
<summary><strong>linux（ELF）</strong> —— Linux 原生二进制 / 固件 / 内存镜像</summary>

| Tier | 工具 | 安装 |
|---|---|---|
| HARD | `file`、`readelf`、`objdump` | `binutils` 包 |
| HARD | Ghidra 或 IDA | 二选一 |
| HARD（T2/T3） | VMware + vmr-shell，或 ssh/docker 控制平面 | 见[自带分析环境](#自带分析环境) |
| HARD（T2/T3） | `frida-server`（改名，自定义端口） | 设备端二进制，端口 1337 |
| WARN | `gdbserver`（主机侧 PATH）、`strace`、`ltrace` | 可选补充 |

`ssh-mcp` 给远程 / 云 / docker 主机开 ssh 控制平面。

</details>

<details>
<summary><strong>android（APK / DEX / native .so）</strong> —— 难度最高、HARD 项最多</summary>

| Tier | 工具 | 安装 |
|---|---|---|
| HARD | `aapt` 或 `aapt2`（或 `unzip` 兜底） | Android SDK build-tools |
| HARD | `jadx`（DEX → Java 反编译器） | [skylot/jadx](https://github.com/skylot/jadx) |
| HARD | `apktool`（APK 资源解码 / 重打包） | [iBotPeaches/Apktool](https://github.com/iBotPeaches/Apktool) |
| HARD | `gitnexus`（反编译后图谱） | `npm i -g gitnexus` |
| HARD | Ghidra 或 IDA | 仅当 APK 含 native `.so` |
| HARD | `adb` + **已 root 设备**，`ro.debuggable=1` | platform-tools + 设备端自定义 frida |
| HARD | `frida-server`（改名，自定义端口 1337） | 设备端二进制 |
| HARD | `android_server`（IDA 远程调试） | 设备端二进制，端口 23946 |
| WARN | `apkid` | `uv pip install apkid` |
| WARN | `baksmali` | 从 [smali releases](https://github.com/baksmali/smali/releases) 下载 |

</details>

<details>
<summary><strong>web &amp; macos</strong> —— 按设计轻量的工具链</summary>

| Tier | 工具 | 安装 |
|---|---|---|
| HARD | `camoufox-reverse` MCP（web） | 反检测 Firefox（hook / trace / 网络抓包），web 上必需 |
| WARN | `docker`（web channel 默认） | Docker Desktop，或显式 `KUNGLAO_CHANNEL=ssh` |
| WARN | `lipo`、`otool`、`nm`、`codesign`、`xattr`（macOS） | Xcode Command Line Tools |
| WARN | `ghidra` MCP（macOS） | 推荐 —— 见[内部](#内部)的清单 |

这两类目标在 init 只探测必需项；更重的能力在目标真正需要时启用。
macOS 的动态分析走 `ssh` channel（连到 Mac 主机）；要用可选的 x64dbg
浏览器侧调试，就按上面的 Windows 工具链装。

</details>

以上所有内容的统一真源 —— 随时可探测：
`uv run python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>`
（退出码 1 = HARD 缺失）。

## 自带分析环境

动态调试需要一个 agent 能驱动的执行控制平面。`KUNGLAO_CHANNEL` 在五个
一等公民 channel 里选一个 —— 你环境里已有什么就用什么，没有降级模式：

| Channel | 驱动什么 | 前置 |
|---|---|---|
| `vmr`（默认） | VMware 驱动的 VM，**任何客户机系统** —— snapshot/revert 工作流是它不可替代的价值 | vmr-shell 技能；`KUNGLAO_VM_HOST` + 端口 9876/1337 |
| `ssh` | 任何 ssh 可达的机器：远程裸机、云 VM、Mac、远程 docker 主机 | 密钥认证 —— 探测会真的跑一次 BatchMode `ssh ... true` |
| `docker` | 本机或远程 docker daemon —— `docker exec` 等价于任何控制路径 | `docker version` 绿；可选 `KUNGLAO_DOCKER_CONTAINER` |
| `adb` | 安卓模拟器或真机 | `adb devices` 能看到设备；`adb forward tcp:1337 tcp:1337` 给 frida |
| `local` | **仅主机侧静态分析** | 无 —— 见下面的红线 |

> **`local` 红线：** local 只为**静态**工作准备 —— 绝不在主机上执行、
> 调试、注入样本。任何动态需求都把 `KUNGLAO_CHANNEL` 切到
> `vmr`/`ssh`/`docker`/`adb`；动态任务配 `local` 会被 init HARD-reject。

channel 探测只对动态任务跑（纯静态任务直接跳过）。`ssh` channel 上的
执行流过 **ssh-mcp** 控制平面（`npm i -g ssh-mcp`）；裸 CLI ssh 是兜底。
远程 docker 走 ssh 时，设 `KUNGLAO_DOCKER_CONTAINER`。

## 配置

四个变量覆盖大多数场景：

| 变量 | 默认 | 含义 |
|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | 未设 | 必须保持未设或 `0` —— 真值会让派工走 teammate channel，会被拒绝 |
| `KUNGLAO_CHANNEL` | `vmr` | 动态分析执行控制平面：`vmr` \| `ssh` \| `docker` \| `adb` \| `local` —— 见[自带分析环境](#自带分析环境) |
| `KUNGLAO_VM_HOST` | 未设 | 动态分析的 VM/主机（vmr-shell :9876，Frida :1337） |
| `GHIDRA_HOME` | 未设 | Ghidra 安装根目录（要含 `support/analyzeHeadless.bat`） |

很少用到：`KUNGLAO_DOCKER_CONTAINER`（`ssh`/`docker` channel 的 docker
执行目标）、`KUNGLAO_FRIDA_PORT`（默认 1337）、`KUNGLAO_DIE`（DIE 路径，
兜底 PATH）、`KUNGLAO_CLAUDE_JSON`（用户级 MCP 注册表的测试覆盖）。

## 常见问题

**它什么时候停？**
`CONVERGED`（退出码 0）：`task_spec.yaml` 里每个主问题都有 `PROVEN`
fact 背书的答案、零全局矛盾、完成事务重算干净。预算与墙钟上限约束
运行；耗尽计为失败，绝不静默算成功。

**claim 状态是什么意思？**
`OPEN`（未落定）、`PARTIALLY-VERIFIED`（有 fact、无盲签核）、
`PROVEN`（独立验证者盲重推一致且门控通过）、`STAMP`（自我宣布 ——
永不信作证据）。worker 自己的签核最多产生 `STAMP`。

**oracle 判决是什么意思？**
对量化验证契约的机器校验决定 —— 点名产物、无 LLM 可运行的机械判据、
阈值。它是系统里唯一可信的货币；结算校验器拒绝覆盖它。

**怎么读 FAIL 结算？**
FAIL 在结算行旁边发出结构化 gap-note（撞到的诱饵墙、证据缺口、成本
超支 —— 仅机器信号，advisory 标记）。同单元重试读取前任的记录，下一
次尝试攻打点名的缺口，而不是重复第 1 次。

**PARK 是什么？**
option-death 估计器按（障碍类, 方法族）学习一条投资弧是否已死。死掉的
option 被 PARK —— 采样中降权 —— 永不删除；它的历史留在账本上，状态
变了可以复活。

**循环报 BLOCKED —— 卡死了吗？**
`BLOCKED`（退出码 4）表示所有 open claim 都被阻塞。循环对 blocker 跑
自愈；SUSPECT/陈旧前提被自动作废并重推。持续的 blocker 连同失败归因落
`blockers/` —— 加预算前先读那些记录。

**崩溃之后怎么续？**
`/kunglao-agent:resume <工作区>`（或 `kunglao resume <工作区>`）：只读
断点简报 —— 健康、open claim、在跑 worker、崩溃时间线 —— 加状态机的
下一步。全部状态在盘上；不需要任何会话上下文。

**必须要有 VM 或 MCP server 吗？**
纯静态任务完全不需要执行平面（`KUNGLAO_CHANNEL=local`）。动态任务需要
vmr/ssh/docker/adb 之一。MCP 方面，所有类型都要 `ghidra` +
`sequential-thinking`；web 另需 `camoufox-reverse`（随插件自带）。随时
探测：`uv run python scripts/mcp_probe.py <ws> --type <type>`。

**我的工作区比插件版本老。**
`/kunglao-agent:upgrade <工作区>` 把脚手架（hooks、模板、事件词表）向前
迁移；用户数据绝不触碰，字节漂移即拒绝（RC=4）。版本不匹配会拒绝开
analysis，直到升级完成。

**怎么加一个 eval 族？**
建 `eval/v1/tasks/<tier>/<family>/`，放齐四份契约文件：`task.yaml`
（schema `kunglao-eval-task/1`，含三个 oracle 锚 —— 目标原话、成功判据、
验证方法）、构造出的 `target/`、`ground_truth.json`、独立的
`checker.py`。对已用版本的任何变更都要铸新版本目录 + changelog 条目
—— 绝不静默就地改动。eval 语料被契约性排除在蒸馏源之外（见
[`eval/README.md`](eval/README.md)）。

## 安全

- 样本绝不在主机上执行 —— `block_malware_exec` hook 强制；动态只跑在
  VM/容器/设备里，且要求逐会话授权。
- 真相等级：原始证据 > 本地工具 > 沙箱 > 威胁情报（CTI 是可证伪的假设，
  不是真相）。
- Maker-checker：worker 永不自我验证；验证者永不读 maker 的结论。
- bins、settings、hooks 永不入库；密钥与工作区、仓库隔离。

## 开发

欢迎贡献。流程：从 `dev` 切分支，一个改动一个分支，PR 回 `dev`。

```bash
git worktree add .worktrees/<name> -b <name> dev
uv sync --locked
uv run python -m pytest -q
gh pr create --base dev
```

权威的全量测试入口是 `uv run python -m pytest -q`（见
.github/workflows/release-check.yml）。

设计文档在 `docs/` 与 `specs/`。见[许可证](#许可证)。

## 内部

<details>
<summary><strong>MCP 供应（完整清单）</strong></summary>

单一真源：`scripts/mcp_probe.py`；`kunglao-init` 在缺失时生成工作区
`.mcp.json`（`--no-mcp` 跳过；已有文件绝不覆盖）。探测：
`uv run python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>`
—— 退出码 1 = HARD 缺失，2 = 仅 WARN 缺失。

| MCP server | Tier | Scope | 用途 | 注册 |
|------------|------|-------|---------|--------------|
| `ghidra` | HARD | 所有 type 必需 | 反编译 / 静态分析 | `claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe` |
| `sequential-thinking` | HARD | 所有 type 必需 | 结构化推理 | `claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| `x64dbg` | HARD | Windows T3 动态 | 动态调试（VM 远程） | `claude mcp add x64dbg -- x64dbg-automate-mcp` |
| `volatility` | WARN | Windows T3 | 内存取证 | `claude mcp add volatility -- python <path>/volatility_mcp_server.py` |
| `ida-pro-vm` | WARN | 选 IDA 时 | 远程 IDA 分析 | `claude mcp add --transport http ida-pro-vm <ida-mcp-url>` |
| `gitnexus` | HARD | Android 图谱构建 | 反编译后知识图谱 | `claude mcp add gitnexus -- gitnexus mcp` |
| `ssh-mcp` | WARN | channel | ssh 执行控制平面 | `claude mcp add ssh-mcp -- ssh-mcp` |
| `virustotal` | WARN | CTI | 威胁情报（家族归属假设） | `claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal` |
| `camoufox-reverse` | HARD | web | 浏览器 JS 逆向（hook / trace / 网络抓包）—— web 必需 | 随 kunglao-agent 插件自带（`.claude-plugin/plugin.json mcpServers`）—— 启用插件；装依赖：`uv pip install camoufox-reverse-mcp` |

</details>

<details>
<summary><strong>工作区布局</strong></summary>

一个工作区对应一次样本分析：

```
<workspace>/
├── bins/<sha256>              # 样本（gitignore）
├── task_spec.yaml             # primary_questions / scope / constraints / success_criteria
├── claim-register.yaml        # claim C-NN（OPEN/PROVEN/STAMP/...）
├── claim_deps.yaml            # claim DAG
├── facts/                     # 字节锚定 fact F-NNN.md + _INDEX.md
├── evidence/                  # 原始证据 + _index.json（eid → 路径 + sha256）
├── runs/                      # worker-status、plan、ledger、.heartbeat.json
├── blockers/                  # 每个 claim 的失败归因记录
└── CLAUDE.md                  # 工作区规则，kunglao-init 生成
```

kunglao hook 只落在工作区层级；你的全局 `~/.claude/settings.json` 永远
不会被写入。

</details>

---

## 许可证

双协议许可：**AGPL-3.0** 用于个人、学术、内部使用（免费 —— 见
[LICENSE](LICENSE)）；闭源或 SaaS 商业使用需要**商业许可** —— 见
[LICENSE-commercial.md](LICENSE-commercial.md)。
