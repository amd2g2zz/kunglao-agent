# Phase 4 契约 — M1 DECIDE 动作选择改造 (Track C)

来源文档(冻结源, 引文带行号):
- `D:/works/samples/2026-07-01/malware-analysis-workspace/.research-tree-alignment/kong-agent-module-design.md` — §M1 全部 (L89-171); M1.1 划分 L93-100; M1.2 签名 L102-127; M1.3 schema L129-139; M1.4 状态机 L141-158; M1.5 错误处理 L160-164; M1.6 测试点 L166-170
- 同目录 `kong-agent-design-spec.md` — §3.2 比值键算法 L125-150; §6.5 method-graph L464-477; §6.7.1 新增清单 L483-497
- 现成可复用(不改): `scripts/convergence_check.py::decide`(5 分支矩阵, golden F-01..F-16)、`scripts/priority.py::rank_claims`(legacy 加法权重)、`scripts/ask_for_direction_gate.py`(selfcheck 反问部分已实现)

---

## 1. 函数签名(冻结, M1.2 原文 L102-127)

```python
def convergence_matrix(open_count, partial_count, free_slots, blocked_count) -> Decision:
    """→ DISPATCH(1) | DISPATCH_VERIFIER(2) | SATURATED(3) | BLOCKED(4) | CONVERGED(0)"""

def priority_ratio(claims: list[Claim], deps: DepGraph, evidence: EvidenceView) -> list[Action]:
    """比值键排序: score = [0.35·Δdisc + 0.35·E_unlock + 0.10·unc] / cost
    Δdisc = marginal_discriminator(对已得证据去重)
    E_unlock = expected_unlock(deps) × P(success)
    unc = freshness = 1/(1+attempts)
    cost = NEXT_TIER_CHEAP[tier]"""

def method_router(action: Action, method_graph: MethodGraph, tool_health: dict) -> Path:
    """Dijkstra 选路径; 失败 → 出边∞ → 重算; 图断 → escalate(LLM)
    method-graph.yaml: 节点=现有 skill, 边=替代+衔接"""

def explore_gate(verified_fact_count: int, threshold: int) -> bool:
    """count < threshold → 探索模式(按 cheapness 铺开 T1)"""

def selfcheck(text: str) -> list[str]:
    """扫描 orchestrator 输出, 找反问/自加 cap 违规"""

def decide(ws: Path) -> DecideOutput:
    """组合以上; 输出契约冻结"""
```

### 落地映射(契约空白决策)

| 设计签名 | 本阶段落地 | 备注 |
|---|---|---|
| `convergence_matrix(...)` | **不新建** — `convergence_check.decide(ws)` 已实现同矩阵(5 分支顺序一致, L241-259)且 golden 冻结 | M1.6 L168 "行为快照已有" |
| `priority_ratio(claims, deps, evidence)` | `scripts/priority_ratio.py::priority_ratio` | 纯函数; failure-blocked 过滤由调用方(kunglao-decide)做(签名无 ws) |
| `method_router(action, ...)` | `scripts/method_router.py::method_router(action_type: str, method_graph: dict, tool_health: dict)` | 纯机械 Dijkstra(heapq), **0 LLM**; escalate 是输出信号, 由 orchestrator 接 LLM 图生长 |
| `explore_gate(count, threshold)` | `scripts/explore_gate.py::explore_gate(count, threshold=EXPLORE_THRESHOLD)` | `EXPLORE_THRESHOLD = 5`(L133 "verified_fact_count < EXPLORE_THRESHOLD"; 契约空白) |
| `selfcheck(text)` | `scripts/kunglao-decide.py::selfcheck(text)` 组合 `ask_for_direction_gate.find_violations`(反问) + `worker_budget.detect_self_cap`(自加 cap) | ask_for_direction_gate 已实现, 只补测试 |
| `decide(ws)` | `scripts/kunglao-decide.py::decide(ws, method_graph_path, tool_health, scan_text)` | 独立 CLI, 非 kunglao.py 子命令(design-spec §6.7.5 L568: `python kunglao-decide <ws>`) |

