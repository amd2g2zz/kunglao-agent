# Loop Engineering — kunglao 主 loop 研究(2026-08-10,整合 + 细化版)

> 两轮调研(LangChain/DSD + cobusgreyling repo)+ 4-subagent 多视角细化 + 代码级根因验证。
> VoI 打分调研已落 `design-spec.md` §3.2;本文件是 **loop 层**的研究终稿。

## 1. 研究范围与方法

**问题**:kunglao-agent 主 loop(convergence loop)是否需要改进?改进什么?
**方法**:框架映射(LangChain 4-loop / DSD 10 模式 / cobusgreyling 5-block)→ kunglao 对照 → 4 subagent 多视角细化(框架专家 / 可靠性 ×2 / YAGNI)→ 代码级根因验证。
**产出**:1 必做(heartbeat cycle-lock,correctness bug)+ 1 评估(triage 质量)+ 砍/defer 清单。

## 2. Loop Engineering 论点

2026 范式:从"prompt 单 agent"转向"设计编排 agent 随时间运行的控制系统"。Anthropic 的 Boris Cherny(Claude Code lead)定义自己的工作为"写外部执行 loop"。核心等式:

```
AI Agent = LLM + Instructions + Tools + State + Loop
```

**kunglao 已是此范式**:v1.9 把 notification-driven(被动等人戳)改成 convergence-driven(每 tick 机械检查 open claim + 自派发)。"傻等"老毛病修掉 = 跨 8 会话 / 6 workspace 研究的根因治愈。

## 3. 三框架整合

### 3.1 LangChain 4 层 loop 栈

| Loop | 作用 | 影响 |
|---|---|---|
| L1 agent | model 调工具直到任务完成 | 自动化工作 |
| L2 verification | grader 按 rubric 检查,失败带反馈重试 | 保证质量 |
| L3 event-driven | 事件(cron/webhook)触发 agent run | 规模化自动 |
| L4 hill-climbing | 生产 trace → 分析 agent → 改 harness 配置 | harness 自改进 |

关键论断:"focus should pivot to loops 3 and 4 where value compounds."(注意:此论断隐含 SaaS 规模前提,见 §5.3 裁决)

### 3.2 DSD 10 模式(三档)

- **基础(1-4)**:ReAct / Reflection / Tool Use / Prompt Chaining
- **实践(5-7)**:Ralph(外部 validator 退出,Claude Code `/goal` 即此)/ Evaluator-Optimizer / Multi-Agent Supervisor
- **生产加固(8-10)**:Circuit Breaker / Heartbeat / Bounded Execution + Context Engineering

DSD 原话:patterns 8-10 "non-negotiable once a loop runs autonomously in production."

### 3.3 cobusgreyling repo(工程落地版)

5 building block + Memory/State,loop anatomy:`Schedule → Triage → R/W STATE → Isolated Worktree → Implementer Sub-agent → Verifier Sub-agent → MCP/Git/Tickets → Human Gate → Commit/PR OR Escalate`。
工具:`loop-audit`(就绪分)/ `loop-sync`(STATE↔LOOP drift)/ `loop-context`(memory + circuit breaker)。
7 pattern(PR Babysitter / CI Sweeper / ...)是 coding-workflow 专用,不直接映射 RE,但"异步观察 + 对过程结果反应"的结构原则可迁移(kunglao worker 监控同构)。

### 3.4 三框架关系

LangChain = 概念栈(讲清 4 层);DSD = 模式分类(讲清每层可选模式 + 失败模式);cobusgreyling = 工程积木(讲清落地 block + 工具)。三者互补。kunglao 评估三者并用。

## 4. kunglao 主 loop 成熟度对照

### 4.1 building block 全具备(cobusgreyling 框架)

| block | kunglao |
|---|---|
| Automations/Scheduling | heartbeat_loop_prompt + CronCreate /loop |
| Worktrees | §1d.1 worker 独立 worktree |
| Skills | kunglao-agent + sub-skills + references/ |
| Plugins/MCP | ghidra / x64dbg / frida |
| Sub-agents | worker + kunglao-redteam BLIND(v1.9.22 forward-derive) |
| Memory/State | claim-register + digest + ledger + loop-state |

### 4.2 loop 栈 / 模式成熟度

