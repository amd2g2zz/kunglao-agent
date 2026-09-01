# Proposal: issue-879-trace-identity — trace 身份层（trace_id / actor 词表 / claim 谱系边）

## Why

发起方类型/id/时间不可知，动作与工具缺链路 ID → 干完就忘、无法 debug、DAG 无法装配、值无法归属（RC1，#866 评论 5492595123）。identity 锚三层已定案：mission（trace_id 不变）/ claim（C-NN 不可变+状态机）/ span（append-only）；subtask 拓扑变化建模为"生命周期事件+谱系边"，不重写历史。

## What Changes

- `scripts/kunglao_log.py`：emit 加 `trace_id` 字段（缺省 null，旧行/旧消费者零破坏）；
  +`validate_trace_id` / `new_trace_id` / `allocate_trace_id`（mission 稳定，`tr-<mission>-<seq>`，
  状态存 `runs/.trace-state.json`，fail-open）；+`validate_actor` 严格词表
  （`orchestrator / worker:<name> / verifier:<name> / hook:<name> / subagent:<type>`）
  + `LEGACY_ACTORS` 收编既有字面量（#459 EMIT_ACTIONS 收编纪律先例）；
  +读方面 `unattributed_rate(ws)`（未归因率，座舱字段数据源）与 `--check-actors` CLI
- `hooks/dispatch_gate.py`：激活派发路径解析 trace_id（envelope 合法→复用；缺失→分配；
  非法→WARN+重新分配）；分配时发 `trace_allocated` 行（新 EMIT_ACTIONS 词，字母序）；
  `_emit_trace` 增 trace_id 形参（deviation 行可归因）
- `hooks/worker_budget_sinks.py`：#461 linkage `dispatch` 行补 `trace_id=`（envelope meta 解析，additive）
- `scripts/plan_stages.py`：`plan_review` 事件 detail 携带结构 diff（added/removed/changed stage id）
- `scripts/retract_claim.py`：`--reason superseded` 增 `--superseded-by <C-NN>` → register 写
  `superseded_by:`（被撤 claim）+ `supersedes:`（后继 claim）双边谱系边
- `scripts/carrier_consistency.py`：新 violation 类 `(g)` — 谱系边校验（目标存在/不自环/无环）
- `scripts/lint_facts.py`：`KNOWN_FRONTMATTER_KEYS` 收编 `trace_id`（L-3 已见即收编，非放行漂移）
- 协议/文档：`references/dispatch-protocol.md`（envelope 新 `trace_id` 段）、
  `skills/kunglao-agent/SKILL.md`（派发 envelope 样例）、`agents/kunglao-worker.md`
  （worker 回带：worker-status 行 `| trace: <id>` + fact frontmatter `trace_id:`）、
  `references/schema.md`（claim-register 谱系字段）、`templates/fact-frontmatter.md`（扩展层表）

## Capability Intent

同 mission 全链行（dispatch→worker→结算）可按 trace_id join；未归因率（无 trace 行占比）
可计算——座舱字段的数据源；SUPERSEDED claim 有边可循（谁替代谁）；actor 出现非法词表值时
机械门可查。全部 additive：旧 emit 行、旧 register、旧 worker-status、旧 dispatch prompt 零破坏。

## Out of Scope

- 聚合消费（座舱接线/statusline 显示）→ #882；EMIT 双向门/tool_call 发射者 → #880
- 既有 LEGACY actor 字面量的批量重写（收编不迁移，与 #459 同纪律；新代码必须词表内）
- span 层独立数据结构（本轮 trace_id 落在既有账本行上，span=append-only 账本本身）

## Recon

### 锚点表（计划推测 → 实测）