### priority_ratio 分量语义(契约空白决策, 均写死进 contract 与测试)

- `Δdisc(a) = marginal_discriminator(a, evidence)`:
  - claim a 在 `facts/_INDEX.md` 中有 **terminal fact**(状态含 PROVEN/VERIFIED/NEGATIVE/REFUTED/DEFERRED 之一)→ `0.0`(已得证据去重; design-spec L137 "已确认 C2 → 同类动作边际≈0")
  - 否则 `1.0`
- `E_unlock(a) = expected_unlock(a, deps) × P(success)`:
  - closure 复用 `priority._leverage_v2`(sigmoid 传递闭包 + gateway bonus, 裁剪 [0,1]; priority.py L93-113 现成可复用)
  - `P(success) = 1/(1+promotion_attempts)`(契约空白)
- `unc(a) = freshness(a) = 1/(1+attempts(a))`(与 P(success) 同形; design-spec L140)
- `cost(a) = NEXT_TIER_CHEAP[evidence_tier_attempted(a)]`, 字典 = priority.py L44 `{0: 1.0, 1: 0.5, 2: 0.2}`, 越界 `0.1`
  - **契约空白(字面照抄 design-spec L142-143 "cost = NEXT_TIER_CHEAP[tier]")**: 分母用 cheapness 原值, 语义 = "已尝试过深层证据(eta 高)的 claim 比值放大 — 鼓励深推"; 与 legacy 加法权重(priority.py L171-172)不同。E4.1 测量此字面公式的价值序符合率, **不改公式迁就测量**
- `score(a) = (0.35·Δdisc + 0.35·E_unlock + 0.10·unc) / cost(a)`(design-spec L141-143)
- 排序: score 降序(L145); dispatchable 过滤: 非 terminal、attempts<3、depends_on 全部 terminal(priority.py L60-64/L147-155 同规则)
- `classify_action(claim)`(契约空白): 关键词分类器(statement+answers_question 小写): C2/mpd/pegasus/dead-drop→`c2_config_extract`; 命令表/command table/命令分发→`command_table`; 协议/protocol/runtime 行为/网络→`protocol_restore`; 持久化/persistence/autorun/注册表→`persistence`; 注入/injection/reflective/CreateRemoteThread→`injection`; 反分析/anti-analysis/garble/诱饵/decoy/CFF/混淆→`anti_analysis`; 家族/family/归属/vidar/wingo/gsb→`family_attribution`; 未命中→`evidence_collection`

### method_router 语义(契约空白决策)

- 节点 = 方法(method-graph.yaml `nodes{id, skill, tier, alternatives[]}`); 边 = `edges{from, to, kind}` kind ∈ {`sequence`(衔接), `alternative`(替代)}
- `tool_health: dict[skill -> "down"|"healthy"|"unknown"]`; 仅 `"down"` 使 skill 不可用, 其余(含 unknown)视为可用(M1.5 L163 "VM 掉线" 显式标记)
- 节点可执行 ⇔ 主 skill 或任一 alternatives 可用; 可用性选序: 主 skill 优先, 之后按 alternatives 顺序
- 起点可执行 → 直达路径(0 次 LLM)
- 起点全挂 → **Dijkstra(heapq)** 在可执行子图上找最近可达方法(沿出边, 权重: 每边 1.0 + 终点 DONE 边权重 `TIER_COST = {1:1.0, 2:2.0, 3:4.0}`), 输出路径 = [起点(blocked), …, 可执行终点(带 skill)]
- 图断(无可达可执行节点)/节点缺失 → `escalated=True` + reason(M1.5 L162 "method_graph 缺节点 → 视为图断 → escalate(LLM 图生长)"); **本模块自身永不调用 LLM**, `llm_calls` 恒 0(机械门禁断言点)

### 探索模式(design-spec §3.2 L132-134)

