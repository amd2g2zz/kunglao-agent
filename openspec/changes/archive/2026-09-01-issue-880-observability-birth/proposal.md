# issue-880: 观测出生——EMIT 双向门 + toolfirst 双面落盘 + 结算行 + lessons 接线

## Why

RC1：`tool_call` 只在 kunglao_log.py 词表注释里、全仓零发射者——账本记录"开发者记得发的"。
RC2：toolfirst 门（`check_tool_first`）算出 keyword→tool 归因后 pass 路径只返回字符串 reason，
结构化归因 payload 被丢弃。lessons_telemetry 四件套（record_citation/record_burn/record_match/
deprecate_lesson）全仓零生产调用方，计数器空转。claim 状态转换无结算行，#881 聚合器无账可 join。

## Recon（前置探索产出，2026-09-02）

### 锚点表（计划锚点 vs 实测）

| 目标 | 计划锚点 | 实测锚点（本分支 62dcc83） |
|---|---|---|
| EMIT_ACTIONS 词表 | scripts/event_taxonomy.py | scripts/event_taxonomy.py:160-243（~100 词，sorted+unique，test_event_stream_adoption.py:121-188 锚定） |
| 词表正向锚（代码→词表） | test_event_stream_adoption | tests/test_event_stream_adoption.py:98-117 `_unregistered_action_literals`（4 个 literal pattern，已存在=双向门的反向侧） |
| toolfirst 门 | worker_budget_gates.py 一带 | hooks/worker_budget_gates.py:739-796 `check_tool_first`；keyword 表 :687-718 `_load_tool_index_keywords`（tools/_INDEX.yaml category+capability 两半）；reject 路径 :788-795；pass 归因路径 :766-774（`matched_tools` 算出后只进 reason 字符串 = RC2） |
| 双面 emit 样例（照抄对象） | signal_gate 双 emit | scripts/dual_gate.py:56-60 `_emit`：`kunglao_log.emit(ws, actor=..., action=..., detail=json.dumps(payload))`，pass/reject 双面各一发（:87/:103/:123/:132/:144） |
| dispatch 事件发射点 | worker_budget_sinks.py:414 | hooks/worker_budget_sinks.py:413-443 `_dispatch_lifecycle`（trace_id 经 :395-410 `_declared_trace_id` 从 v1 envelope meta 透传） |
| claim 转换钩子 | register_proven_gate | hooks/write_guard.py:325-357 CARRIER_REGISTER leg 调 scripts/register_proven_gate.py:128 `check_register_transitions(ws, new_text, old_text)`；write_guard.main :408-493，ALLOW 路径 = :480-493（violations 为空 → 放行，写将落地 = 结算 emit 的确切点） |
| TERMINAL 状态单一源 | — | scripts/status_defs.py:62 `TERMINAL = {PROVEN, VERIFIED, NEGATIVE, REFUTED, DEFERRED, STALE, SUPERSEDED, DEAD}` |
| lessons 四件套 | lessons_telemetry 签名 | scripts/lessons_telemetry.py:217/223/229 `record_citation/record_burn/record_match(library, slug, workspace=None)`；写前 emit 后顺序契约 :208-211 |
| lesson 检索面（citation/burn 的 slug 来源） | — | scripts/failure_analysis_gate.py:851-867 `_score_lessons` → `[{file: "lesson-<slug>.md", score, ...}]`；record_analysis 把 candidates + next_method_source 存进 analyses/failure-<claim>.yaml（:379-427） |
| tool_call 发射者候选（claim 粒度 v1） | PostToolUse 同通道 | hooks/worker_budget_sinks.py:637 `post_check`（Agent PostToolUse）；:360-366 `scan_actual_tools(tool_result)`（worker transcript 实际工具名）；worker 条目 `claim_id/dispatched_at` 从 analysis_state.txt [active_workers]（worker_budget_core.py:371-410） |
| orchestration label 的 claim 块定位 | — | register claim 块 `- id: C-NN`（register_proven_gate._load_statuses 消费同一形状；worker_budget_gates.py:125-131 的块内 regex 先例） |

### 孤儿 action 现状（双向门正向侧证据）

