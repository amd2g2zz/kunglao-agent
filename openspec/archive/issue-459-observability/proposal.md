# Observability Event-Stream Adoption — kunglao_log 统一事件流收编决策点 (#459)

## Why

Issue #459(v0.1.2 wave 5,挂靠 #498 决策循环一体化的 **Observe 器官**):
#287 建了统一事件日志 `runs/logs/kunglao-*.jsonl`(`kunglao_log.emit`,
唯一 sink),但覆盖是局部的——决策与执法核心大面积零日志:

- 每轮 DECISION 之外的决策面全静默:ask_for_direction_gate 拦下 TYPE A-E
  判定无人记录;dispatch_gate 的 #496 两颗牙 REJECT 时只有 stderr;
  plan_drift_detector 第 7 类 WARN 只 print。
- 失败侧只有 `failure_blocked` 一个词:#495 三产物落地(record 成功)与
  三产物缺失(BLOCKED 的 missing_artifacts)都不进事件流 — Orient 层
  (#498)没有输入(2026-08-19 挂靠评论明确要求)。
- "诊断不可解释"(issue 证据 3):卡死事故重建靠 status 尾行 + mtime +
  vmware.log 三方拼图 40 分钟;事后没有任何单命令能回答"最近发生了什么"。

## What Changes

- **① 决策点收编**(全部 fail-open,决策行为零变化,只加观测):
  - `scripts/convergence_check.py` 每轮 DECISION:复用既有 emit 面
    (action=`converge`),detail 补计数(open/partial/slots/workers)。
  - `scripts/ask_for_direction_gate.py` 拦截面:TYPE A-E 判定 + rc 入流
    (`ask_back`/`must_stop`/`must_ask`/`ladder_required`/
    `death_verdict_rejected`/`plan_stall`,exit=rc)。
  - `hooks/dispatch_gate.py` `_top1`/`_capability` REJECT 面:`top1_reject`
    / `capability_reject`(#496 已有 excused 侧 `priority_deviation` /
    `capability_switch`,补齐 REJECT 侧)。
  - `scripts/plan_drift_detector.py` 第 7 类 WARN:
    `stale_plan_on_new_evidence` 逐条入流(WARN 永不改 exit code)。
- **② 失败事件**(#495 落地面):
  - `failure_analysis_gate --record` 成功 → `analysis_recorded`
    (detail 含 source + candidates 数)。
  - 三产物缺失 BLOCKED → `analysis_blocked`(detail 含 missing_artifacts);
    纯 stale-coverage BLOCKED 保留原词 `failure_blocked`。
- **③ 诊断闭环**:`kunglao_log.py` 新增只读 CLI `--tail <ws> [N]`
  (默认 20,跨全部日期文件取最近 N 条,JSON lines 输出)—
  "诊断不可解释"的最小解。
- **④ 受控词表**:`scripts/event_taxonomy.py` 新增 `EMIT_ACTIONS` —
  全仓 emit action 字段的唯一词表(既有 7 词 + 新 11 词);CI 锚测试
  扫描 scripts/ + hooks/ 的 action 字面量,违例即红。
- **⑤ 禁零日志回归锚**:`tests/test_event_stream_adoption.py` —
  上述每个决策点触发时 ≥1 事件(seam 级 monkeypatch emit 计数 +
  hook 侧 subprocess 验真实文件);emit 抛异常时各面 rc 不变的
  fail-open 锚。

## Impact

- **代码**:`scripts/event_taxonomy.py`(EMIT_ACTIONS 词表)、
  `scripts/kunglao_log.py`(tail + CLI)、`scripts/ask_for_direction_gate.py`
  (拦截面 emit)、`hooks/dispatch_gate.py`(REJECT 面 emit)、
  `scripts/plan_drift_detector.py`(WARN emit)、`scripts/failure_analysis_gate.py`
  (record/blocked emit)、`scripts/convergence_check.py`(detail 增强)。
- **测试**:`tests/test_event_stream_adoption.py`(新)、
  `tests/test_kunglao_log.py`(--tail 契约)。
- **不做**:不新建第二日志通道(kunglao_log 是唯一 sink);不动
  self_redirects.jsonl(#447 违规计数器,dispatch_gate 注释明令不污染);
  不动 decide() 的 .convergence_ledger.jsonl 侧信道;不做 log_query.py
  全功能查询接口 / tags / pandas/duckdb(issue 验收的后续切片);
  不改任何决策点的判定逻辑与退出码。

## 关联

需求源 issue #459 · 总纲 #442 · 架构脊柱 #498(Observe 器官)·
前作 #287(统一日志)· 同波 #461(dispatch 事件已入流)·
#495(三产物)/#496(两颗牙)/#497(TYPE A-E)的落地面收编。
