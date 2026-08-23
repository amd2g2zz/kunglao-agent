# Design — decision-loop value teeth (#496)

## 问题边界

"价值上牙" = 让 #499 裁决的权威 scorer(priority_ratio)的排名与 #495 的
类型化失败事实在**不可绕过的执行点**产生约束力。落点是两条既有执行面:

- `hooks/dispatch_gate.py`(Agent 工具 PreToolUse,激活 TTL 内不可忽略)
  — 承接 ① top-1 强制与 ②(a) 能力看牌 REJECT;
- `scripts/priority_ratio.py` 的 EvidenceView 输入侧 — 承接 ② 的事实消费
  与 ③ 的 strategy novelty。

**不是**本变更(范围外):
- 不改 `failure_analysis_gate.py` 的记录面(#495 已定,三产物字段、升格
  协议、`analyses/failure-*.yaml` 文件形状都冻结 — 本设计只**读**它);
- 不建完整 attempt 价值树(③ 只留 `[strategy <id>]` 标记接口);
- 不动 `worker_budget.check_priority` 的签名/语义(dispatch_gate **复用**
  它作为唯一排名源 — 两 hook 对 top-1 的判定永不分歧);
- 不动 worker_budget 的 `devreason` 门(`reasoning:` 标记属于那条 hook 链
  的既有纪律;本变更在 dispatch_gate 链引入 `agent-reasoning:`,与 #310
  agenttype-deviation 同名同形)。

## D1. top-1 强制(agenttype-deviation 模式的精确复制)

