# kunglao-agent v2.0 工程设计规格书(修订版)

> **HISTORICAL (2026-08-11)**: 本文档写成时名为 `kong-agent`;技能已更名为 `kunglao-agent`,本文档中的 `kong.py` / `lib_kong.py` 等名称均为历史设计引用,不是当前代码。当前实现见 `scripts/kunglao*.py` + `scripts/hook_activation.py`。此档案仅用于追溯设计意图。

> 修订: 恢复 kong-redteam 对抗验证(修订前被弱化) + 新增 subskill 拆分(用户纠正: 拆分=拆 subskills, 非代码收敛)
> 修订 2026-08-06: 方法路由 → 资源选择层(kong-select CLI)+ 反馈闭环 + resource-registry 动态注册(8 → 9 CLI)
> 配套: kong-agent-refactor-plan.md(目标与验收)

---

# 一、系统架构总览

## 1.1 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         M5 MONITOR (tick)                           │
│   heartbeat二分 · loop_state对账 · convergence_health │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ 每 tick(5min, cron) 或事件驱动
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         M1 DECIDE                                   │
│   convergence矩阵 · priority比值键 · action排序 · 探索阶段           │
│   输出: {decision, top_actions[], blocked[], drifts[]}              │
└───────────────┬──────────────────────────────────┬──────────────────┘
                │ dispatch(机械门)                  │
                ▼                                  ▼
┌─────────────────────────┐        ┌──────────────────────────────────┐
│  M2 ACT (hook层)        │        │  M3 VERIFY (双层 + 对抗)         │
│  worker_budget 8项检查  │        │  L1 机械重跑 → L2 kong-redteam   │
│  dispatch_gate 注入     │        │  (攻击性对抗: 独立推导+多路径)    │
└─────────────┬───────────┘        └────────────┬─────────────────────┘
              │ worker 完成                      │ verified fact
              ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         M4 RECORD                                   │
│   ledger.jsonl 幂等写入 · reconciler回放旧通道 · claim状态迁移        │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         M0 状态层(单一事实源)                        │
│   claim-register.yaml(人类可审) · loop-state.json(机器) ·            │
│   digest.md(工作记忆) · ledger.jsonl(事件账本) · facts/(产物)        │
└─────────────────────────────────────────────────────────────────────┘
```

## 1.2 组件清单

| 组件 | 职责 | 替代的旧脚本 | 状态 |
|---|---|---|---|
| `kong.py` | 编排原子入口(每 tick 自动循环, 非子命令) | 31 个 CLI 的循环调用 | Phase 3 部分 |
| `kong-decide` | 决策/排序/资源选择(独立 CLI)【修订 2026-08-06】 | convergence_check+priority+failure_gate(scan) | ⏳ |
| `kong-select` | 资源选择(独立 CLI: 多路召回+融合排序+组合选择+反馈更新)【修订 2026-08-06 新增】 | 无(新增) | ⏳ |
| `kong-verify` | 验证(独立 CLI, L1 机械 + L2 redteam 派发) | blind_gate+normalize_trace+content_hash | ⏳ |
| `kong-record` | 记账(独立 CLI, ledger 幂等) | update_index+reconcile_intents+progress_report | ⏳ |
| `kong-monitor` | 对账/健康(独立 CLI) | heartbeat_tick+convergence_health | ⏳ |
| `kong-digest` | digest 机械生成(独立 CLI) | 无(新增) | ⏳ |
| `kong-init` | 初始化(独立 CLI, 防二次, §6.7) | Phase 0 手动 | ⏳ |
| `kong-eval` | 评测(独立 CLI, 三臂) | 无(新增) | ⏳ |
| `loop_state.py` | TEMP mtime → loop-state.json 对账 | 3 账本 | ✅ E2.1/E2.2 |
| `lib_kong.py` | workspace 解析/DISPATCH_RE/激活检查 | 三处复制 | ✅ E2.4 |
| `heartbeat_touch.py` | activity_ts 观察(语义二分) | 旧 last_tick_ts 污染 | ✅ E2.3 |
| `worker_budget.py` | M2 机械门(8 项) | 保留 | 保留 |

---

# 二、kong-agent 拆分(代码层 31 → 5+1)

## 2.1 拆分原则

1. **按认知相位拆**,不按痛点拆(旧模式的病根)
2. **每模块单一职责**,输入/输出契约冻结(worker_pulse 解析的 JSON 不许变)
3. **状态只经 M0 读写**,模块间不直接改对方状态
4. **决策权边界硬编码**:机械 8 项在脚本, LLM 6 项在接缝, 用户 5 项留人

## 2.2 模块-脚本映射(31 → 5+1)

| 模块 | 合并的旧脚本 | 职责边界 |
|---|---|---|
| **M0 状态层** | claim-register.yaml(不变) + loop-state.json(新) + digest.md(新) + ledger.jsonl(新) | 唯一状态读写口; 其他模块不得自研状态逻辑 |
| **M1 DECIDE** | convergence_check + priority + failure_analysis_gate(scan) + claim_expiry + plan_drift_detector + ask_for_direction(selfcheck) | 该不该派 / 派哪个 claim / 该 claim 内哪个 action |
| **M2 ACT** | worker_budget + dispatch_gate(注入) + worker_pulse(通知) | 机械执行门(≤3 worker/tier/VM-only/self-cap/heartbeat/自提升防) |
| **M3 VERIFY** | blind_gate + normalize_trace + content_hash + **kong-redteam(对抗)** + verify-note 契约 | L1 机械重跑 → **L2 kong-redteam 攻击性对抗验证**(§3.4) |
| **M4 RECORD** | update_index + reconcile_intents + stale_blocker_prune + progress_report + claim 状态迁移 | ledger 写入(幂等); 状态迁移; summary_of_work 聚合 |
| **M5 MONITOR** | heartbeat_tick + heartbeat_loop_prompt + hooks_selfcheck + hook_activation + active_intervention + backtrack_gate + convergence_health | tick 原子入口; 心跳/对账/卡死检测/健康 |

## 2.3 删除/保留裁决(基于真实代码核实)

- **删除 3**(✅ 已删): checkpoint / progress / git_checkpoint(零契约引用)
- **保留改语义 1**(✅): heartbeat_touch(activity_ts)
- **保留 hook 2**: worker_budget / worker_pulse(机械门 + 完成通知)
- **保留为库 4**: content_hash / normalize_trace / update_index / reconcile_intents(M3/M4 内部函数)
- **转 worker 库 1**: complete_teardown 的 5 个 operator(修 maker-checker 边界)
- **合并 12**: 见 §2.2 映射

---

# 三、核心算法设计

## 3.1 认知循环主循环(tick → decide → act → verify → record)

```
算法: 主循环(tick 驱动)
输入: workspace
每 tick(5min, cron 或 worker 完成事件触发):
  1. MONITOR:  heartbeat-check(查 tick_ts, 35min 门)
               loop_state.reconcile(TEMP mtime → loop-state.json)
               convergence_health(HEALTHY/STALLED/SPINNING)
  2. DECIDE:   decision = convergence_matrix(open, partial, free_slots, blocked)
               if DISPATCH:
                 actions = priority_ratio(claims, deps, evidence)   # §3.2
                 top = top_k(actions, k=free_slots)                  # k=worker 槽位
                 top = select_resources(top)                         # 资源选择层(kong-select)【修订 2026-08-06】
                 dispatch(top)                                       # M2 门检查
               if DISPATCH_VERIFIER: dispatch verifier(top partials)
  3. ACT:      worker 执行(M2 机械门保证约束)
  4. worker 完成事件:
               M4.record(ledger, worker_result)                      # 幂等
               M3.verify(fact)                                       # §3.4 双层+对抗
               M1.re_decide(evidence_updated)                        # 自适应重排
  5. 收敛判定:  if CONVERGED AND active_workers==0 AND partial==0:
                 §6.3 checklist 全绿 → 宣告完成
                 else: 继续(排空闸)