| 探索目标 | 实测锚点 | 结论 |
|---|---|---|
| dispatch prompt 前缀生成点 | 前缀由 **orchestrator 按协议手写**，无 script 生成方；权威文档 `skills/kunglao-agent/SKILL.md:193` + `references/dispatch-protocol.md:16-33` | "加段"=协议层加 envelope 键 `trace_id`，文档落点即上两处 |
| 前缀消费者 | 解析 `hooks/lib_kunglao.py:135` `parse_dispatch_json`（:166-168 任意键 passthrough 进 meta）；消费者 `hooks/dispatch_gate.py:192/:218(reversible)/:704(agent)`、`hooks/worker_budget_sinks.py:434` | envelope `trace_id` 零解析器改动即达全部消费者；meta 通道有 `task`/`agent`/`reversible` 先例 |
| `kunglao_log.emit` 行结构 | `scripts/kunglao_log.py:79-107`（13 字段，全 null 缺省，sort_keys 稳定序列化） | 加 `trace_id` 与 #818 加 arm/epoch 同型，additive |
| emit 消费者清单 | `event_taxonomy.py:433`（按 event_type 分类，不触 emit 行字段）；`kunglao_status.py:169,186`（.get 全字段展示）；`infeasible_signal.py:35`（action/detail）；`value_replay.py:111,220`（action/tool）；`kunglao_resume.py:274`（ts/file/actor/action）；`verify_status_watch.py:105`（tail→action/actor/claim/artifact/detail） | **全部 dict 按字段名 `.get`，无位置解析、无键集断言**（唯一键集断言在 tests/test_kunglao_log.py:22 ALL_FIELDS，随 schema 增长同步更新）→ 加字段无解析破坏风险 |
| claim-register 权威 schema | `references/schema.md:27-39`（entry 字段表） | 新字段 `supersedes`/`superseded_by`/`derived_from` 走 additive |
| register 加载容错 | 全仓 get-based（`priority_ratio.py:144,268,295,728`；`event_taxonomy.py:321-335` 行式解析只看 `- id:`/`status:`）；严格面仅 `carrier_consistency.py:135` `_StrictLoader`（防重复键，不限制键集） | 容忍性证据：新增测试以"带新字段的 register"过 carrier_consistency.check + event_taxonomy._claim_statuses + priority_ratio 读取 |
| worker-status 写入点 | `agents/kunglao-worker.md:62-66,288-290`（首行/追加/`status: done` 携 artifacts 协议）；解析 `hooks/lib_kunglao.py:274` `WORKER_STATUS_RE` + `:334` tokens | 行尾追加 `| trace: <id>` 不触 `status:` token 正则（测试钉住） |
| fact frontmatter 写入点 | `templates/fact-frontmatter.md:22`（`claim_id` 字段 #9 = 回带通道）+ :74-86 扩展层；lint `scripts/lint_facts.py:130` KNOWN_FRONTMATTER_KEYS、`:686` UNKNOWN_KEY=warning | `trace_id` 收编进 KNOWN 表（L-3 "seen and curated" 纪律） |
| trace_id 生成挂点 | `hooks/dispatch_gate.py:874` `main()`；pass 路径 `:982`；**dispatch 事件行实际发射点 `hooks/worker_budget_sinks.py:414`**（`_apply_dispatch_linkage`，action=dispatch，actor=hook:worker_budget）；`_emit_trace` `:352-367` | 两个 hook 解析**同一份 prompt** → envelope meta 是零竞态共享通道；gate 侧分配走 workspace 状态文件（mission 稳定），不依赖 hook 触发顺序 |
| actor 词表现状 | 既有 actor 字面量约 40 种（orchestrator / hook:dispatch_gate / hook:worker_budget / convergence_check / init / migrate_facts / user / ...）；`hook:<name>` 形态已在用 | 一次性强制会红掉约 50 个发射点 → 采用 #459 EMIT_ACTIONS 收编纪律：严格词表 + LEGACY_ACTORS 收编 + CI anchor（新字面量必须词表内） |
| plan_review 事件 | `scripts/plan_stages.py:149-176` `_commit_review`（replan 时 `:158` `data["stages"]=new_stages`，emit detail 仅 {verdict,reason}） | detail 增 `stages_diff`（added/removed/changed，按 stage id 对比） |
| SUPERSEDED 写者 | `scripts/retract_claim.py`（RETRACTED 终态 + `retract_reason: superseded`，:219-221 写 register）；status_defs SUPERSEDED 语义（#59 superseded_by） | retract_claim 是谱系边 `--superseded-by` 的权威写者 |

### 基线

