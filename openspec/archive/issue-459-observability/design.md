# Design — observability event-stream adoption (#459)

## 问题边界

本变更只做"把既有决策/失败面接入既有统一日志 + 一个只读 tail"。明确
不做:决策逻辑改造(判定/退出码零变化)、第二日志通道、log_query 全
功能查询、tags、pandas/duckdb(后续切片)。所有落点复用
`kunglao_log.emit`(唯一 sink,never-raises 契约)与
`scripts/event_taxonomy.py`(词表的家)。

## D1. 受控词表 EMIT_ACTIONS(event_taxonomy.py)

25 类 taxonomy(`ALL_EVENT_TYPES`,classify_workspace 的计数契约,
`test_catalog_has_exactly_25_types` 钉住 25)**不动**——那是"状态分类"
的词表。新增独立常量 `EMIT_ACTIONS`:"写入侧允许说什么"的词表:

- 既有 7 词(先收编事实):`claim_migrate`(kunglao_record)、`verify`
  (kunglao_verify)、`converge`(convergence_check)、`failure_blocked`
  (failure_analysis_gate)、`dispatch`(worker_budget #461)、
  `priority_deviation` / `capability_switch`(dispatch_gate #496 excused 侧)。
- 新 11 词(本变更的面,见 D2-D4)。

CI 锚:测试扫描 `scripts/*.py` + `hooks/*.py` 源码中的
`action="..."` 字面量与 `_emit_trace(ws, "...")` 首参字面量,断言全部
∈ EMIT_ACTIONS(issue 验收"action 字段 100% 来自受控词表,违例即红"
的本切片实现)。emit 本身**不校验**(fail-open 优先,词表是 lint 面
不是运行时门)。

## D2. 决策点收编(全部 fail-open,行为零变化)

| 面 | action | 载荷 |
|---|---|---|
| convergence_check 每轮 DECISION(复用既有面) | `converge` | detail=`<DECISION> open=N partial=N slots=N workers=N`,exit=exit_code |
| ask gate TYPE A/B 违规(rc1/3-strike rc2) | `ask_back` | detail=`types=[A,B] redirects=N`,exit=rc |
| ask gate TYPE S must-stop(rc2) | `must_stop` | detail=`type=S match='...'`,exit=2 |
| ask gate TYPE D must-ask(rc2,含梯耗尽) | `must_ask` | detail=`type=D ...`,exit=2 |
| ask gate TYPE D-blocker 降级(rc1) | `ladder_required` | detail=`type=D-blocker ...`,exit=1 |
| ask gate TYPE E 判死被拒(rc1) | `death_verdict_rejected` | detail=`type=E ...`,exit=1 |
| ask gate plan-stall(rc1) | `plan_stall` | detail=`declaration='下一步:'`,exit=1 |
| dispatch_gate `_top1` REJECT | `top1_reject` | claim + msg,exit=2 |
| dispatch_gate `_capability` REJECT | `capability_reject` | claim + validated/dispatch families,exit=2 |
| plan_drift 第 7 类 WARN(逐条) | `stale_plan_on_new_evidence` | claim=warn.claim_id,detail=fix |

实现形态统一为各模块一个 `_emit_*` 私有 helper:try/except 包住
import+emit(kunglao_record/kunglao_verify 既有姿势),emit 失败只丢
事件不改 rc。dispatch_gate 复用 `_emit_trace`(补可选 exit 参数,
excused 侧调用点不变)。ask gate 的 OK/clean 路径**不**发事件
(拦截面才发,零噪声)。convergence_check 只增强 detail,action/exit
不动(既有事件的消费者兼容)。

## D3. 失败事件(#495 落地面)

- **`analysis_recorded`**:`record_analysis` 成功返回前 emit,detail=
  `source=<next_method_source> candidates=<len(candidates)>` —
  三产物落地事件(挂靠评论:Orient 层的输入)。函数级 emit(非 CLI
  级),直接调用方(测试/orchestrator API)同享。
- **`analysis_blocked`**:`_emit_failure_blocked` 内分流 —
  `missing_artifacts` 非空(分析缺失或产物缺字段)→ `analysis_blocked`
  (detail 含 missing 列表 + attempts);空(纯 stale coverage,
  covers_attempt < promotion_attempts)→ 保留 `failure_blocked`。
  一个 BLOCKED 恰好一条事件,词选择携带原因,不双发。

## D4. --tail 诊断闭环(kunglao_log.py)

`tail(ws, n=20)`:glob `runs/logs/kunglao-*.jsonl` 按文件名(=日期)
排序合并,取最近 n 条;坏行跳过(与 event_taxonomy._read_jsonl 同
容忍度);纯读,不创建不修改任何文件。CLI:`--tail <ws> [N]` 输出
canonical JSON lines(与 emit 同 dumps 形态:sort_keys +
ensure_ascii=False)。错误面 fail-fast:workspace 不存在 / N<1 →
stderr + exit 64(仓库 RC 习惯);无事件 → 空输出 exit 0。

## D5. 测试映射(验收 ↔ 测试)

| 验收 | 测试 |
|---|---|
| 每个决策点触发时 ≥1 事件 | TestAskForDirectionEmit / TestDispatchGateRejectEmit / TestPlanDriftWarnEmit / TestConvergenceDecisionEmit(seam monkeypatch 计数;hook 侧 subprocess + 真实 jsonl 断言) |
| action 100% 受控词表 | TestVocabulary(源扫描 CI 锚 + EMIT_ACTIONS 唯一性/完备性) |
| analysis_recorded / analysis_blocked | TestFailureAnalysisEmit(source/candidates 数;missing_artifacts;stale-coverage 保留 failure_blocked 的分流 pin) |
| --tail 只读 + 默认 20 + JSON lines | test_kunglao_log.py TestTail(跨文件时序 / N 边界 / 只读 guard / rc 契约) |
| emit 失败 fail-open | TestFailOpenEmit(emit 抛异常 → 各面 rc 与正常路径逐位相等) |

## 风险

| Risk | L | I | 缓解 |
|---|---|---|---|
| emit 抛异常改变决策 rc | L | H | 全部 try/except + TestFailOpenEmit 逐面锚定 |
| 词表漏词 → CI 锚误报 | M | L | 源扫描只认 action= 字面量与 _emit_trace 首参;变量传参(无字面量)不误伤 |
| failure_blocked 语义分裂打破旧消费者 | L | M | grep 全仓:无消费者按 action=failure_blocked 过滤日志(decide_anchor 的 failure_blocked 是另一字段) |
| --tail 与写侧并发 | L | L | append-only + 逐行读,坏行跳过 |