| 层/模式 | kunglao | 状态 | 证据 |
|---|---|---|---|
| L1 agent | worker dispatch(maker) | ✅ | kunglao-worker |
| L2 verification | redteam BLIND + doubt_checker + verify | ✅ 强 | v1.9.22 forward-derive |
| L3 event-driven | heartbeat + CronCreate + worker_pulse | ✅ | v1.9.28 |
| **L4 hill-climbing** | 跨 run 不学习 | ❌ | 无 trace→harness 反馈环 |
| 模式 5 Ralph | CONVERGED=claim 清零 + convergence_check 机械执行 | ✅ | 框架专家纠正:机械退出 = 强 Ralph(原评 ⚠️ 偏保守);"问对问题集"隐患属 L4 不属 Ralph |
| 模式 6 evaluator-optimizer | redteam 独立 evaluator | ✅ | — |
| 模式 7 supervisor | orchestrator | ✅ | — |
| 模式 8 circuit breaker | backtrack/active_intervention/convergence_health(SPINNING) | ⚠️ | 3 gate 未用失败场景验过;SPINNING `_dedup_consecutive` 误折 flatline(代码 L98-101 自警) |
| 模式 9 heartbeat | .heartbeat.json + reconcile | ⚠️ | **设计层 bug — 见 §6** |
| 模式 10 bounded + context | digest 已建未接冷启动 | ⚠️ | Opus 1M 下非瓶颈(defer) |

**结论**:loop 骨架与"理想 loop"同构,5 block 齐全。改进点是**生产就绪度**(尤其模式 9 的活 bug),不是架构重写。

## 5. 多视角细化(4 subagent)

### 5.1 强共识:heartbeat 是唯一真 correctness bug

3 个 agent 独立定位(可靠性 ×2 + YAGNI),代码级证据见 §6。本次会话 STALE=5267min 拦截 2 次 subagent 派发 = 活症状。

### 5.2 砍(与已有机制重叠 90%+)

| 原提案 | 砍因 | 已有机制 |
|---|---|---|
| loop-audit | 95% 改名 | `acceptance_check.py`(oracle/CLI/VoI/digest/test-suite 5 条 binary gate) |
| STATE↔契约 drift | 90% 重叠 | `plan_drift_detector.py`(5 类 drift)+ v1.9.18 `--reconcile` |
| hill-climbing L4 | SaaS 规模论据,单用户 ROI 负 | 无(failure-registry 数据量不足以喂 L4) |

### 5.3 冲突裁决

- **L4 优先级**:框架专家主 #2(LangChain "value compounds")vs YAGNI 砍(SaaS fantasy)。**裁决:YAGNI 对**——LangChain 论断隐含多用户高频 run 前提;kunglao 单用户偶尔跑样本,L4 defer。
- **digest 接冷启动**:YAGNI 指出 76K→38K 在 1M Opus context = 3.8% vs 7.6%,非瓶颈。**defer**(Haiku 撞墙才值)。
- **模式 5 Ralph**:框架专家纠正 ✅(§4.2 已采纳)。

### 5.4 框架专家补的盲点:triage 质量(见 §7)

`convergence_check` + `priority_ratio` 是 L3 最高杠杆决策点("现在派哪个 claim"),但全研究对其**排序质量**沉默——只评估了"有没有这机制",没评估"排得对不对"。独立评估缺口。

## 6. heartbeat bug 根因分析(细化到代码级)

### 6.1 症状(活证据)

本会话 2026-08-10:派 subagent 时 `worker_budget.py` 两次 REJECT——`heartbeat STALE (5267 min > 35) — cron not ticking`。`runs/.heartbeat.json` 实测 `last_tick_ts == started_ts == 01:49:56Z`(注册后 cron tick 从未 fire),`activity_ts` 字段缺失(hook 从未执行过)。这不是新故障,是 v1.9.12/13/18/25/26/28/36 反复"心跳停了"的同一根因。

### 6.2 根因(代码级,5 条)

**RC1 语义分裂不一致(设计层,最深)** — `hooks/heartbeat_touch.py` docstring 自述 E2.3 语义分裂:`tick_ts`(cron only,**gates** 35-min check)vs `activity_ts`(any tool,**observation only**)。但 `worker_budget.py::check_heartbeat_alive` L530 `data.get('last_tick_ts', '')` 只读 `last_tick_ts`,**从不读 `activity_ts`**。hook bump 的字段 gate 不读 → bump 对 gate 完全无效。v1.9.36 的"decouple liveness from cognition"实际上 decouple 错了字段:它把 liveness 信号(`activity_ts`)标成 observation-only,却让 gate 继续依赖 cognition(cron tick)。**fix 没修 gate**。