`pytest tests/test_kunglao_log.py tests/test_event_stream_adoption.py tests/test_decision_teeth.py tests/test_lint_facts_532.py tests/test_plan_stages_822.py tests/test_retract_claim.py tests/test_dispatch_protocol.py tests/test_worker_budget.py -q` → **218 passed**（改动前绿）。

### 决策记录（实现级 WHAT/WHY，非规格偏航）

1. **trace_id 权威来源 = v1 envelope 可选键 `trace_id`**（"前缀新段"的落点）：orchestrator 按
   协议写入 → dispatch_gate / worker_budget 两 hook 解析同一 prompt 即零竞态共享；meta
   passthrough 使解析器零改动。mission 稳定语义（"mission(trace_id 不变)"）由 gate 分配面保证：
   `runs/.trace-state.json` 记 {mission, seq, trace_id}，同 mission 复用同一 id，缺失才分配
   （seq 递增），fail-open（状态文件不可用时以时间戳序号兜底，格式仍合法）。
2. **`trace_allocated` 为新 EMIT_ACTIONS 词**（字母序登记）：仅"新分配"面发射，复用面静默
   （dispatch 行本身已由 worker_budget linkage 发射，一词一面纪律）。
3. **actor 词表收编**：`validate_actor` 严格（词表五形态）；`LEGACY_ACTORS` 收编存量字面量；
   CI anchor 扫描 scripts/hooks 的 actor 字面量（新字面量必须词表内，收编表外即红）——与
   #459 EMIT_ACTIONS adoption 完全同构。emitter 运行时**不**因 actor 拒写（logging never
   breaks analysis）；`--check-actors <ws>` 提供账本非法值可查面。
4. **谱系边方向**：被撤 claim 写 `superseded_by: <后继>`、后继写 `supersedes: <被撤>`（双边，
   与 #47 fact 级先例同词汇）；`derived_from: []` 为 derivation 边（非替代）。校验面 =
   carrier_consistency 新 `(g)` 类（目标存在/不自环/supersedes 链无环）。
5. **worker 回带通道**：worker-status 行尾 `| trace: <trace_id>`（token 解析不受影响的实测
   依据见锚点表）；fact frontmatter `trace_id:`（扩展层字段，KNOWN 表收编后 lint 零告警）。

### 偏航

无规格级偏航。计划锚点漂移（§0.7 预期内）：`_emit_trace` 与 dispatch 事件发射点实测分别在
dispatch_gate.py:352 与 worker_budget_sinks.py:414（计划未给行号，方案不受影响）。

### Rebase 冲突处置（rebase onto origin/dev 74879e8，2026-09-01）

dev 上 #600（`_emit_capability_dormant` + sentinel + `capability_dormant` 词）与 #601
（must-stop 规则 id + `matched_rule` schema 字段）与#884/#886 合并后，本卡 5 commits 重放，
3 处冲突全部语义合并（双方语义都活）：

1. `scripts/kunglao_log.py` emit — `matched_rule` 与 `trace_id` 同为 additive kwarg，
   双保留 + 双 docstring 段；模块 schema 列表补 `matched_rule` 行。
2. `tests/test_kunglao_log.py` ALL_FIELDS / `tests/test_logging_coverage.py`
   SCHEMA_FIELDS — `matched_rule` 与 `trace_id` 并入同一字段集（15 字段 schema 钉子，
   两字段共存已实测：同行可同时携带 `matched_rule="mcp__ghidra__*"` +
   `trace_id="tr-m-0001"`，join 语义不受影响）。
3. `hooks/dispatch_gate.py` — `_emit_trace` 双形参（matched_rule + trace_id）；dev 的
   `_emit_capability_dormant` 函数整体保留 + 本卡 `_capability_guard` trace_id 形参合并；
   main() 自动合并后语义核对：#601 must-stop rule face → 本卡 trace 解析 → teeth
   （trace 透传）→ pass 路径 `trace_allocated` 发射，顺序不变、双方 face 均在。
4. 生成面按序刷新（先 `tools/ext-scan.py` 再 `deploy_manifest.py --write/--verify`，
   规避 ext-index 哈希落后于 manifest 的顺序陷阱）：363 entries verified；
   `references/_INDEX.yaml` re-pin 无漂移。

