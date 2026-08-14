# kunglao-agent 模块子模块级设计(§4 扩展)

> **HISTORICAL (2026-08-11)**: 本文档写成时名为 `kong-agent`;技能已更名为 `kunglao-agent`,文中 `kong.py` / `lib_kong.py` 为历史名称,当前实现见 `scripts/kunglao*.py`。此档案仅用于追溯设计意图。

> 每个模块展开到: 子模块划分 / 函数签名 / 输入输出 schema / 内部状态机 / 错误处理 / 测试点。
> 配套: kong-agent-design-spec.md §4(模块级)+ kong-agent-refactor-plan.md(目标)。

---

# M0 状态层 — 子模块设计

## M0.1 子模块划分

```
M0 状态层
├── store_claim       claim-register.yaml 读写(人类可审)
├── store_loopstate   loop-state.json 读写(机器, 派生视图)
├── store_digest      digest.md 读写(工作记忆, 机械生成)
├── store_ledger      ledger.jsonl 读写(事件账本, 幂等)
├── store_registry    resource-registry.yaml 读写 + 增量添加【修订 2026-08-06: 新增】
└── store_atomic      原子写实现(所有 store 共用)
```

## M0.2 函数签名

```python
# store_atomic(共用)
def atomic_write(path: Path, text: str) -> None:
    """写 temp → fsync → rename(崩溃安全). 所有 store 写走这里."""

def atomic_append(path: Path, line: str) -> None:
    """append 到 jsonl: O_APPEND + flush; 崩溃最多丢尾行, 不损坏."""

# store_claim
def read_claims(ws: Path) -> list[Claim]:           # yaml.safe_load + schema 校验
def write_claim(ws: Path, claim: Claim) -> None:     # 单条更新(读-改-写, atomic)
def read_claim(ws: Path, cid: str) -> Claim | None
def claim_statuses(ws: Path) -> dict[str, str]       # {cid: status}, 供 decide/monitor

# store_loopstate
def reconcile(ws: Path) -> LoopState:                # TEMP mtime → 派生视图(§3.3)
def read_loopstate(ws: Path) -> LoopState | None
def write_loopstate(ws: Path, state: LoopState) -> None

# store_digest
def build_digest(ws: Path) -> str                    # 六节机械生成(§3.6)
def read_digest(ws: Path) -> str
def digest_completeness(ws: Path) -> bool            # 新增 fact 1 轮内进 digest?

# store_ledger
def record_event(ws: Path, event: Event) -> int:     # 幂等: 同 event_id 返回已有 seq
def read_events(ws: Path, event_type: str | None) -> list[Event]
def reconcile_to_legacy(ws: Path) -> bool            # 账本回放旧通道, checksum 零漂移?

# store_registry 【修订 2026-08-06: 新增】
def scan_resources(ws: Path) -> list[Resource]:
    """注册器: 扫描 ~/.claude/skills/* + ~/.claude/agents/* + mcpServers + scripts/
    → resource-registry.yaml(动态生成, 不写死); kong-init 阶段调用"""
def read_registry(ws: Path) -> list[Resource]:       # 读 resource-registry.yaml
def add_resource(ws: Path, res: Resource) -> None:
    """增量添加(反馈固化); 同 id 已存在 → 合并不覆盖评分"""
def update_score(ws: Path, res_id: str, outcome: str) -> None:
    """反馈: success → success_rate↑; fail → fail_count++ 降权"""
```

## M0.3 数据结构 schema

```python
@dataclass Claim:
    id: str; status: str; boundary_type: str
    evidence_tier_attempted: int; promotion_attempts: int
    depends_on: list[str]; method_trail: list[str]      # 每 attempt 追加

@dataclass LoopState:
    ts: str; source: str
    agent_count: int; active: list[str]; stale: list[str]
    agents: dict[str, AgentMeta]                        # {agent_id: {path, mtime_ts, age_min, project, session}}

@dataclass Event:
    seq: int; event_id: str                             # sha256(event_type+payload)
    source_module: str; event_type: str
    payload: dict; checksum: str

EventType = Literal["fact_written","fact_verified","claim_promoted","claim_refuted",
                    "failure_recorded","intent_opened","intent_closed"]

# 【修订 2026-08-06: 新增】资源条目(resource-registry.yaml)
@dataclass Resource:
    id: str; kind: str                               # skill | tool | mcp | script
    description: str; keywords: list[str]
    score: dict[str, float | int]                    # {success_rate, fail_count, last_result}
    depends_on: list[str]                            # 组合依赖序(静态先行: ghidra → frida → floss)
```

