# Loop Engineering — 调研整合与 kunglao 主 loop 评估

> 2026-08-10 整合两轮调研(LangChain/DSD + cobusgreyling repo),评估 kunglao-agent 主 loop 的成熟度与改进点。
> 不是一个待实现的 spec,是**研究落盘 + 决策记录**。VoI 打分调研已落 design-spec §3.2;本文件补 loop 层。

## 0. 源

- [The Art of Loop Engineering — LangChain 2026-06](https://www.langchain.com/blog/the-art-of-loop-engineering) — 4 层 loop 栈
- [10 Loop Engineering Design Patterns — DataScienceDojo 2026](https://datasciencedojo.com/blog/loop-engineering-design-patterns/) — 10 模式分类法
- [cobusgreyling/loop-engineering — GitHub](https://github.com/cobusgreyling/loop-engineering) — 生产工具 + 7 pattern + 5 building block(CLAI CLI)
- [LEAF Architecture Pattern — ResearchGate](https://www.researchgate.net/publication/408733345) — 学术 taxonomy
- [Autonomous Agentic Event-Driven Systems — Confluent](https://www.confluent.io/blog/autonomous-agentic-event-driven-systems-architecture/) — closed-loop control

## 1. 论点:Stop prompting. Design the loop.

Loop engineering 是 2026 范式:从"prompt 单个 agent"转向"设计编排 agent 随时间运行的控制系统"。Anthropic 的 Boris Cherny(Claude Code lead)把自己的工作定义成"写外部执行 loop"。核心等式(Anthropic 11 页 PDF):

```
AI Agent = LLM + Instructions + Tools + State + Loop
```

kunglao 已是此范式(v1.9 convergence-driven 取代 notification-driven,"傻等"老毛病修掉了)。

## 2. 三个框架

### 2.1 LangChain 4 层 loop 栈

| Loop | 作用 | 影响 |
|---|---|---|
| L1 agent loop | model 调工具直到任务完成 | 自动化工作 |
| L2 verification loop | grader 按 rubric 检查,失败带反馈重试 | 保证质量 |
| L3 event-driven loop | 事件(cron/webhook/事件)触发 agent run | 规模化自动 |
| L4 hill-climbing loop | 生产 trace 喂分析 agent → 改 harness 配置 | **harness 自改进** |

关键论断:"focus should pivot to loops 3 and 4 where value compounds."

### 2.2 DSD 10 模式(三档)

- **基础(1-4)**:ReAct / Reflection / Tool Use / Prompt Chaining
- **实践(5-7)**:Ralph(外部 validator 退出,/goal 即此)/ Evaluator-Optimizer / Multi-Agent Supervisor
- **生产加固(8-10)**:Circuit Breaker / Heartbeat / Bounded Execution + Context Engineering

DSD 原话:patterns 8-10 "non-negotiable once a loop runs autonomously in production."

### 2.3 cobusgreyling repo(工程落地版)

5 building block + Memory:
- Automations/Scheduling(节奏触发)
- Worktrees(隔离并行)
- Skills(项目知识持久)
- Plugins & Connectors(MCP)
- Sub-agents(maker/checker)
- **+ Memory/State(durable spine,对话外)**

loop anatomy:
```
Schedule → Triage → R/W STATE → Isolated Worktree →
Implementer Sub-agent → Verifier Sub-agent → MCP/Git/Tickets → Human Gate → Commit/PR OR Escalate
```

工具:`loop-audit`(就绪分)/ `loop-sync`(STATE↔LOOP drift)/ `loop-context`(memory+circuit breaker)/ `loop-cost` / `loop-worktree`。
7 pattern(PR Babysitter / CI Sweeper / ...)是 **coding-workflow** 专用,不映射 RE。

## 3. kunglao 主 loop 对照

### 3.1 building block(全部具备 ✓)

| block | kunglao |
|---|---|
| Automations/Scheduling | heartbeat_loop_prompt + CronCreate /loop ✓ |
| Worktrees | §1d.1 worker 独立 worktree ✓ |
| Skills | kunglao-agent + sub-skills + references/ ✓ |
| Plugins/MCP | ghidra/x64dbg/frida ✓ |
| Sub-agents | worker + kunglao-redteam BLIND(v1.9.22) ✓ |
| Memory/State | claim-register + digest + ledger + loop-state ✓ |

### 3.2 loop 栈 / 模式成熟度

| 层/模式 | kunglao | 状态 |
|---|---|---|
| L1 agent | worker dispatch | ✅ |
| L2 verification | redteam BLIND + doubt_checker + verify | ✅ 强 |
| L3 event-driven | heartbeat + CronCreate + worker_pulse | ✅(v1.9.28) |
| **L4 hill-climbing** | 跨 run 不学习 | ❌ **缺** |
| 模式 5 Ralph | CONVERGED=claim 清零(非"检查全绿") | ⚠️ 退出语义偏 |
| 模式 6 evaluator-optimizer | redteam 独立 evaluator | ✅ |
| 模式 7 supervisor | orchestrator | ✅ |
| 模式 8 circuit breaker | backtrack/active_intervention/convergence_health(SPINNING) | ⚠️ **3 gate PENDING**(未用失败场景验过) |
| 模式 9 heartbeat | .heartbeat.json + reconcile | ⚠️ **缺 cycle-in-progress 锁**(DSD 点名 top 失效模式) |
| 模式 10 bounded + context | digest 已建 **未接冷启动** | ❌ **digest 闲置** |

**结论:loop 骨架与 cobusgreyling "理想 loop"几乎同构,5 block 齐全。改进点是生产就绪度,不是架构重写。**

## 4. 改进优先级(融合三框架,ROI 排序)

| # | 项 | 框架出处 | ROI 理由 |
|---|---|---|---|
| 1 | **digest 接冷启动**(模式 10 接线) | DSD 10 | 机制全在(#3 已建),只差 wire;冷启动 76K→≤38K 可测 |
| 2 | **`loop-audit` readiness check** | cobusgreyling | 把 acceptance(#6)升级成 loop 就绪度评分,量化跟踪本表缺口 |
| 3 | **hill-climbing loop**(L4) | LangChain | 最大复利;最小起步:run debrief → 写回 failure-registry → 下轮 digest sec_e 带上 |
| 4 | **circuit breaker 验证 + heartbeat cycle-lock**(模式 8/9) | DSD | 3 PENDING gate 用失败场景验 + heartbeat 加 cycle mutex 防重叠 tick |
| 5 | **`loop-sync` STATE↔契约 drift** | cobusgreyling | 运行时 state ↔ SKILL.md 契约一致性(抓僵尸 active_workers 那类漂移) |

附:kunglao.py 现为 Phase 3 subcommand 路由,按 L3 应为事件驱动 loop 入口(= #5 deferred 的 loop-entry 重构,与范式一致)。

## 5. 决策

- **做**:1、2、4(生产就绪度,可量化,风险低)。3 视下轮预算(范式跃迁,工作量最大)。5 长期。
- **不做**:照搬 cobusgreyling 7 pattern(coding-workflow 专用,不映射 RE);重写 loop 架构(已同构)。
- **升级 acceptance**(#6 的 acceptance_check.py)成 loop-audit(项 2),作为本表的进度仪表盘。

## 6. 与现有重构文档的关系

- `design-spec.md` §3.2 — VoI 打分(已落,本文件是其 loop 层补充)
- `design-spec.md` §3.6 — digest 算法(项 1 接线的目标)
- `refactor-plan.md` 阶段 6/7 — digest/eval 已合 dev(本文件项 1/2 是其后续 wire-up)
- `references/convergence-loop.md` — v1.9 convergence 行为(本文件评估的对象)