- 宽网（词以 quoted literal 出现在 scripts/|hooks/*.py、排除 event_taxonomy.py 自身）：
  **当前 0 孤儿**（#459 后词表卫生良好）。双向门的职责 = 防再犯 + 治理新词
  （`tool_call`/`toolfirst_pass`/`toolfirst_reject`/`claim_settled` 必须与真实发射者同帧注册）。
- 严网（仅认 4 个 emit-site literal pattern）：25 词命中不了（dual_gate._emit /
  lessons_telemetry._bump / recall_inject._trace / kunglao_upgrade._emit 等 helper 路由的
  合法发射者全部漏报=假阳性）。**门定义采用宽网**，与既有 test_event_stream_adoption
  锚互为补充：反向（代码→词表）走既有严网 pattern 表，正向（词表→代码）走宽网。
  `tool_call` 当前在 kunglao_log.py:12 docstring 里是**未加引号的散文**——宽网不认散文，
  正是它藏身的形状；本卡给它接上真实发射者后以 quoted literal 进词表。

### lessons 挂点判定（orchestrator 预裁决的 Recon 确认）

预裁决：record_citation ← "recall 注入被 worker 实际引用"判定点；record_burn ← "结算负样本"点。
**两类判定点确认存在且可挂，按预裁决直接实现：**

- **citation 挂点** = `failure_analysis_gate.record_analysis`：record 以
  `next_method_source: "lesson-hit"` 声明 next_method 来自 lessons 梯级检索（= recall 注入被
  实际引用的机判点），candidates（`_score_lessons` 行，含 file→slug）随 entry 落盘。
  触发条件：failure_time 记录 ∧ source=="lesson-hit" ∧ candidates 非空 → 对 candidates[0]
  的 slug 发 record_citation。
- **burn 挂点** = 结算 emit（见下）：claim 终态为负样本（REFUTED/NEGATIVE/DEAD）∧ 其
  analyses/failure-<claim>.yaml 的 next_method_source=="lesson-hit" ∧ candidates 非空 →
  record_burn（top slug）。即"lesson 的方法被消费且闭环为负"。
- 观察（记录给 orchestrator，不构成偏航）：lessons_telemetry.utility = burn/(citation+1)
  随 burn 上升；负样本 burn 抬高 utility 的符号问题属 #881 聚合器消费语义（它用独立的
  cite/burn/reject 计数，不直接吃该公式），本卡不改公式。
- record_match 保持零调用（match 语义=检索 score>0，本卡两个预裁决挂点都不覆盖；留待 #881）。

### toolfirst 双面落盘设计（照抄 dual_gate._emit 模式）

- 新纯函数 `_toolfirst_evaluate(text_lower, cited)` 抽出 check_tool_first 的归因计算，
  返回 `{mode, keywords, tool}`：mode ∈ matched / optout / no_index / exempt / no_match / reject。
- pass 面：`toolfirst_pass`（detail=JSON {mode, keywords, tool}）——matched 才携带归因 payload；
  reject 面：`toolfirst_reject`（detail=JSON {keyword, tool}）。emit fail-open（lazy import +
  try/except，观测不改门 rc，沿 #459 fail-open 契约）。
- **operation label**：matched 面把 `{keywords, tool}` 写成 claim 属性（claim-register.yaml 该
  claim 块新增 `operation:`（逗号 join keywords）+ `operation_tool:` 两行，text-surgical 块内
  插入、逐字节保留其余内容，复用 _replace_segment 的文本手术先例）。写入点 = sinks.pre_check
  全门通过后（fail-open）。词源 tools/_INDEX.yaml，零新词表（issue 原文"operation label 白捡"）。
- round-trip 验收：写 `operation: xor,crypto` 的 claim，读回断言 ≠ "PE 逆向" 形状。

### 结算行 schema（#881 join 键=claim id；全部走 kunglao_log 既有字段，零 schema 变更）

```
action="claim_settled"  actor="hook:write_guard"  claim=C-NN
trace_id=<mission-stable（kunglao_log.allocate_trace_id 复用面）>
duration_ms=<now − 该 claim 最近一次 dispatch 事件 ts（账本实测）>
detail=JSON {"from","to","tools":[...],"outcome":<to>}
tools=该 claim 最近一次 dispatch 事件 detail 的 tools 清单（无则 []）
```

- 发射点：write_guard.main ALLOW 路径 ∧ carrier==register（violations 为空=写必落地）。
  BLOCK 路径不发（写未发生）。transitions diff 复用 register_proven_gate._load_statuses；
  仅 `to ∈ status_defs.TERMINAL` 发（OPEN→IN_PROGRESS 非结算）。
- 覆盖边界（记录）：经 write_guard 通道的 register 写=覆盖面；脚本直写 register
  （failure_analysis_gate._promote_obstacle_claim 只产 OPEN、不触终态；rollup 的
  sweep 面属 #881 聚合器管辖）不在本卡结算覆盖内。

### tool_call 发射者（claim 粒度 v1，卡片明示不阻塞）

- post_check（Agent PostToolUse）：先读 [active_workers] worker 条目（claim_id/dispatched_at）
  再 remove_worker（现顺序是先删，需调序）；`scan_actual_tools(tool_result)` 得实际工具集 →
  每工具一行 `action="tool_call"`，actor="hook:worker_budget"，claim、tool、
  trace_id=`_declared_trace_id(prompt)`。duration_ms 不带（claim 粒度无 per-tool 时长，
  编造即撒谎；时长归结算行）。

### 镜像样例（要抄的既有惯例）

- detail 携带结构化 payload：scripts/dual_gate.py:56-60（detail=json.dumps）。
- gate 内 fail-open emit：hooks/write_guard.py:351-357（proven_waiver_used，lazy import +
  try/except）。
- additive 字段/词注册通道：trace_allocated（event_taxonomy.py:231，#879 同帧注册+发射者）。
- 文本手术写状态：worker_budget_core._replace_segment（analysis_state.txt 段替换）。
- 测试夹具：tests/test_event_stream_adoption.py 的 events fixture（monkeypatch emit 计数）。

### 基线测试（变更前绿）

`tests/test_event_stream_adoption.py test_kunglao_log.py test_lessons_telemetry.py
test_write_guard_register_gate_819.py test_worker_budget.py test_recall_inject.py
test_trace_identity_879.py test_logging_schema_818.py test_logging_coverage.py
test_failure_lessons.py` → **216 passed**（2026-09-02，本分支）。

### 偏航

无规格级偏航。实现级选择（记录 WHAT/WHY，§0.2 第 4 条允许）：
1. 双向门正向侧用宽网（quoted-literal）而非严网 pattern——严网对 helper 路由发射者全漏报
   （25 假阳性证据见上），宽网与反向严网锚互补。
2. `check_register_transitions` 本体不改（violations/waivers 契约不动）；结算走同模块新函数
   `emit_settlements`，由 write_guard ALLOW 路径调用——gate 职责（拦）与观测职责（记）分离。
3. label 写入用 text-surgical 块内插入而非整文件 safe_dump——避免 LLM 手写 register 的
   注释/格式被 safe_dump 抹掉（数据保真）。

### 实现后核账（设计微调记录，非规格偏航）

1. **toolfirst pass 面的发射点后移到派单批准点**：pass 面最初挂在 `check_tool_first` 门内，
   被 #754 既有钉子（test_heartbeat_bootstrap：被拒派单的账本零事件——lifecycle 静默契约）
   打红。定案：reject 面留在门内（toolfirst 自己的裁决行，任何后续门拒绝与否都真实）；
   pass 面移到 `pre_check` 全门通过后经 `toolfirst_pass_record` 发射 + 落 label——账本行
   只描述真实派单，与 #461 dispatch 行同帧同语义。被更晚的门（agenttype 等）拒绝的派单
   不产 toolfirst 行（与 dispatch 行的缺席一致，#881 聚合面无损）。
2. **operation label 关键词口径**：payload/label 的 keywords = 文本中实际命中且映射到被引
   用工具的关键词（`decode the crypto blob` + `tool-catalog: crypto-tool` → `crypto`），
   非"该工具的全部关键词"——归因忠实于本次派单文本。
3. **资产面刷新两次触发**：`--write` 之后的任何代码编辑都会使 deploy digest 过期
   （test_deploy_lifecycle_783 抓住）；按计划顺序陷阱重刷 ext-scan → --write → --verify 后绿。

## What Changes

1. `scripts/emit_gate.py` 双向门（正向宽网孤儿扫描 + 反向严网未注册扫描）+ CI 挂载
   （tests/test_emit_gate_880.py：干净仓绿 / 人造孤儿红 / 人造未注册 literal 红 / tool_call 放行）
2. toolfirst 双面落盘：`toolfirst_pass`/`toolfirst_reject` 词注册 + `_toolfirst_evaluate`
   归因 payload + operation label 存 claim 属性（round-trip 测试钉）
3. 结算 emit：`claim_settled` 词注册 + register_proven_gate.emit_settlements +
   write_guard ALLOW 路径挂载（字段齐 + trace_id 断言）
4. lessons 接线：record_citation ← record_analysis lesson-hit 面；record_burn ← 结算负样本面
   （计数器 +1 测试钉）
5. `tool_call` 真实发射者：post_check claim 粒度（scan_actual_tools + worker 条目回读）

## Impact

- scripts/event_taxonomy.py（+4 词：claim_settled / tool_call / toolfirst_pass / toolfirst_reject）
- scripts/emit_gate.py（新）、scripts/register_proven_gate.py（+emit_settlements）
- scripts/failure_analysis_gate.py（record_analysis +citation 面）
- hooks/worker_budget_gates.py（_toolfirst_evaluate + label 写入器）、
  hooks/worker_budget_sinks.py（pre_check 挂 label / post_check 挂 tool_call）、
  hooks/write_guard.py（ALLOW 路径挂结算）
- tests/test_emit_gate_880.py（新）+ 既有测试文件内钉子
- deploy_manifest：新增 scripts/emit_gate.py → 资产面变更（ext-scan → --write → --verify 顺序）