## M0.4 错误处理

- 任何 store 读失败 → 返回空/None + 记录 warning(不崩溃, 侧通道语义)
- atomic_write 失败 → 重试 1 次 → 失败则报错(状态一致性优先)
- 幂等: 同 event_id 重复 record → 返回已有 seq(不重复落盘)
- 注册器扫描失败(目录缺失) → 空注册表 + 警告(不崩溃), 等待 kong-init 重扫【修订 2026-08-06】

## M0.5 测试点

- atomic_write 崩溃恢复(写一半 → rename 未发生 → 旧文件完好)
- 幂等: 同 event 两次 record → 1 条
- digest 完整性: 新增 fact 不进 digest → completeness=False
- 注册器: 新增 skill 后重扫 → 条目出现(不写死)【修订 2026-08-06】
- 增量添加幂等: 同 id 两次 add_resource → 合并不重复【修订 2026-08-06】

---

# M1 DECIDE — 子模块设计

## M1.1 子模块划分

```
M1 DECIDE
├── convergence_matrix    该不该派(5 分支决策矩阵)
├── priority_ratio        比值键排序(§3.2)
├── resource_selector     资源选择层(多路召回 + 融合排序 + 组合选择)【修订 2026-08-06: 替代 method_router】
├── feedback_updater      反馈闭环(读 fact/verify/ledger → 更新评分/固化)【修订 2026-08-06: 新增】
├── explore_gate          探索阶段判定(证据计数阈值)
└── selfcheck             行为契约扫描(不反问/不加 cap)
```

## M1.2 函数签名

```python
def convergence_matrix(open_count, partial_count, free_slots, blocked_count) -> Decision:
    """→ DISPATCH(1) | DISPATCH_VERIFIER(2) | SATURATED(3) | BLOCKED(4) | CONVERGED(0)"""

def priority_ratio(claims: list[Claim], deps: DepGraph, evidence: EvidenceView) -> list[Action]:
    """比值键排序【修订 2026-08-06 算法定稿】: score = [0.45·L + 0.30·D + 0.25·N] / cost
    L = leverage = |下游 OPEN claim| / |下游最大| (claim_deps 反边); claim 有 terminal fact → L=0
    D = discriminator = 结构字段: 活 competitor_group=1.0 / answers_question=0.5 / else=0.2
    N = novelty = 1 − min(1, 该证据区已产 fact 数 / k); k=EXPLORE_BASE
    cost = TIER_COST[tier] = {T1:1, T2:3, T3:10}
    纯机械零 LLM; 同分(ε)取 cost 小者; 权重起点值待回放标定"""

# 【修订 2026-08-06: method_router → resource_selector + feedback_updater】
def resource_selector(action: Action, registry: list[Resource], emb_client=None) -> list[Resource]:
    """多路召回: 嵌入(bge-m3, 本地 ollama)+ 关键词 + description 融合 → 排序
    → top-k; 组合选择: 按 depends_on 依赖序(静态先行);
    返回有序资源列表(kong-select 内核); emb_client 不可用 → 降级两路召回"""
def feedback_updater(ws: Path) -> None:
    """读 fact/verify/ledger 执行结果(读盘, 不拦截): 成功+研究兜底发现新资源
    → 增量注册固化; 失败 → 降权 + 换 top-2(熔断);
    成功率累积 → 自学习后置层(SkillWeaver 式)数据源"""

def explore_gate(verified_fact_count: int, threshold: int) -> bool:
    """count < threshold → 探索模式(按 cheapness 铺开 T1)"""

def selfcheck(text: str) -> list[str]:
    """扫描 orchestrator 输出, 找反问/自加 cap 违规"""

def decide(ws: Path) -> DecideOutput:
    """组合以上; 输出契约冻结"""
```

## M1.3 输出 schema(冻结, worker_pulse 解析)

```json
{
  "decision": "DISPATCH|DISPATCH_VERIFIER|SATURATED|BLOCKED|CONVERGED",
  "exit_code": 0|1|2|3|4,
  "top_actions": [{"claim_id": "C-001", "action": "c2_config_extract", "score": 0.87, "skill": "ghidra-re",
                    "resources": ["ghidra-re", "rev-frida", "floss"]}],   # 【修订 2026-08-06: 组合资源, 依赖序】
  "blocked": [], "failure_blocked": [], "stale": [], "drifts": [],
  "explore_mode": false, "selfcheck": []
}
```