`explore_gate(verified_fact_count, threshold=5)`: `count < threshold` → 探索模式。kunglao-decide 在探索模式下按 cheapness 铺开: 同 dispatchable 过滤, `score = NEXT_TIER_CHEAP[eta]` 降序(T1 优先), `explore_mode=True`。

---

## 2. 输出 schema 引用

- 冻结结构: `schemas/decide-output.json`(M1.3 L131-138 逐字段)
- 必需 9 字段: `decision`(enum 5 值) / `exit_code`(0-4) / `top_actions[]`(items: claim_id, action, score, skill) / `blocked[]` / `failure_blocked[]` / `stale[]` / `drifts[]` / `explore_mode`(bool) / `selfcheck[]`
- 附加字段(additionalProperties 允许, 非冻结必需): `escalations[]`, `open_count`, `partial_count`, `free_slots`, `error`
- 字段映射(契约空白):
  - `blocked` = open_claims 中 `blocked=True` 的 id
  - `failure_blocked` = convergence_check 的 failure_blocked(经 failure_analysis_gate.scan_workspace)
  - `stale` = stuck_workers 的 worker 名(>20min 无 in-progress 更新, convergence_check L98-120)
  - `drifts` = 恒 `[]`(阶段 4 不计算; plan_drift_detector 为独立 gate, 后续阶段接入)
  - `selfcheck` = `--scan-text` 提供时扫描, 否则 `[]`

## 3. 状态机(M1.4 L141-158 原文流程)

```
decide(ws):
  evidence = load_evidence(ws)                    # facts/_INDEX + ledger + loopstate
  decision = convergence_matrix(...)              # ← convergence_check.decide (golden)
  if decision == DISPATCH:
    if explore_gate(evidence.verified_count):     # 早期
      top = sort_by(cheapness)[:k]                # explore_mode=True
    else:
      actions = priority_ratio(claims, deps, evidence)
      for a in top_k(actions, k=free_slots):
        a.path = method_router(a, method_graph, tool_health)   # 方法路由
    dispatch(top)
  elif decision == DISPATCH_VERIFIER:
    dispatch_verifier(partial_facts)
  return DecideOutput
```

- `k = free_slots = max(0, 3 - active_workers)`(convergence_check L231)
- DISPATCH_VERIFIER / SATURATED / CONVERGED: `top_actions=[]`, 其余字段照 convergence_check 映射
- 脚本异常(M1.5 L164): 记 ledger(failure_recorded) + 返回 `BLOCKED`(exit 4) + `error` 字段 — **不误报收敛**

## 4. 测试点(M1.6 L166-170 + 本阶段 RED 清单)

| 测试点 | 断言 | 文件 |
|---|---|---|
| 比值键公式(L169) | `score == (0.35·Δdisc + 0.35·E_unlock + 0.10·unc)/cost(NEXT_TIER_CHEAP)`; **≠ 加法权重**; 排序 score 降序 | tests/test_priority_ratio.py |
| Δdisc 去重 | claim 已有 terminal fact → Δdisc=0 → 分数必低于无证据同 claim | 同上 |
| unc 新鲜度 | attempts 增 → unc 降 → score 降 | 同上 |
| dispatchable 过滤 | terminal / attempts≥3 / dep 非 terminal 排除 | 同上 |
| E_unlock 传递闭包 | 解锁下游的 claim 的 E_unlock 高于无下游者 | 同上 |
| explore_gate | count<5 → True; =5/≥5 → False; 自定义 threshold | tests/test_explore_gate.py |
| kunglao-decide 组合 | DISPATCH 时 top_actions 有值且过 `schemas/decide-output.json`; CONVERGED 时 top_actions=[]; explore_mode 正确 | 同上 |
| selfcheck(L123) | 反问文本 REJECT(rc=1); 自加 cap 文本 REJECT(rc=1); 组合扫描返回违规列表 | 同上 |
| method_router(L170, E4.2) | 注入 tool_health 失败 → 换替代路径, **0 次 LLM 调用**; 图断 → escalate=True; 节点缺失 → escalate=True | tests/test_method_router.py |
| 图引用(L464-477, E4.2) | 每个节点 skill/alternatives 真实存在(skills/agents/scripts); edges 引用合法节点 | tests/test_method_graph_refs.py |