**RC2 setdefault 假象** — `heartbeat_touch.py` 的 `data.setdefault("last_tick_ts", data["activity_ts"])` 注释"legacy readers",但 `setdefault` 在 key 已存在时是 **no-op**;`--heartbeat-on` 注册后 `last_tick_ts` 永远存在 → 这行永远不改 `last_tick_ts`。代码"看起来"在同步两字段,实际从不执行。

**RC3 bare write_text 竞态** — `heartbeat_touch.py` 用 `hb.write_text(json.dumps(data))`,**非** `_atomic_write`(tmp→rename)。orchestrator + N 个 worker subagent 的每次 Bash/Read/Write/Edit/Agent 都触发此 hook → 多进程并发 read-modify-write 同一 `.heartbeat.json` → 经典竞态 → 某 writer 的更新静默丢失。

**RC4 无 cycle-in-progress 锁** — `heartbeat_tick.py` 不检查"上一个 tick 是否还在跑"。两 cron tick 重叠 → 同时执行 `_reconcile_workers` → 同时重写 `analysis_state.txt [active_workers]` 段 → `worker_budget::pre_check` 读 `[active_workers]` 判 ≤3 时可能读到旧值 → **WORKER_CAP=3 不变量被绕过**(可能派发第 4 个 worker)。`_atomic_write` 只保证单次 write 原子,不保证 read-compute-write 序列串行化。

**RC5 cron session-only(平台限制)** — `/loop` cron job 不跨会话持久。新会话不注册 cron → `last_tick_ts` 永不更新 → gate STALE。v1.9.28 引入 gate 本意"强制 orchestrator 注册 /loop",但平台限制使这成为周期性自伤。

### 6.3 级联失败模式

`last_tick_ts` STALE → dispatch gate 拒绝一切 → ledger 不更新 → `convergence_health` 读 stale trajectory → false SPINNING/STALLED → orchestrator panic-dispatch 或完全停摆。SPINNING 的 `_dedup_consecutive`(L98-101)误折真实 flatline → 假收敛 → 无界烧钱(最危险,持续静默)。

### 6.4 历史定位

v1.9.12/13/18/25/26 都报"心跳停了";每次修法不同(register cron / wire-up hook / reconcile workers),根因未触。v1.9.28 加 dispatch gate(强制 heartbeat 活);v1.9.36 加 `heartbeat_touch`(bump activity_ts)。**v1.9.36 的修法最接近,但因 RC1(语义分裂)未真正生效**。本会话 STALE=5267 = 此路径实证。

### 6.5 修复设计(代码级,实现就绪)

| # | 修法 | 改动点 | 性质 |
|---|---|---|---|
| **F1** | gate 改读 `activity_ts`(或 `max(last_tick_ts, activity_ts)`) | `worker_budget.py::check_heartbeat_alive` L530 | **核心** — 真正修掉 STALE 假阳性;liveness = tool activity,不依赖 cron cognition |
| F2 | `heartbeat_touch` 用 `_atomic_write` 替 bare `write_text` | `heartbeat_touch.py` | 消除 RC3 竞态 |
| F3 | `heartbeat_tick` 加 cycle-in-progress 锁(`fcntl.flock` on `.heartbeat.lock` 或 PID file) | `heartbeat_tick.py` | 消除 RC4 重叠 tick |
| F4(可选) | `/loop` 注册检查从 dispatch gate 拆出,改 advisory warning(不 block) | `worker_budget.py` | 解 RC5 平台限制卡生产 |

**F1 是核心**:语义对齐——gate 的目的是"orchestrator session 活着吗",而 tool activity(`activity_ts`)是比 cron tick 更直接、更不易假阴性的 liveness 信号(cron tick 本身就由 orchestrator session 驱动)。把 `/loop 注册` 拆成 advisory(F4)即可保留"提醒注册 cron"的原意,不拿它卡 dispatch。

### 6.6 TDD 清单(F1+F2)

- RED1:模拟 orchestrator busy(cron 不 tick)但 tool 活跃 → 当前 gate STALE 拒绝(错);F1 后 alive(对)。
- RED2:4 进程并发写 `.heartbeat.json` → 无更新丢失(F2 原子写)。
- RED3:回归 —— cron 正常 tick 时 gate 仍 alive(不破坏正路径)。

## 7. triage 质量评估计划(框架专家补的盲点,细化)

### 7.1 为什么 triage 是 L3 最高杠杆点