```

**复杂度**:每 tick O(open_claims × deps),无 LLM 调用(除接缝)。符合"DECIDE 必须便宜"铁律。

## 3.2 动作选择算法(比值键 + 自适应重排 + 探索)

```
算法: priority_ratio(claims, deps, evidence)
输入: claims(claim-register), deps(claim_deps), evidence(facts/_INDEX + ledger)
输出: 排序后的 actions 列表

1. 探索阶段判定:
   if verified_fact_count < EXPLORE_THRESHOLD:      # 早期全低价值
     return sort_by(actions, key=cheapness)          # T1 优先铺开
   
2. 对每个可执行 action a(依赖满足 + tier 允许):【修订 2026-08-06 算法定稿】
   L(a) = leverage(a, deps)      # |下游 OPEN claim| / |下游最大| (claim_deps 反边); claim 有 terminal fact → L=0
   D(a) = discriminator(a)       # 结构字段: 活 competitor_group=1.0 / answers_question=0.5 / else=0.2
   N(a) = novelty(a, evidence)   # 1 − min(1, 该证据区已产 fact 数 / k), k=EXPLORE_BASE
   score(a) = [0.45·L + 0.30·D + 0.25·N] / cost(a)   # 比值键, 纯机械, 零 LLM 调用
   cost(a)  = TIER_COST[tier(a)] # {T1:1, T2:3, T3:10}  [修正 2026-08-06: 原 NEXT_TIER_CHEAP 反向]
   
3. 排序: actions.sort(by=score, desc); 同分(ε)取 cost 小者(机械裁决, 不问 LLM)
4. 返回 top_k(actions, k=free_slots)