## M1.4 状态机

```
decide(ws):
  evidence = load_evidence(ws)                    # facts/_INDEX + ledger + loopstate
  decision = convergence_matrix(...)
  if decision == DISPATCH:
    if explore_gate(evidence.verified_count):     # 早期
      top = sort_by(cheapness)[:k]
    else:
      actions = priority_ratio(claims, deps, evidence)
      for a in top_k(actions, k=free_slots):
        a.resources = resource_selector(a, registry, emb_client)  # 资源选择层(kong-select)【修订 2026-08-06】
    dispatch(top)                                 # 组合派发(依赖序)
  if has_completions: feedback_updater(ws)        # 读结果 → 更新评分/固化【修订 2026-08-06】
  elif decision == DISPATCH_VERIFIER:
    dispatch_verifier(partial_facts)
  return DecideOutput
```

## M1.5 错误处理

- 【修订 2026-08-06】注册表无匹配资源 → escalate(LLM 图生长) + 成功后反馈固化(增量注册)
- tool_health 探测失败(VM 掉线) → 该资源降权 → top-2 替代(熔断)
- 嵌入服务(ollama)不可用 → 降级关键词 + description 两路召回(不阻塞)
- 脚本异常 → 记录 ledger(failure_recorded) + 返回 CONVERGED 前的保守决策(不误报收敛)

## M1.6 测试点

- 5 分支矩阵各 ≥2 用例(行为快照已有)
- 比值键: 同 claim 集新旧排序差异快照(阶段 4 验收)
- resource_selector: 注入资源失败 → 换 top-2(熔断), 0 LLM 调用(E-SEM-1: 关键词匹配正确区分)【修订 2026-08-06】
- feedback_updater: 成功 → 评分上升; 失败 → 降权 + 下次 top-2 优先【修订 2026-08-06】

---

# M2 ACT — 子模块设计

## M2.1 子模块划分

```
M2 ACT(hook 层)
├── gate_workers        ≤3 worker
├── gate_cap            promotion_attempts < 3
├── gate_tools          tools ⊆ task_spec.constraints
├── gate_hostchan       host-channel 动态工具禁止(VM-only)
├── gate_deadline       now < deadline_ts
├── gate_tier           tier 门控
├── gate_selfcap        dispatch 无自加时间帽
├── gate_heartbeat      heartbeat alive(查 tick_ts)
└── gate_claimstatus    worker 自提升防
```

## M2.2 函数签名

```python
def pre_check(payload: dict, paths: dict) -> int:
    """8 项检查(顺序): workers→cap→tools→hostchan→deadline→tier→selfcap→heartbeat
    任一 REJECT → exit 2(阻塞 dispatch)
    全过 → register_worker + exit 0"""

def register_worker(state_path: Path, entry: dict) -> None:
    """写 [active_workers] 段(atomic)"""

def remove_worker(state_path: Path, worker_id: str) -> dict | None:
    """worker 完成/失败 → 移除(PostToolUse)"""

def check_claim_status_change(reg_path: Path, agent_name: str) -> tuple[bool, str]:
    """worker 写 terminal 状态(非 orchestrator) → 拒(maker-checker)"""

def post_check(payload: dict, paths: dict) -> int:
    """worker 完成 → remove_worker + claim-status 审计(只 log 不拦)"""
```

## M2.3 触发时序

```
PreToolUse(matcher=Agent):
  dispatch → pre_check(8 项) → REJECT(exit 2) 或 register_worker(exit 0)
PostToolUse(matcher=Agent):
  worker 完成 → post_check: remove_worker + claim-status audit
  → worker_pulse(通知 M1 重排 + 补位)
```

## M2.4 错误处理

- settings.json hooks 段被重写擦除 → hooks_selfcheck 检测 → 自动重建(幂等)
- 激活过期(30min) → gate_heartbeat 拒 dispatch → orchestrator renew
- zombie active_workers → reconcile 从 TEMP mtime 重建(真实活性)

## M2.5 测试点

- 8 项检查各 ≥2 用例(24/24 smoke 已有部分)
- 自提升防: 伪造 worker 写 PROVEN → 拦(E3.3 F8)
- 心跳门: A(无 tick)触发 / B(tick 正常)不触发(E2.3)

---

# M3 VERIFY — 子模块设计

## M3.1 子模块划分