复制的结构(#310 `check_agent_type` + `_reject`):

| 面 | agenttype(#310 既有) | top1(#496 新) |
|---|---|---|
| 判定源 | `route_capability.recommend_agent_type` | `worker_budget.check_priority(...)[2]` (deviated) |
| REJECT 条件 | 派发 agent != 推荐 且无 `agent-reasoning:` | 派发 claim != ratio top-1(rank≥2)且无 `agent-reasoning:` |
| 错误文本 | `specialist-first violation (#310): ...` | `REJECT top1: dispatched <C> rank #N ...` |
| 日志 | stderr `AGENTTYPE (deviation recorded): ...` | stderr `TOP1 (deviation recorded): ...` + `kunglao_log.emit` |
| exit | 2(stderr + hookSpecificOutput.additionalContext 修正指引) | 2(同构) |

关键决策:

1. **单一排名源**: dispatch_gate 调 `worker_budget.check_priority(reg,
   deps, task_spec, cid, ws)` — 与 worker_budget devreason 审计同一函数、
   同一 failure-blocked 预过滤、同一 RETRACTED 过滤。两个 hook 对"谁是
   top-1"永不给出不同答案(否则 orchestrator 收到互相矛盾的 REJECT)。
2. **rank-None 不 REJECT**: 派发目标不在可派发集(被 deps/promotion 卡、
   或 failure-blocked)→ check_priority 返回 ADVISORY(deviated=False)→
   dispatch_gate 仅 stderr 透传。failure-blocked 切片由 #495 的注入路径
   负责(先记录三产物),不叠加新 REJECT — 与 worker_budget 的 devreason
   只在 deviated=True 时 REJECT 完全对齐。
3. **留痕走统一日志**: `self_redirects.jsonl` 是 #447 的 ask-back **违规**
   计数器(3 次/小时强制 pause),写入合法偏差会污染 pause 语义 → 留痕走
   既有统一事件日志 `kunglao_log.emit(ws, 'hook:dispatch_gate',
   'priority_deviation', claim, detail)`(#459 目标面,#461 dispatch 事件
   同款),stderr 同步打 `TOP1 (deviation recorded)`。
4. **FAIL_OPEN**: check_priority 不可 import、register 缺失、actions 为空
   → 静默放行(坏门不得阻塞派发 — 与 agenttype FAIL_OPEN 同 philosophy)。

## D2. ②(a) 能力看牌(消费 validated_capability)

**数据面**(EvidenceView 输入侧,纯读取):

```python
EvidenceView.validated_capabilities: tuple[tuple[str, str], ...]  # (claim_id, text)
EvidenceView.identified_obstacles:     tuple[tuple[str, str], ...]  # (claim_id, text)
```

`from_workspace` 扫 `analyses/failure-*.yaml`(逐文件 try/except,坏文件
fail-open 跳过),收集非空 `validated_capability` / `identified_obstacle`。
每 claim 一个文件、record 覆写 → 文件内容即"最新 analysis"。

**判定面**(纯函数,零 LLM):

```python
TOOL_FAMILIES  # token -> family 词表: frida/rev-frida->frida, xposed->xposed,
               # ghidra->ghidra, x64dbg->x64dbg, ida->ida, volatility->volatility,
               # vmr-shell/vmrun->vm, qiling/malware-framework->qiling
tool_families_from_tools(tools)   # 声明工具名(协议结构字段)按部件匹配
tool_families_from_text(text)     # 能力文本(自由文本,唯一可用通道)按词边界匹配
capability_switch_violation(claim_ids, dispatch_tools, prompt_text, evidence) -> dict | None
```

冲突判据(全部机械,无自然语言推断):

```
cap_fams  = families(validated_capability of claim_ids 的最新 analysis)
disp_fams = families(派发协议声明的 tools)
冲突 iff cap_fams ≠ ∅ ∧ disp_fams ≠ ∅ ∧ cap_fams ∩ disp_fams = ∅
       ∧ prompt 无 capability-disproof: <family>(named ∩ cap_fams ≠ ∅)
```

- **claim 作用域 + 障碍父链**: dispatch_gate 解析目标 claim 的
  `obstacle_for`(若有)→ claim_ids = {目标, 父}。轨迹1 的换工具转向若
  落在升格出的障碍 claim 上,同样被父链上的能力约束拦住。
- **逃逸是声明不是推断**(#447 doctrine): `capability-disproof: frida
  (spawn path timed out — injection itself was validated)` — 命名被证伪的
  工具族即放行并留痕。失败记录里本来就有障碍证据,标记只是强制 orchestrator
  **出示**它(看牌纪律),不是新增举证负担。
- **fail-open 三处**: 能力文本不含已知工具族(T1 静态能力不约束 T2 工具
  选择)、派发未声明任何已知族、无该 claim 的 analysis → 无约束。
- **执行点**: dispatch_gate REJECT(`REJECT capability` + 修正指引 +
  exit 2);带标记放行 + `kunglao_log.emit(action='capability_switch')`。
  不进 check_priority(issue 验收写明 REJECT;ADVISORY 是弱化)。

## D3. ②(b) 障碍 leverage(钉住,不改评分核)

#495 升格协议写出的边:`claim_deps.depends_on[obstacle] = [failed_claim]`,
obstacle claim OPEN、继承父的 `answers_question`。ratio 的既有机制:

- **L 侧(自然消费,平铺 DAG 可观察)**: `_reverse_deps` 把该边翻成
  `rev_deps[failed] = [obstacle]`;`lev_raw[failed]` 计入该 OPEN 下游 →
  平铺 DAG(deps 全空,人人 L=0)在升格后 max_lev=1、父 claim L=1.0、
  排名跃居 top-1。"打障碍解锁父"的价值即父 claim 分数上升。
- **D 侧(解锁后自然消费)**: 父 claim 终结后 obstacle 过候选过滤
  (depends_on 全 terminal),继承的 `answers_question` → D=0.5(无此继承
  的普通 claim D=0.2)。

结论: **零代码改动,双测试钉住**(防止后续重构悄悄丢掉):
`test_obstacle_promotion_raises_parent_leverage_flat_dag`(经
`record_analysis` 真实升格后重排名)与
`test_obstacle_claim_discriminator_consumes_inherited_answers_question`。

## D4. ③ strategy novelty(最小接口)

- **写面**(dispatch_gate 放行路径): prompt 含
  `\[strategy\s+([A-Za-z0-9._-]+)\]` → 追加
  `runs/strategy-log.jsonl` 一行
  `{"ts", "event": "dispatch", "strategy", "claim", "attempts_at_snapshot"}`
  (attempts 取 claim-register 的当前 promotion_attempts;fail-open)。
- **读面**(EvidenceView): `strategy_failures: dict[str, int]` +
  `claim_strategy: dict[str, str]`。失败判定**不新增写者**: dispatch 行
  的 `attempts_at_snapshot=n` 在该 claim 的 analysis `covers_attempt>n`
  时计一次同 strategy 失败(attempts 语义使时间戳多余: 派发后新失败必然
  重录 analysis 且 covers 递增)。
- **消费面**(priority_ratio): 候选 claim 的 N 按
  `fact_counts[cat] + strategy_failures[strategy(claim)]` 计 — 同一打法
  历史失败越多,新颖度越低,排名越靠后。无标记/无日志 → N 不变
  (**不强制使用**,行为向后兼容)。

## D5. 验收 → 测试映射(tests/test_decision_teeth.py)

| #496 验收 | 测试 |
|---|---|
| 派非 top-1 无理由 → REJECT | `test_dispatch_rank2_without_reasoning_rejected` |
| 带 agent-reasoning → 放行留痕 | `test_dispatch_rank2_with_agent_reasoning_passes_and_logs` |
| top-1 派发静默 | `test_dispatch_top1_silent` |
| failure-blocked 切片不被新门劫持 | `test_failure_blocked_claim_keeps_guidance_path` |
| 能力✓在手换工具 → REJECT | `test_capability_switch_rejected` |
| capability-disproof 出示 → 放行 | `test_capability_switch_with_disproof_passes` |
| 障碍 claim 继承父能力上下文 | `test_obstacle_claim_inherits_parent_capability_context` |
| 纯函数判据(同族/未知族/无能力 fail-open) | `TestCapabilitySwitchJudgment` 5 例 |
| 障碍升格 leverage 生效(平铺 DAG) | `test_obstacle_promotion_raises_parent_leverage_flat_dag`(PIN) |
| 继承 answers_question 进 D | `test_obstacle_claim_discriminator_consumes_inherited_answers_question`(PIN) |
| strategy 失败计数进 novelty | `test_strategy_failures_lower_novelty` / `test_claim_without_strategy_unchanged` |
| gate 记 dispatch 行 | `test_strategy_dispatch_row_logged_by_gate` |

负例(轨迹重演单元级): rank-3 无理由被拦 = top1 REJECT;换工具被拦 =
capability REJECT(先证伪);6 次无信息转向的等价类 = 每次
`agent-reasoning`/`capability-disproof` 留痕进统一日志(事后可审计)。

## Rejected

- **R1 在 check_priority 里内联排名逻辑**: dispatch_gate 自己 load
  register+deps+evidence 再调 `_ratio_rank` 会复制 failure-blocked /
  RETRACTED 过滤 = 第二表示;复用 `check_priority` 是唯一排名源。
- **R2 把留痕写 self_redirects.jsonl**: 那是 ask-back 违规计数器(3 次/时
  强制 pause),合法偏差写入会污染 pause 语义;统一日志
  `kunglao_log.emit` 是既有等价日志(#459/#461 已用)。
- **R3 让 dispatch_gate 在 rank-None 时也 REJECT**: deps-blocked /
  failure-blocked 派发已有各自的面(plan 纪律、#495 注入);top-1 门只管
  "可派发集内的排序偏离",越界即与 worker_budget devreason 语义分叉。
- **R4 改 obstacle 升格的边方向让障碍 claim 立即可派发**: #495 的记录面
  冻结(obstacle depends_on 失败 claim);改方向 = 改记录面,且"先关父再
  打障碍"的时序语义由 next_method 纪律承接,不是 ratio 的职责。
- **R5 strategy 失败判定新增写者(analysis 里加 strategy 字段)**: 又是
  记录面改动;attempts 快照 + 既有 covers_attempt 的单调性已足够推导,
  零新增协议字段。