每轮自适应重排: 证据 ledger 变化(claim 状态/事实落盘)时触发本算法重算。
低价值不删: 全保留排序, 只降序(预算内尽量做)。
```

**理论锚**:子模下贪心 (1-1/e)≈63.2% 是可达最优上界(Feige 1998);含依赖全局最优 NP-hard(Lín 2013);比值排序在条件独立假设下精确最优(Breese & Heckerman);探索阶段对应 EcoFuzz exploration 三态机。**【修订 2026-08-06 价值口径定稿】**: 本算法是 **VoI(Value of Information)的廉价实现** —— L=图论信息增益、D=假设空间收窄、N=覆盖熵代理、C=成本分母;正式定义 `VoI(a)=ΣP(outcome|a)·ΔH/C(a)`,现无 hypothesis tracker(每 claim 无 P(h))故用结构代理。**打分者 = 机械函数,LLM 永不进分数**: LLM 只在 claim-seed(写假设/判别组)与结果(写 fact)两个接缝出现;其"语义重要性"判断因 full-state 退化(C-401=C-402=0.696 实测同分)被排除。权重 (0.45/0.30/0.25) 为起点值,需 3-5 历史 claim 回放标定(阶段 7 harness 内)。

**[修订 2026-08-06] 选择层**: 动作选定后由**资源选择层**选资源(skill/tools/MCP/scripts, 详见 §4.2): 多路召回(嵌入 bge-m3, 本地 ollama 已验证 5/6 + 关键词 + 资源描述 三路融合)→ 排序 → top-k → **组合选择**(一个分析任务可能需多资源按依赖序配合, 如 C2 提取 = ghidra 静态反编译 → frida 动态 hook → floss 字符串)→ 派发。选择器是**机械多路召回**, 不是手写 rulebase(领域举例如 JNI 只是示例, 不是规则)。

**[修订 2026-08-06] 反馈层**: agent 选到资源成功/失败, 路由必须知道——落地为**消费已有 fact/verify/ledger 结果**(读盘观察执行结果, 不拦截调用; 吸收 Nginx 式代理"统计成败"的思想, 但不引入代理层——RE 工具是长驻进程非 HTTP 后端, 代理架构错配)。成功 + 研究兜底发现新资源 → 增量注册固化; 失败 → 该资源降权 + 换 top-2(熔断); 长期成功率数据累积 → 自学习后置层(详见 §6.8 反馈闭环)。

## 3.3 状态对账算法(loop_state)

```
算法: reconcile(workspace)
输入: TEMP/claude/*/*/tasks/*.output(stat-only, 不读内容)
输出: runs/loop-state.json(派生视图)

1. glob TEMP/claude/*/*/tasks/*.output
2. 对每个文件: stat(mtime, size); 解析 project/session/agent_id
3. age = now - mtime
   if age < ACTIVE_WINDOW(30min): 记入 agents{}
   active = agents where age < STALE_MIN(20min)
   stale  = agents where age >= STALE_MIN
4. 写 loop-state.json = {ts, agent_count, active[], stale[], agents{}}
5. 对比上次快照: 生成 NEW/GONE/STALE 事件 → .agent-events.jsonl
```

**关键**:worker-status 文件**不是**机器状态源(实验证实自由格式);TEMP mtime 是权威信号(598/598 可解析, 0.1min vs 12987min 分界)。loop-state 是**派生视图**,每 tick 再生, 从不写回 subagent 契约。

## 3.4 验证算法(双层门禁 + kong-redteam 对抗验证)【修订: 恢复对抗层】

```
算法: verify(fact)
输入: fact(Fxxx.md 含 reproduce/expected) + fixture
输出: {fact_id, verdict, expected, actual_sha256, cmd} → runs/verify-<ts>.json

L1 机械层(优先, 确定性):
  cmd = parse_reproduce(fact)
  actual = run(cmd)                        # 只读 grep/python/xxd(放行名单)
  actual_sha = sha256(actual)
  verdict = (actual_sha == expected_sha) ? PASS : FAIL
  if verdict == FAIL: return FAIL          # 不进入 L2

L2 kong-redteam 对抗层(每个 maker claim 必过, 不得跳过):
  dispatch kong-redteam subagent(独立进程, 无 maker 上下文)
  硬约束(agent 定义):
    a. BLIND — 不看目标 claim 的 facts/F<NNN>-*.md / notes/ / worker-status / plan
       只读 facts/_INDEX(列表) + sample binary + fixtures + evidence/*.txt
    b. 独立推导 — 从原始 artifact 跑自己的命令(xxd/python/pefile/capstone)
    c. 先陈述自己的发现, orchestrator 后对比 — pass 仅 exact match
    d. 每个分歧报 DIFF(即使小数字差异)
    e. 攻击五角度: 方法盲区 / 替代解释 / 外推 / 自洽性 / 负结果过度
    f. plan-to-execute — 先写 runs/plan-redteam-<target>.md
    g. self-consistency — 关键数字用 ≥2 不同方法推导, 多数表决:
       ≥2 paths 支持 → CONFIRMED; ≥2 反驳 → REFUTED; 分裂 → UNVERIFIED-WITH-GAP
  输出: RED-TEAM VERDICT (CONFIRMED / REFUTED / UNVERIFIED-WITH-GAP) + GAPs

  裁决: orchestrator 比较 — CONFIRMED → claim 可升 PROVEN
        REFUTED/UNVERIFIED-WITH-GAP → claim 不升, 回 maker 修正或 DEFER
  "A red-team pass that confirms everything is a pass; a pass that finds a hole
   is a better pass."(maker-checker §1b/§6.3: maker 自签是 STAMP 不是 PROVEN)

锚定条款: PASS 必须带 anchors(原始字节位置 + 复现命令 + expected/actual)
无锚不提升; 与 handoff-check.py --anchors 数字保真门禁打通。
```

## 3.5 记账算法(ledger)

```
算法: record(event)
输入: {source_module, event_type, payload}
输出: ledger.jsonl 追加(幂等)

1. event_id = sha256(json(event_type + payload))    # 去重键
2. 原子写: 写 temp → rename(事务性, 崩溃安全)
3. 幂等: 同 event_id 重复 → 返回已有 seq, 不重复落盘
4. event_type 枚举: fact_written/fact_verified/claim_promoted/
                    claim_refuted/failure_recorded/intent_opened/intent_closed
5. 保留 maker_module 字段 → 跨模块 maker-checker 审计链

状态迁移(Expand→Migrate→Contract):
  Expand: 账本旁路写入, 31 CLI 照旧
  Migrate: reconciler 把账本回放为 progress.txt/analysis_state.txt append,
           连续 N=3 轮 checksum 零漂移 → 读者切账本
  Contract: 旧通道降级只读
```

## 3.6 digest 生成算法(机械, 无 LLM)

```
算法: build_digest(workspace)
输出: runs/digest.md(2-4KB)

head:   schema 版本 + anchor 版本号(条目变更 +1) + reconciliation 时间戳
sec_a:  task_spec 主问题/约束(3-5 行)
sec_b:  claims 索引: C-NN | status | 一句话结论 | 锚点(file:line)
sec_c:  verified facts: F-NN | boundary_type | conclusion | unit=口径(数字保真)
sec_d:  架构性结论: 家族/执行链/C2(保留推理链, 不压成单句)
sec_e:  失败规则: WHEN X THEN 禁止/必须 + 证据锚(结构化, 非自由文本)
sec_f:  指针表: progress.txt/claim-register/facts 路径(按需读)

注入顺序: 新条目在前(位置偏置规避: Lost in the Middle 20+pp)
数字保真: facts 的 unit 字段原样带入; digest 跑 handoff-check.py --anchors
完整性:  新增 verified fact 必须 1 轮内进 digest, 否则 FAIL(防 extraction gap)
```

## 3.7 heartbeat 算法(语义二分)

```
算法: heartbeat(workspace)
.tick_ts:    仅 cron 驱动的 heartbeat_tick 写(证明监控循环在跑)
.activity_ts: 任何工具调用写(heartbeat_touch, 观察仅供诊断)
35-min 门:   只查 tick_ts(worker_budget.check_heartbeat_alive)
             tick_ts 陈旧 → REJECT dispatch(监控失效可检出)
             activity_ts 新但 tick_ts 旧 → 门触发(修复 v1.9.28/36 自矛盾)
```

## 3.8 收敛算法(排空闸)

```
算法: convergence(workspace)
CONVERGED 判定: open==0 AND partial==0 AND active_workers==0
                AND 无 verify_status: pending
违反 → premature-convergence 告警, 强制进入 §6.3 checklist 循环:
  ① verifier 签收全部(kong-redteam 全过)② notes 覆盖 ③ verdict 重评
  ④ 报告写出 ⑤ 动态验证考虑
每项打勾才允许 CONVERGED(修 10 个 CONVERGED-w>0 的过早收敛事故)
```

---

# 四、模块详细设计

## 4.1 M0 状态层

**数据结构**:
```
claim-register.yaml:  claims[].{id,status,boundary_type,evidence_tier_attempted,
                               promotion_attempts,depends_on,method_trail[]}
loop-state.json:      {ts, source, agent_count, active[], stale[], agents{}}
digest.md:            六节(§3.6)
ledger.jsonl:         {seq, event_id, source_module, event_type, payload, checksum}
facts/_INDEX.md:      F-NN | status | claim_id | conclusion(产物索引)
```

**读写契约**:所有模块经 lib_kong 的原子读写函数; worker 不直接写 claim 状态(自提升被 claim-status guard 拦); digest 只由脚本写(schema 化, 无自由文本注入位)。

## 4.2 M1 DECIDE

**输入**: loop-state.json + claim-register + facts/_INDEX + ledger + resource-registry.yaml【修订 2026-08-06: method-graph → resource-registry】
**输出**: {decision, exit_code, top_actions[], blocked[], failure_blocked[], stale[], drifts[], selfcheck}
**接口**(独立 CLI, 非子命令):
```
python kong-decide <ws> [--json]      # 决策/排序/资源选择(输出契约冻结)
python kong-monitor <ws>              # 对账/健康(独立 CLI)
```
**状态机**:
```
DECIDE 输出 → DISPATCH(有 open + 槽) | DISPATCH_VERIFIER(partial + 槽)
           | SATURATED(open 无槽) | BLOCKED(全 blocked) | CONVERGED(无 open/partial)
```
**[修订 2026-08-06] 资源选择层(替代原"方法路由(Dijkstra)")**: kong-decide 内部先 select(action) 走资源选择层:
```
1. 多路召回: 嵌入(bge-m3, 本地 ollama, 已验证 5/6)+ 关键词 + 资源描述 三路融合
   ——机械选择器, 不是手写 rulebase(JNI 等只是领域举例, 不是规则)
2. LLM 推荐路【修订 2026-08-06 新增】: 机械路低置信/模糊任务/组合需求时, 把任务 + 资源清单给 LLM,
   LLM 返回推荐 top-N + 组合(依赖序)+ 理由; 推荐了本地没有的资源 → 记录"能力缺口"→ 触发发现/固化
   ——按需触发(低置信才走), 不是每次路由都调 LLM(成本控制)
3. 排序 → top-k(综合代价排序, 参考"高德最短≠最省时"; LLM 路参与融合)
4. 组合选择: 一个 action 可需多资源按依赖序配合(如 C2 提取 = ghidra 静态 → frida 动态 → floss 字符串),
   按 resource-registry 的 depends_on 组合派发
5. 失败降级(保留 self-healing 思想): top-1 失败 → 用 top-2(熔断); 连续失败 → 降权
```
**错误处理**:任何脚本异常 → 记录 ledger(failure_recorded) + 不阻塞循环(侧通道语义)。

## 4.3 M2 ACT(hook 层)

**8 项机械检查**(worker_budget.pre_check): workers≤3 / promotion cap / tools allowed / host-forbidden / deadline / tier gate / self-cap / heartbeat alive。
**注入**: dispatch_gate 对 failure-blocked claim 注入 corrective guidance(非硬 abort)。
**完成通知**: worker_pulse(PostToolUse) → 触发 M1 重排 + 补位。

## 4.4 M3 VERIFY(双层 + 对抗)【修订: kong-redteam 恢复】

**接口**(独立 CLI, 非子命令):
```
python kong-verify <ws> <fact_id|note> [--lane <lane>] [--json]
```
**两阶段**:
- L1 机械层: 重跑 reproduce + 字节比对(确定性, 无 LLM)
- L2 kong-redteam 对抗层: 每个 maker claim 必过(§3.4 全约束)

**lane 管理**: 从 claim-register refutability path 构造 fact 依赖 DAG; 无共享上游的 fact 批并行(≤3 lane); 共享证据的 fact 同 lane 串行(前序 PASS 才派后继)。
**预算**: 每 fact ≤10-15K tokens; 同 artifact 前缀复用 prompt cache(90% 输入节省)。
**错误处理**: 任一 FAIL → 驳回重派; 超轮数/超时/工具错误 → 机械采集进 failure-registry。

**重要**: kong-redteam 是**独立 subagent**(无 maker 上下文), 不是 M3 内部函数——它是 M3 的"外部对抗审计员", 通过 orchestrator 派发, 盲验证硬约束由 agent 定义强制执行。

## 4.5 M4 RECORD

**接口**(独立 CLI, 非子命令):
```
python kong-record <ws> --event <json>   # ledger 幂等写入
```
**summary_of_work 契约**(worker 返回): {topic, conclusion, evidence_pointers, open_questions}(1,000-2,000 tokens), digest 只聚合这些。
**provenance**: 落盘含 env/命令/输出证据, 审计 agent 声称与实际一致。

## 4.6 M5 MONITOR + 编排原子入口

**接口**(独立 CLI, 非子命令):
```
python kong.py <ws>       # 编排原子入口(每 tick 自动循环: monitor→decide→dispatch→verify→record)
python kong-monitor <ws>  # 独立 CLI: 对账/健康(可单独调试)
```
**kong.py <ws> 内部自动循环**(不靠 LLM 记步骤):
```
1. 自动检测该做什么(机械):
   - 有活跃 worker? → 对账 + 健康 + 处理完成
   - 无活跃 + 有 open? → decide + 资源选择(kong-select) + dispatch(内部路由到现有资源)【修订 2026-08-06】
   - 有 partial? → verify(内部派发 kong-redteam)
   - 全 done? → 收敛判定 + §6.3 checklist
2. 输出: 一句话状态 + 下一步建议(LLM 只读这一行)
```
**tick 步骤**: heartbeat-check → loop_state.reconcile → active_intervention(help_request 响应检查)→ backtrack_gate(卡死检测)→ convergence_health。
**心跳语义**: tick_ts(cron 证明)/ activity_ts(观察), 门只查 tick_ts(§3.7)。

---

# 五、工程设计

## 5.1 数据流时序(端到端)

```
t=0    cron tick → M5: heartbeat/对账/健康 → M1: decide=DISPATCH(C-001, action=C2提取)
t=1    M2 门检查通过 → dispatch worker(C-001) → worker 写 worker-status + 产出
t=2    worker 完成事件 → M4 record(ledger) → M3 verify(F-001)
t=2.5  L1 机械重跑 PASS → L2 kong-redteam 对抗(独立推导 + 多路径) → CONFIRMED
t=3    M1 重排(证据更新) → 下一 action/claim → 循环
t=N    open=0, partial=0, workers=0 → CONVERGED → §6.3 checklist → 宣告完成
```

## 5.2 并发模型

- **worker 并发**: ≤3(worker_budget 机械门); 但资源感知——VM 通道独立信号量(=1), tier-3 同时只 1 个, 其余槽跑 tier-1/2 采集(把等待变工作)
- **验证 lane**: 与主 worker 并发(不同 fact 独立验证); **kong-redteam 与 maker 完全隔离**(无共享上下文)
- **补位节拍**: 完成事件驱动(主)+ 5min tick 兜底; 派发冷却 60s 防忙等
- **不采用**: worker 自助取活(反模式, Celery prefetch 教训)、并行化推理链(错误传播 + 上下文碎片)

## 5.3 错误处理分级

| 级别 | 错误 | 处理 |
|---|---|---|
| L0 机械 | 脚本异常 | 记录 ledger, 不阻塞循环(侧通道) |
| L1 工具 | MCP 失败/VM 掉线 | 同 MCP 换模式 → 读 setup.sh → 派 env-fix worker |
| L2 推理 | 失败归因 | failure_analysis_gate 三问(LLM 诊断, 门禁机械) |
| L3 挂死 | BP flood/VM wedged | 中途停止保存部分证据 + 记录(非成本门) |
| L4 用户 | B2 stop/task_spec/收敛签核 | 用户 5 项决策权 |

## 5.4 部署与迁移

- **开发**: worktree `kong-refactor` 分支(生产不动)
- **验收**: 每阶段判据过 → commit(带实验证据)
- **上线**: 全部阶段完成 + 端到端验收过 → 合入生产(git merge)
- **回滚**: 每阶段 revert 对应 commit; 状态文件 git tag + 快照(阶段 0 起)
- **旧 CLI**: 迁移期间保留为只读代理, 全部验证完成才删

## 5.5 配置

```
task_spec.yaml:  primary_questions / scope / constraints / depth / success_criteria
resource-registry.yaml: 资源条目(skill/tool/MCP/script) + description + 关键词 + 评分 + 依赖序   【修订 2026-08-06: method-space → resource-registry】
failure-registry.yaml: WHEN X THEN 禁止/必须 + 证据锚 + 可采纳性状态
explore_threshold:  脚本常量(verified_fact_count 低于此 → 探索阶段)
next_tier_cheap:    {T1:1.0, T2:0.5, T3:0.2}(成本分母)
```

## 5.6 测试策略(三层)

1. **回归层**: F1-F18 29/29 + 行为快照 10/10 + 24/24 smoke(每次 commit 全绿)
2. **等价层**: 迁移前后同 fixture 逐字节 diff(worker_pulse 契约保护)
3. **评测层**: eval_harness 三臂 A/B/C + 故障注入 + 防污染(每个阶段后)

---

# 六、系统能力定位(事实版: 不拆, 只路由)

## 6.1 前提: 已存在的组件盘点(2026-08-06 实测)

```
~/.claude/skills/ 分析侧已存在:
  ghidra-malware/ ghidra-re/     反编译
  rev-frida/ rev-idapython/ rev-unicorn-debug/ rev-struct/ rev-symbol/  动态/结构
  js-obfuscated-deobf/ js-reverse-ops/         JS 逆向
  cti-expert/ cti-linkage-false-positive-check/  CTI
  mal-recon/ malware-framework/   框架
  anysearch/ defuddle/ jina-reader/  检索
  hr-report/ hr-report-pro/       报告
  vmr-shell/                      VM 控制

~/.claude/agents/ 已存在:
  kong-worker(通用 maker 骨架) / kong-redteam(对抗 checker) /
  ghidra-light / floss-filter / pefile-signature / go-symbols /
  verdict-scorer

另: .mcp.json mcpServers(ghidra/frida/virustotal/volatility/x64dbg...)+ scripts/ 亦为资源注册来源【修订 2026-08-06】
```

## 6.2 核心结论: 不需要拆任何新 subskill

**kong-agent 的问题不是"缺 subskill", 是"缺资源选择层"。**【修订 2026-08-06】 分析能力全部已存在(独立 skill), 编排组件(kong-worker/kong-redteam)已存在。重构 = 编排内核 + 资源选择层(kong-select)+ 反馈闭环 + 补评测, 不是拆新 skill。

## 6.3 组件定位(基于事实)

| 组件 | 角色 | 状态 |
|---|---|---|
| **kong-agent**(主) | 编排循环骨架 | 已存在, 重构(kong.py) |
| **kong-worker**(maker) | 通用 claim 执行骨架 | 已存在, **加资源选择(kong-select)**【修订 2026-08-06】 |
| **kong-redteam**(checker) | 对抗验证 | 已存在, 保持 |
| **现有分析 skill** | 工具能力库(worker 路由到) | 已存在, 保持 |
| **kong.py + 子命令** | 编排机械内核 | 重构中 |
| **kong-eval** | 评测(真正缺) | 新增 |

## 6.4 kong-worker 的角色: maker 骨架 + 路由

```
kong-worker(maker 骨架, 已存在)
  ├── 读 claim + task_spec + digest(M0)
  ├── 按 kong-select 推荐(resource-registry.yaml)→ 加载对应资源(ghidra-re/rev-frida/...)【修订 2026-08-06】
  ├── 执行 → 产证据 → 写 fact
  └── 返回 summary_of_work(结构化)
```

**kong-worker 需要加的能力**【修订 2026-08-06】: 消费 kong-select 的选择结果 → 选对资源(不是自己实现分析, 是路由到现成能力)。

## 6.5 资源注册表 resource-registry.yaml(要建的, 不是新 skill)【修订 2026-08-06: method-graph → resource-registry】

```
resource-registry.yaml(条目 = 现有 skill/tool/MCP/script, 由注册器扫描真实环境生成, 不写死)
  注册来源(§7 动态注册): ~/.claude/skills/* + ~/.claude/agents/* + .mcp.json mcpServers + scripts/
  条目字段: id / kind(skill|tool|mcp|script) / description / keywords[] /
            score{success_rate, fail_count, last_result} / depends_on[]
  示例条目:
    ghidra-re  kind=skill  desc=静态反编译       keywords=[静态, decompile, Ghidra]  score{1.0, 0, ok}
    rev-frida  kind=skill  desc=动态 hook        keywords=[动态, hook, Frida]        score{0.9, 1, ok}
    floss      kind=skill  desc=字符串提取       keywords=[字符串, floss]             score{0.8, 0, ok}
  组合: C2 配置提取 = [ghidra-re → rev-frida → floss](按 depends_on 依赖序, 静态先行)
失败 → 该资源降权 + 换 top-2(熔断, 见 §6.8 反馈闭环)
覆盖缺失 → LLM escalation + 反馈固化(增量注册)
```

## 6.6 编排侧不拆 skill(子命令替代)

kong-monitor/decide/verify/memory **留在主 kong-agent 作为 kong.py 子命令**(每 tick 一起触发 + 共享循环上下文, 拆成独立 skill = 忘记加载的别名)。模块化在代码层(31→5+1), 不在 skill 层。

## 6.7 新增清单(真正缺的, 全部独立 CLI)

### 1. resource-registry.yaml(资源注册表)【修订 2026-08-06: method-graph → resource-registry】
```
resource-registry.yaml(条目 = 现有 skill/tool/MCP/script, 注册器扫描生成, 不写死)
  注册来源: ~/.claude/skills/* + ~/.claude/agents/* + mcpServers + scripts/
  条目字段: id / kind / description / keywords[] / score{success_rate, fail_count, last_result} / depends_on[]
  组合: C2 配置提取 = [ghidra-re → rev-frida → floss](依赖序)
失败 → 该资源降权 + 换 top-2(熔断, §6.8)
覆盖缺失 → LLM escalation + 反馈固化(增量注册)
```
消费方: kong-worker(路由到现有资源)+ kong-decide(资源选择)。

### 2. kong-worker 路由能力
kong-worker(已存在)加: 读 resource-registry.yaml / kong-select 输出 → 选对资源(小改动)。【修订 2026-08-06】

### 3. kong-init(独立 CLI, 防二次初始化)【修订: 从可选项升为明确新增】

**核心问题**: 冷启动跑一次, 防二次初始化三类事故——覆盖已有分析 / 重复激活 hook / 重复 seed claims。

**三阶段防重**:
```
python kong-init <ws> [--force]
阶段 1 存在性检查(不写):
  if analysis_state.txt 存在 AND [initialized] 段 = true:
    → 已初始化 → 幂等续接(不重建, 不覆盖)
    → 只读当前状态 + 报告"已初始化于 <ts>, 续接模式"
  else: → 全新初始化 → 继续

阶段 2 初始化(仅全新):
  a. workspace scaffold(目录骨架 + state 文件 + facts/_INDEX)
  b. sample mount + sha256 校验
  c. task_spec intake(首次, 允许问用户)
  d. seed claims(primary_questions → PRIMARY claims)
  e. hooks 部署(wire-up, 幂等: 只补缺失, 不全量覆写)
  f. 资源注册器: 扫描 ~/.claude/skills/ + mcpServers + scripts/ → 生成 resource-registry.yaml(动态, 不写死)【修订 2026-08-06】
  g. 写 [initialized] 标记

阶段 3 幂等校验:
  重跑 → 检测 [initialized] 标记 → 续接模式(不重建)
  --force 才允许重建(且先备份旧状态)
```

**[initialized] 标记**(防重锚):
```
analysis_state.txt 的 [initialized] 段:
[initialized]
  ts: <ISO UTC>
  ws: <workspace path>
  skill_version: <kong-agent version>
  sample_sha256: <校验过的样本哈希>
  state_hash: <claim-register/facts 的状态哈希, 检测后续漂移>
[/initialized]
```
**state_hash 作用**: 不只防重, 还防"初始化后状态被外部改了"——重跑时 hash 不匹配 → 警告(不是静默续接)。

**hook 部署防重**:
```
先读 settings.json 现有 hooks 段
幂等: 已有 heartbeat_touch/worker_budget/dispatch_gate/worker_pulse → 不重复加
只补缺失的(不全量覆写 —— settings 重写擦除 hook 是反复事故)
写后 hooks_selfcheck 验证(project=OK, user=OK)
```

**涉及的配置**: .claude/settings.json(hooks 段)/ runs/.heartbeat.json(注册)/ runs/.hook_state.json(激活)/ analysis_state.txt([initialized] 标记)/ claim-register.yaml(seed claims 仅首次)

**验证实验**:
```
E-init.1 防重: 连续跑 2 次 → 第 2 次续接模式(不重建, 无重复 seed)
E-init.2 幂等: 重跑后 hooks 不重复注册(hooks_selfcheck project=OK, 无重复条目)
E-init.3 漂移检测: 初始化后改 claim-register → 重跑 hash 不匹配 → 警告
E-init.4 恢复: 已初始化 workspace 新会话 → 续接(不覆盖已有分析)
```

### 4. kong-eval(独立 CLI, 评测, 真正缺)
```
python kong-eval <ws> [--arm A|B|C] [--inject <type>] [--seed <n>]
三臂 A/B/C 预注册 + 故障注入 + 防污染(§P4.5)
```

### 5. 编排侧独立 CLI 汇总(9 个, 非子命令)【修订 2026-08-06: 8 → 9, 加 kong-select】
```
python kong.py <ws>               # 编排原子入口(每 tick 自动循环)
python kong-decide <ws>           # 决策/排序/资源选择
python kong-verify <ws> <fact>    # 验证(L1 + redteam 派发)
python kong-record <ws> --event   # 记账(幂等)
python kong-monitor <ws>          # 对账/健康
python kong-digest <ws>           # digest 机械生成
python kong-init <ws>             # 初始化(防二次 + 资源注册器)
python kong-eval <ws>             # 评测(三臂)
python kong-select <ws> <task>    # 资源选择(多路召回 + 组合排序 + 反馈更新)
```
**原则**: 每个独立 CLI 单一职责, 可独立调用/测试; 不共享 argparse 入口(不是子命令); 内部仍按 M0-M5 模块化。kong.py 是唯一编排入口, 其余是按需显式调用的独立工具。

### 6. kong-select(独立 CLI, 资源选择层)【修订 2026-08-06: 新增, 8 → 9 CLI】
```
python kong-select <ws> <task> [--top-k N] [--json]
输入: task(action/claim 描述) + resource-registry.yaml + 执行结果(fact/verify/ledger)
输出: {task, resources: [{id, kind, score}], combos: [{seq: [ids], order: 依赖序}]}

职责(单一, 机械低频纯逻辑, 最低成本——不做成 skill/MCP):
  1. 多路召回: 嵌入(bge-m3, 本地 ollama; 不可用则降级 关键词+description 两路)+ 关键词 + description 融合
  2. LLM 推荐路【修订 2026-08-06 新增】: 机械路低置信(融合分 < 阈值)/模糊任务/组合需求 → LLM 看任务+资源清单,
     返回推荐 top-N + 组合(依赖序)+ 理由; 推荐本地没有的资源 → gap 信号(与 5 衔接)
  3. 排序 → top-k(综合代价; LLM 路参与融合)
  4. 组合: 按 depends_on 依赖序拼装多资源(C2 提取 = ghidra → frida → floss)
  5. 反馈更新: 读 fact/verify/ledger 更新评分(成功 → 固化; 失败 → 降权 + top-2 熔断)
  6. 缺口上报: 无匹配 → 输出 gap 信号 → LLM escalation + 成功后增量注册
```
消费方: kong-decide(派发前选资源)+ kong-worker(加载资源)。

## 6.8 反馈闭环(新增)【修订 2026-08-06】

**问题**: agent 选到资源成功/失败, 路由必须知道——否则 top-k 排序永远是无反馈的静态排序, 资源库不会生长。

**落地**: 消费已有 fact/verify/ledger 结果(**读盘观察执行结果, 不拦截调用**; 吸收 Nginx 式代理"统计成败"的思想, 但不引入代理拦截层——RE 工具是长驻进程非 HTTP 后端, 代理架构错配)。

**数据流**:
```
资源执行 → fact/verify/ledger 落盘 → feedback_updater 读结果(kong-select 反馈更新)
  ├─ 成功 + 研究兜底发现新资源 → 增量注册进 resource-registry(固化, 下次可选)
  ├─ 失败 → 该资源降权(fail_count++, success_rate 重算)+ 换 top-2(熔断)
  └─ 长期: 成功率数据累积 → 自学习后置层(SkillWeaver 式技能合成, 独立模块,
     路由发现覆盖缺口时触发; 本阶段只留接口)
```

**触发条件**:
1. 研究兜底: 资源覆盖缺失 → LLM escalation → 找到新资源
2. 找到 + 成功 → 固化(增量注册)
3. 失败 → 降权熔断

**数据源**: fact(成功产物)/ verify(验证通过/驳回)/ ledger(failure_recorded / fact_verified 事件)——全部是已有落盘结果, 无新增拦截点。

---

# 七、验收与依赖

| 阶段 | 服务目标 | 完成判据 | 依赖 |
|---|---|---|---|
| 0 基线 | G5 | fixture 全绿 + token 基线 | — |
| 1 状态统一✅ | G4/G3 | E2.1-E2.4 过 | — |
| 2 循环模块化✅ | G4/G1 | E3.1-E3.4 过 | — |
| 3 契约重写 | G2/G4 | SKILL ≤500 + 授权矩阵 + subskill 树落盘 | 0 |
| 4 动作选择 | G2 | 价值序符合率 ≥70% + 反馈闭环固化实验【修订 2026-08-06】 | 0 |
| 5 状态迁移 | G4/G5 | 假 fact 全 FAIL + 零漂移 | 0/4 |
| 6 digest | G3 | 冷启动 ≤38K + RRR ≤0.3 | 5 |
| 7 评测 | G5 | 三臂 A≥B + oracle 10/10 | 4/5 |
| 8 收尾 | G1 | 31→9 CLI + 资源选择(kong-select)路由【修订 2026-08-06】 | 全部 |
| 9 端到端 | 全部 | §2.3 清单全过 | 8 |

**重构完成 = 阶段 9 通过 = 五目标全部验收判据达成。**