```
M3 VERIFY
├── l1_mechanical     L1 机械层: 重跑 reproduce + 字节比对
├── l2_redteam        L2 对抗层: 派发 kong-redteam(独立 subagent)
├── lane_scheduler    fact 依赖 DAG → lane 并行/串行
└── anchor_check      PASS 必须带 anchors(数字保真)
```

## M3.2 函数签名

```python
def l1_mechanical(fact: Fact, fixture: Path) -> Verdict:
    """parse_reproduce → run(只读白名单) → sha256 比对 expected → PASS/FAIL"""

def l2_redteam(claim_id: str, ws: Path) -> RedteamVerdict:
    """派发 kong-redteam(独立 subagent, BLIND)
    约束: 不看 facts/F<NNN>/notes/worker-status; 独立推导; 自证先于对比;
          DIFF 每分歧; 五角度; plan-to-execute; self-consistency 多路径
    → CONFIRMED | REFUTED | UNVERIFIED-WITH-GAP"""

def lane_scheduler(facts: list[Fact], refutability: DepGraph) -> list[list[Fact]]:
    """无共享上游 → 并行 lane(≤3); 共享证据 → 同 lane 串行"""

def anchor_check(verdict: Verdict) -> bool:
    """PASS 必须带 anchors(原始字节位置 + 命令 + expected/actual); 无锚不提升"""

def verify(ws: Path, fact_id: str) -> VerifyOutput:
    """L1 → 若 PASS 且需语义 → L2 → anchor_check → 写 runs/verify-<ts>.json"""
```

## M3.3 输出 schema(冻结)

```json
{
  "fact_id": "F-001", "claim_id": "C-001",
  "l1": {"verdict": "PASS|FAIL", "actual_sha256": "...", "cmd": "..."},
  "l2": {"verdict": "CONFIRMED|REFUTED|UNVERIFIED-WITH-GAP", "gaps": ["..."]},
  "anchors": [{"byte_offset": "0xFE8F0", "cmd": "xxd -l 64", "expected": "4d5a9000"}],
  "overall": "VERIFIED|REJECTED|PARTIAL"
}
```

## M3.4 状态机

```
verify(ws, fact_id):
  v1 = l1_mechanical(fact, fixture)
  if v1 == FAIL: return REJECTED            # 不进入 L2
  if not needs_semantic(fact): return VERIFIED(v1)
  v2 = l2_redteam(claim_id, ws)             # kong-redteam 独立派发
  if v2 == CONFIRMED AND anchor_check: return VERIFIED
  if v2 == REFUTED: return REJECTED
  return PARTIAL(UNVERIFIED-WITH-GAP)
```

## M3.5 错误处理

- L1 命令超时/工具缺失 → FAIL(不降级为 PASS)
- redteam 无法完成(VM 需求) → 在 GAPs 说明, 不静默 PASS
- lane 并发冲突 → 回退串行(前序 PASS 才派后继)

## M3.6 测试点

- 已知 PROVEN fact 全 PASS / 构造假 fact 全 FAIL(判别力)
- 盲验证: 输入不含 maker 结论 → redteam 独立推导(伪造 PROVEN 被拦)
- anchor_check: 无锚 PASS → 拒提升

---

# M4 RECORD — 子模块设计

## M4.1 子模块划分

```
M4 RECORD
├── ledger_writer       ledger.jsonl 幂等写入
├── reconciler          账本回放旧通道(progress/analysis_state)
├── summary_aggregator  worker summary_of_work 聚合 → digest
└── claim_migrator      claim 状态迁移(合法性检查)
```

## M4.2 函数签名

```python
def ledger_writer(ws: Path, event: Event) -> int:
    """event_id = sha256(event_type+payload); 幂等(重复返回已有 seq); atomic_append"""

def reconciler(ws: Path, n_rounds: int = 3) -> bool:
    """账本回放为 progress.txt/analysis_state.txt append
    连续 n 轮 checksum 零漂移 → True(读者可切账本)"""

def summary_aggregator(worker_result: SummaryOfWork) -> dict:
    """{topic, conclusion, evidence_pointers, open_questions} → digest 聚合"""
```

## M4.3 event_type 枚举(完整)

```
fact_written / fact_verified / claim_promoted / claim_refuted /
failure_recorded / intent_opened / intent_closed
+ maker_module 字段(谁造谁验可追溯)
```

## M4.4 状态迁移(Expand→Migrate→Contract)

