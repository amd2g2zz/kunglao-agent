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

---

## 7. 多 subagent 细化结论(2026-08-10,4 agent 讨论)

派 4 个 subagent(框架专家 / 可靠性 ×2 / YAGNI 怀疑者;RE 域 agent 被 heartbeat gate 拦未补, skeptic 兼盖规模论据)。结论**取代 §4 原 5 项优先级**。

### 7.1 强共识:heartbeat cycle-lock 是唯一真 bug

3 个 agent 独立得出:
- `heartbeat_touch.py` 用 bare `write_text`(非 `_atomic_write`),4 进程(orchestrator + 3 worker)并发 read-modify-write 同一 `.heartbeat.json`,无 flock/PID/cycle flag → 经典竞态 → 写丢失。
- hook bump `activity_ts`,但 `check_heartbeat_alive()` 只读 `last_tick_ts`——**两字段从不交叉**。`--heartbeat-on` 后 `setdefault("last_tick_ts")` 永远 no-op。
- 本次会话 STALE=5267min 拦截 = 此路径的**活症状**,非理论风险。
- `heartbeat_tick.py` 不检查"上 tick 在跑";两 cron tick 重叠 → 同时 reconcile `analysis_state.txt [active_workers]` → dispatch gate 读旧值 → **WORKER_CAP=3 不变量被绕过**。
- 这是 v1.9.12/13/18/25/26 "心跳停了"反复症状的新变体(机制从 cron-未注册 → 并发写丢失/双轨不交叉)。

### 7.2 砍(与已有机制重叠)

| 原项 | 砍因 | 已有机制 |
|---|---|---|
| #2 loop-audit | 95% 改名,§5 自己承认"升级 acceptance 成仪表盘" | acceptance_check.py(5 条 binary gate) |
| #5 STATE↔契约 drift | 90% 重叠,僵尸 active_workers 已被 v1.9.18 修 | plan_drift_detector.py(5 类 drift)+ --reconcile |
| #3 hill-climbing L4 | LangChain"pivot to L4"是 SaaS 规模论据;单用户偶尔跑样本 ROI 负 | 无(新概念但规模不值) |

### 7.3 冲突裁决

- **L4 优先级**:框架专家主张 #2(LangChain"value compounds")vs skeptic 砍(SaaS-scale fantasy)。**裁决:skeptic 对**——kunglao 单用户偶尔跑样本,failure-registry 数据量不足以喂 L4,L4 defer。
- **digest 接冷启动**:skeptic 指出 76K→38K 在 1M Opus context 是 3.8% vs 7.6%,非瓶颈。**defer**(Haiku 频繁撞墙才值)。
- **模式 5 Ralph**:框架专家纠正——CONVERGED=claim 清零 + convergence_check 机械执行 = 强 Ralph(退出由机械检查器定,非自报),**应 ✅**;"问对问题集"隐患是 L4 问题不是 Ralph 语义。

### 7.4 细化后优先级(取代 §4)

| 序 | 项 | 性质 | 决策 |
|---|---|---|---|
| **1** | heartbeat cycle-lock + last_tick_ts/activity_ts 双轨合一 | correctness bug(活症状) | **必做** |
| 2 | triage 质量评估(convergence_check claim 排序/槽位) | 评估盲点(框架专家补) | 做(评估非改码) |
| — | digest 接冷启动 | 效率非瓶颈(Opus 1M) | defer |
| — | 3 PENDING gate 失败场景验证 | 软约束 | defer(单用户风险可接受) |
| 砍 | loop-audit / loop-sync / hill-climbing | 重叠 / SaaS 规模 | 不做 |

### 7.5 被低估的次级风险(reliability#2 补)

- SPINNING gate `_dedup_consecutive` 误折真实 flatline(代码 L98-101 自警)→ 假收敛 → 无界烧钱。
- Windows + git worktree + antivirus 三重干扰下 mtime 作 liveness signal 不可靠(antivirus 刷新 mtime → 假活跃;git checkout reset mtime → 假僵尸,正在写的 facts 丢失)。
- heartbeat STALE 级联:block dispatch → ledger 不更新 → convergence_health 读 stale trajectory → false SPINNING → panic-dispatch → 更多无效 token。

### 7.6 0 项全做会崩吗

不会。acceptance_check 守 build、convergence_health 守 spin、plan_drift_detector 守 drift;175 tests green。**但 heartbeat 双轨 bug 是活症状(本会话实测),应单独立项修——这是 §4→§7 细化唯一产出的必做项。**