`convergence_check` 决定 DISPATCH 后,`priority_ratio`(VoI `[0.45L+0.30D+0.25N]/cost`,issue #2)排序决定**派哪个 claim**。排序错 = 在低价值 claim 上烧 token、高价值 claim 排队。每 tick 最高杠杆决策,但全研究只评估了"有这机制",没评"排得对不对"。

### 7.2 评估什么

- **价值序符合率**:历史样本上,`priority_ratio` 给的排序 vs "实际最先解决"的符合率(plan §2.2 G2 原指标 ≥70%)。这是 **E4.1 deferred 项的具体化**。
- **C-401≠C-402 类判别**:同分退化是否破除(issue #2 有回归测试,缺真实样本验证)。
- **explore→exploit 切换**:`explore_gate`(verified facts < 5 → cheapness 铺开)的阈值 5 是否合理。

### 7.3 方法

取 3-5 个历史样本(malware-analysis-workspace 的 progress.txt + ledger 有 claim 解决顺序),回放 `priority_ratio` 输出,算与真实序的 Spearman 或 top-3 符合率。如实报告,不为达标改排序/挑样本(plan §2.3 约束)。

### 7.4 产出

`tools/measure_value_order.py` + `runs/triage-quality-<ws>.json`。这不是改码,是**度量**——给 G2 一个真实数字,而非"感觉变好了"。

## 8. 次级风险(记录,不进必做)

- **SPINNING `_dedup_consecutive` 误折 flatline**(`convergence_health.py` L98-101 自警)→ 假收敛 → 无界烧钱。最危险(持续静默)。缓解:§6.5 F1 修好 heartbeat 后,stale trajectory 输入减少,间接降低此风险。
- **mtime 作 liveness signal 在 Windows + git worktree + antivirus 三重干扰下不可靠**:antivirus 刷新 mtime → 假活跃(stuck worker 永不检出);git checkout reset mtime → 假僵尸(活跃 worker 被 reconcile 清掉,facts 丢失)。`_reconcile_workers` / `_scan_active_workers` 依赖 mtime。长期改:加 content-hash 或显式 worker heartbeat。
- **3 PENDING gate 未用失败场景验过**:backtrack/active_intervention/troubleshooting 是 soft constraint(orchestrator 须"记得"调,未 wire 进 settings hooks)。单用户偶发场景 marginal risk 可接受 → defer。

## 9. 最终结论与改进优先级

| 序 | 项 | 性质 | 决策 | 实现 |
|---|---|---|---|---|
| **1** | heartbeat F1+F2(gate 读 activity_ts + 原子写) | correctness bug(活症状) | **必做** | §6.5,小聚焦 PR |
| 2 | triage 质量度量(E4.1 具体化) | 评估盲点 | 做 | §7,不改码只度量 |
| — | heartbeat F3(cycle-lock) | 防重叠 tick | 可选 | RC4,若 F1 后仍见重叠 |
| — | heartbeat F4(/loop advisory) | 解平台限制 | 可选 | RC5 |
| — | digest 接冷启动 | 效率(Opus 1M 非瓶颈) | defer | Haiku 撞墙再做 |
| — | 3 PENDING gate 失败场景验证 | 软约束 | defer | 单用户风险可接受 |
| — | SPINNING flatline 误折 / mtime liveness | 次级风险 | 记录 | F1 间接缓解;长期 content-hash |
| 砍 | loop-audit / loop-sync drift / hill-climbing L4 | 重叠 / SaaS 规模 | 不做 | §5.2 |

**0 项全做不会崩**:`acceptance_check` 守 build、`convergence_health` 守 spin、`plan_drift_detector` 守 drift,175 tests green。**但 heartbeat F1 是活症状(本会话实测 2 次 dispatch 被拦),是细化唯一产出的必做项**——它是 correctness bug,不是增强。

## 10. 源

- [The Art of Loop Engineering — LangChain 2026-06](https://www.langchain.com/blog/the-art-of-loop-engineering)
- [10 Loop Engineering Design Patterns — DataScienceDojo 2026](https://datasciencedojo.com/blog/loop-engineering-design-patterns/)
- [cobusgreyling/loop-engineering — GitHub](https://github.com/cobusgreyling/loop-engineering)
- [LEAF Architecture Pattern — ResearchGate](https://www.researchgate.net/publication/408733345)
- [Autonomous Agentic Event-Driven Systems — Confluent](https://www.confluent.io/blog/autonomous-agentic-event-driven-systems-architecture/)
- 代码证据:`hooks/heartbeat_touch.py` / `hooks/worker_budget.py::check_heartbeat_alive` L505-559 / `scripts/heartbeat_tick.py` / `scripts/hook_activation.py`