```
Expand:   账本旁路写入, 旧 CLI 照旧(零行为变更)
Migrate:  reconciler 回放旧通道, N=3 轮 checksum 零漂移 → 读者切账本
Contract: 旧通道降级只读
```

## M4.5 错误处理

- 幂等: 同 event 两次 → 1 条(不重复)
- reconciler 漂移 → 停在 Migrate(不推进 Contract, 天然可回滚)
- 原子写失败 → 重试 1 次 → 报错(状态一致性优先)

## M4.6 测试点

- 幂等: 同 event 两次 record → 1 条
- 迁移: 账本↔旧通道 checksum 一致(N=3)
- claim 迁移: 非 orchestrator 写 terminal → 拒

---

# M5 MONITOR — 子模块设计

## M5.1 子模块划分

```
M5 MONITOR
├── heartbeat           tick_ts/activity_ts 二分(§3.7)
├── loop_reconcile      TEMP mtime → loop-state(§3.3)
├── help_watch          active_intervention(help_request 响应)
├── stuck_watch         backtrack_gate(卡死检测)
└── health_check        convergence_health(HEALTHY/STALLED/SPINNING)
```

## M5.2 函数签名

```python
def heartbeat_check(ws: Path) -> tuple[bool, str]:
    """查 tick_ts(< 35min) → alive/STALE; 不查 activity_ts"""

def loop_reconcile(ws: Path) -> LoopState:
    """TEMP mtime → loop-state.json + 事件 diff"""

def health_check(ws: Path) -> dict:
    """ledger 轨迹 → HEALTHY/STALLED/SPINNING + flatline/churn 指标"""

def tick(ws: Path) -> TickOutput:
    """组合: heartbeat→reconcile→help_watch→stuck_watch→health
    输出: 一句话状态 + 下一步建议(LLM 只读)"""
```

## M5.3 输出 schema

```json
{
  "ts": "...", "heartbeat": "alive|STALE",
  "active_workers": 2, "stale_agents": [], "gone_events": [],
  "help_requests": [], "stuck": [],
  "health": "HEALTHY|STALLED|SPINNING",
  "next": "dispatch C-001 | verify F-001 | converged-check | ..."
}
```

## M5.4 状态机

```
tick(ws):
  hb = heartbeat_check(ws)
  ls = loop_reconcile(ws)                    # 更新 loop-state + 事件 (active/stale/gone)
  hi = help_watch(ws)                        # 未响应 help_request
  st = stuck_watch(ws)                       # 卡死 worker
  hl = health_check(ws)                      # 轨迹健康
  next = decide_next(hb, ls, hi, st, hl)     # 机械推断下一步
  return TickOutput
```

## M5.5 错误处理

- TEMP glob 失败(目录不存在) → 空 loop-state + 警告(不崩溃)
- heartbeat 文件损坏 → STALE + 提示 re-register

## M5.6 测试点

- heartbeat: A 触发 / B 不触发(E2.3)
- 对账: 三源漂移消除(E2.1)
- 健康: HEALTHY/STALLED/SPINNING 三判定(行为快照)

---

# 编排原子入口 kong.py

## 签名

```python
def kong(ws: Path, verbose: bool = False) -> int:
    """每 tick 调用一次; 内部自动循环:
    tick → decide → (dispatch|verify|record) → 处理完成 → 收敛判定
    输出: 一句话状态 + 下一步建议(LLM 只读)"""

def main():
    """python kong.py <ws> [--verbose]
    唯一编排入口; 不解析子命令(特殊操作用独立 CLI: kong-init/verify/eval...)"""
```

## 状态机(自动循环)

```
kong(ws):
  t = tick(ws)                        # M5: heartbeat/对账/健康
  if t.heartbeat == STALE:            # 监控失效 → 提示 re-register, 不派发
    return
  d = decide(ws)                      # M1: 决策 + 资源选择(kong-select)【修订 2026-08-06】
  if d.decision == DISPATCH:
    dispatch(d.top_actions)           # M2 门检查后派发
  if d.decision == DISPATCH_VERIFIER:
    verify(partial_facts)             # M3 + redteam
  process_completions()               # M4 record + M1 重排
  if converged_and_drained():
    run_checklist(§6.3)               # 收敛 → checklist
```

## 测试点

- 无活跃 worker + 有 open → DISPATCH(一次 tick 内完成)
- 有 partial → DISPATCH_VERIFIER
- 全 done → CONVERGED + checklist 全绿
- 心跳 STALE → 不派发(监控失效可检出)