## 5. 完成判据

1. 全部新增测试绿 + 全量回归绿(`python -m pytest -q -p no:cacheprovider`, 原 134 条不回归; test_v1_8_enforcement_gates 测 rank_claims, 未改动应绿)
2. `schemas/decide-output.json` 对 kunglao-decide 输出通过 jsonschema 校验
3. E4.2: method_router 故障注入 → 0 LLM 调用换路径(测试断言)
4. E4.1: `tools/measure_value_order.py` 输出符合率%(如实报告, 不为达标改排序/挑样本)
5. 约束: 不碰 SKILL.md/references/hooks/kunglao.py/convergence_check.py/priority.py/test_suite_health.py/test_kunglao_init.py; 不 git commit

## 6. 方法路由动态注册(用户纠正, 2026-08-06)

**用户纠正**: 写死路由表无意义 — 路由应在 init 阶段把所有 tools/skill/MCP 注册进去,
环境变化自动反映。新装 skill / 新配 MCP / 新加脚本 → 重跑注册器 → 路由自动多一条候选;
卸载 → 自动消失。

### 6.1 注册器 CLI

```
python scripts/method_router_register.py [env] [--output <method-graph.yaml>] [--action-map <action-type-map.yaml>]
```

- `env` 默认 `~/.claude`; `--output` 默认 `data/method-graph.yaml`; `--action-map` 默认 `data/action-type-map.yaml`
- 纯本地机械扫描, 无 LLM 调用; 确定性输出(无随机、无时间戳); 重注册幂等(节点集相同, 无重复)

### 6.2 三源扫描 → 节点(全部来自环境, 不含手写节点)

| 源 | 位置 | 节点 |
|---|---|---|
| skills | `<env>/skills/*/SKILL.md` frontmatter(name/description/allowed-tools) | `id=skill 名, type=skill, tier 按描述启发` |
| MCP | `<env>/settings.json` 的 `mcpServers` | `id=mcp 名, type=mcp`(settings.json 缺失 → 空; 非法 JSON/mapping → 错误) |
| scripts | `<env>/scripts/*.py` | `id=脚本名去 .py, type=script` |

节点字段(与现有 method-graph 格式兼容, list 形态):
`{id, type, skill, tier, keywords[], alternatives[], present, source}` — `source` 标注注册来源
(SKILL.md 路径 / settings.json#mcpServers.<名> / 脚本路径); skill 节点额外带 `description`;
frontmatter 有 allowed-tools 时并入 keywords 并保留 `allowed_tools` 字段。

### 6.3 边(唯一手写部分 = data/action-type-map.yaml)

- `categories.<名>.keywords`: 小写子串匹配注册节点(id+description)→ 类目成员
- `actions.<名>.tier` + `actions.<名>.categories`: 候选类目(有序 — 首个类目首个成员 = 主 skill,
  其余 = alternatives); 生成 alternative 边(动作 → 每个候选成员)
- `sequence: [[from, to]]`: 动作间工作流衔接 → sequence 边;**只保留两端都实际存在于图
  中(有本地候选)的动作**, 无候选动作被跳过时不产生悬空边(load_method_graph 拒收)
- 动作无任何本地候选 → 节点跳过(运行时 escalate 是设计行为: 缺方法 → LLM 图生长)

### 6.4 消费方

- `method_router.load_method_graph(path)` 装载(list→dict)后 Dijkstra 规划;
- `method_topk.topk_methods(task, graph)` 直接接受 list/dict 形态节点(读 nodes 排序, 任务感知 top-k);
- 流水线: 任务 → top-k 选方法 → Dijkstra 规划执行 → 执行 → top-1 失败降级 top-2。


---

## 6. 任务感知 top-k 方法排序(契约空白决策, 2026-08-06 追加)

**定位**: 方法路由的"选方法"层, 与 §6.5 method_router(Dijkstra "规划执行"层)不冲突。
流水线: 任务 → `topk_methods`(选方法) → `method_router`(规划执行) → 执行 → top-1 失败降级 top-2。
topk 输入为**自由文本任务描述** + method-graph(节点带 `keywords`); method_router 输入为 action_type。

### 函数签名

```python
def topk_methods(task_desc: str, method_graph, k: int = 3) -> list[dict]:
    """→ [{id, score, reason}] 按 score 降序; 不可用节点不进结果; 幂等稳定"""
```

- `method_graph`: 接受 Path(yaml) 或 dict(nodes 为 list 或 {id: node}); 节点必填 `id`,
  `keywords`/`tier`/`present`/`type` 缺省补齐(tier 缺省 2, present 缺省 True, type 缺省 skill)。
- `k` 非负整数校验; 空图/`k=0` → `[]`; 违规输入 → 显式 ValueError/TypeError/FileNotFoundError。
- 节点格式比 §6.5 宽松(tests/test_method_topk.py 注册器产物格式: id/type/skill/tier/keywords[/present])。

### 评分语义(契约空白决策)

`score(method) = 域匹配度 × 本地可用性 × tier 价值因子`

1. **任务 → 领域标签**: `DOMAIN_RULES` 规则表(触发词为小写子串匹配, 命中任一 → 并入标签集):
   - JNI/java/android/dex/smali/apk → `[java, android, native, dex]`
   - c2 / command and control → `[network, static]`; 混淆/obfuscation/garble/ollvm/诱饵 → `[obfuscation, static]`
   - 反编译/逆向 → `[static, re]`; 动态/运行时 → `[dynamic, runtime]`; 调试 → `[debug, dynamic]`
   - 网络/流量/抓包 → `[network, protocol]`; 注入 → `[injection, dynamic]`; 持久化/注册表 → `[persistence, registry]`
   - 加密/解密/crypto → `[crypto, static]`; 字符串/floss → `[strings, static]`; 内存/dump → `[memory, forensics]`
   - 协议 → `[protocol, network]`; 恶意/malware/样本 → `[malware, static]`; 取证 → `[forensics, memory]`
   - 反沙箱 → `[anti_analysis, sandbox]`
   - **未命中任何规则** → 任务自身 token(分词去停用词)兜底为标签("分析 x" → 标签 `x`);
     分词也为空 → `[unknown]`(unknown 不匹配任何关键词, 只触发研究升顶判定)。
2. **域匹配度**: `node.keywords ∩ 领域标签` 累加 — 直接命中 0.9; 互为子串(双方 len≥3)部分 0.5。
3. **可用性**: `present=False` 或 `type ∉ {skill, mcp, tool}` → 不可选,**不进 top-k**
   (本地没有的工具不能选 = 无降级价值); type 缺失默认 skill(兼容 data/method-graph.yaml)。
4. **研究升顶**: 无任何**本地可用**节点域匹配 > 0 → research 类节点
   (keywords ∩ {search, web, research, docs} 或 id 含 "search")得 `RESEARCH_BUMP=10.0` × tier 因子,
   必居第一(恒大于正常域匹配上限 3.6 = 4×0.9×1.0)。reason 标注"研究升顶"。
5. **tier 价值因子**: `{1: 1.0, 2: 0.8, 3: 0.6}`(便宜权重略高); 未知 tier → 0.8。

### 排序与幂等

- 排序键 `(-score, tier, id)`: 同分便宜优先, 再按 id 字典序 → 同输入同输出(无随机)。
- top-1 失败降级: 调用方取 `ranked[1]` 即 top-2(自带降级, 不需重路由)。

### 测试点

| 测试点 | 断言 | 文件 |
|---|---|---|
| 核心用例(用户纠正) | 分析 JNI 程序 + 本地无 jadx → anysearch 第一, x64dbg 不进前 2 | tests/test_method_topk.py |
| 本地工具优先 | 本地有 jadx → jadx 高于 anysearch | 同上 |
| 自带降级 | top-1 失败直接用 top-2(不重路由) | 同上 |
