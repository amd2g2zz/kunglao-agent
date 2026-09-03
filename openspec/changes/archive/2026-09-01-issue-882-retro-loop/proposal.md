# issue-882 — 回溯环宿主与座舱：三触点 + 四产出 + plan_reviser 接线 + 座舱三字段

## Why

RC3 终点：plan_reviser / plan_stages 孤儿、kunglao-decide CALLERS: NONE（悬空）——
"回溯观察 → 优化当前计划"断在修订步。基线已含观测链全产出（#879 trace 身份 /
#880 观测出生 / #881 聚合器 / #883 statusline 快照面），本卡把三触点挂上、四产出
接通、kunglao-decide 复活，并把座舱三字段送进 statusline。**修订提案不自动执行**
（宪法隔离：replan 决策留 orchestrator——issue 自身的架构约束，全程保持）。

## Recon（前置探索产出，2026-09-02，基线 2681a2d = dev，feat/882-retro-loop）

### 锚点表（计划锚点 vs 实测）

| 目标 | 计划锚点 | 实测锚点（本分支 2681a2d） |
|---|---|---|
| 触点① dispatch 契约组装处 | dispatch 前注入"前车之鉴" | hooks/dispatch_gate.py `main()` :1052-1176；ALLOW 收尾链 = `_top1_enforcement` :1159 → `_capability_guard` :1162 → trace_allocated :1171 → `_log_strategy_dispatch` :1175；additionalContext 注入先例 = failure-blocked :1131-1145（print JSON + return 0，不阻塞）；#879 `_resolve_dispatch_trace` :431 / :1123 |
| 触点② register_proven_gate 转换检查 | 结算回放 | scripts/register_proven_gate.py:273 `emit_settlements`（结算面；调用方 = hooks/write_guard.py:488-503 CARRIER_REGISTER ALLOW 路径，"the write passed every gate and WILL land"）；负样本 lesson burn 先例 `_burn_lesson_lineage` :250-261（fail-open 挂法镜像）；结算行 detail=JSON {"from","to","tools","outcome"}，仅 to∈TERMINAL |
| 触点③ heartbeat_tick 门控 | 策略回溯门控 | scripts/heartbeat_tick.py `main()` :196-356；#883 快照挂法镜像 = :337-344（`import statusline_snapshot; _sls.write_snapshot(ws)` try/except fail-open，"快照永不打断 tick"）；advisory step 先例 = rollup_sweep :264 / think :271（`report[...] = run(script, ws)`，recorded never weighed into rc） |
| plan_reviser 现行接口 | 挂入而非重写 | scripts/plan_reviser.py：`run_checks(ws)` :227（blocker/assumption/cost 三触发，suggest_revision 流）+ `append_revision` :239（`--apply`，本卡**绝不调用**）；exit 3 = suggestions exist |
| plan_stages 现行接口 | plan_review ritual 门 | scripts/plan_stages.py：`should_review(ws, rounds_since_review=0, k_threshold=6)` :200（docstring 自证"供 convergence/heartbeat 调用的纯 API"）；`review()` :113 = 裁决三落盘（orchestrator 专属，本卡不调）；verdict 文档 glob = `runs/plan-review-*.md` :184（agenda 文件名必须避开该 glob） |
| kunglao-decide 现行接口 | 悬空复活 | scripts/kunglao-decide.py：`decide(ws, scan_text)` :118 → {decision, exit_code 0-4, top_actions, explore_mode, ...} 纯只读；文件名带连字符 → 常规 import 不可行，挂入走 subprocess `kunglao-decide.py <ws> --json`（heartbeat_tick.run 同款）；`decide_fail_open` 已有 #569 audit 面 |
| hypothesis_store 写入接口 | #868 生命周期 | scripts/hypothesis_store.py `HypothesisStore(ws/"hypotheses")`；`create(h)` :130（id 冲突 raise FileExistsError）；`Hypothesis` dataclass :65（id/claim_id/competitor_group/candidates/predicted_observation）；id 惯例 `H-<NNN>`（hypothesis_seeder._next_free_id :49）；幂等惯例 = body marker（`pq:<qid>` 先例 :34） |
| cockpit_summary 注入点 | 座舱三字段 | scripts/tuition_curve.py:140 `cockpit_summary(ws)`（heartbeat_tick :324-335 每 tick emit `cockpit_sample`） |
| statusline 快照注入点 | #883 已建 | scripts/statusline_snapshot.py：PROBES 注册表 :109-147 两个 inert slot——`unattributed_rate` :137 / `backtrack_lag` :142（"declared-but-inert … wait for #879/#882 data sources"，#882 即本卡）；registry-driven executor `_make_run_probe` :306（probe fn 按 `entry["probe"]` 名查 globals，声明即接入零 writer 改动）；`build_snapshot` :512 返回 dict（additive 字段安全：test_schema_shape 只 assert 必须 keys ⊆） |
| 未归因率数据源 | #879 已落 | scripts/kunglao_log.py:352 `unattributed_rate(ws)` → {rows, attributed, unattributed, rate}（docstring 自证"the cockpit '未归因率' field's data source (#882 downstream)"） |
| (scene,operation) 词汇 | #880/#881 | scene = scripts/tool_tiers.py:61 `scene_for(ws)`（task_spec 平台嗅探）；operation = claim 属性 `operation:`（hooks/worker_budget_gates.py:884 `set_claim_operation` 写入）；未标注口径沿用 tool_value.UNLABELED = "(unlabeled)" |
| stall 指纹 | #634 | scripts/mission_stall.py:28 `stall_mission(ws)` → {stalled, consecutive_flat, k, open_claims, v_m} 纯只读 |
| 假成功检查数据 | PQ 覆盖 | scripts/mission_ledger.py:110 `update()`：PROVEN claim 的 `answers_question` → PQ answered/coverage 1.0——结算瞬间可检"claim PROVEN 但 PQ 覆盖未动"= claim 无 answers_question 或其 PQ state != answered |
| EMIT 词表 | #459 | scripts/event_taxonomy.py:154-242 EMIT_ACTIONS（sorted+unique 锚定 tests/test_event_stream_adoption.py，新词按字母序插 `renew` 与 `rho_checkpoint` 之间） |

### 镜像样例（file:line + 关键片段）

- fail-open 观测挂法：register_proven_gate.py:250-261 `_burn_lesson_lineage`（try/except Exception: pass，"never blocks settlement"）——触点②的两处新挂照抄此姿态。
- tick advisory 挂法：heartbeat_tick.py:264 `report["rollup_sweep"] = run("rollup.py", ws, "--sweep-terminal")` 与 :337-344 #883 快照挂法——触点③照抄。
- additionalContext 注入：dispatch_gate.py:1131-1145（`print(json.dumps({"hookSpecificOutput": {...}}, ensure_ascii=False))` + return 0）——微回溯块同形状，但**不提前 return**（ALLOW 收尾链必须走完），插在 `_capability_guard` 通过后、`trace_allocated` 行之前。
- probe 声明即接入：statusline_snapshot.py:306-333 `_make_run_probe`——两个 slot 补 probe fn + threshold + staleness_budget + enabled=True 即自动执行。
- 零噪声契约（#754）：无教训不注入（微回溯仅当同 key 有结算史时产出块）。

### 基线测试绿（变更前）

- tests/test_observability_birth_880.py + test_statusline_health_883.py +
  test_event_stream_adoption.py + test_register_proven_gate.py +
  test_tool_value_881.py + test_mission_stall_634.py +
  test_write_guard_register_gate_819.py → 118 passed
- tests/test_trace_identity_879.py + test_plan_stages_822.py +
  test_dispatch_contract.py + test_dispatch_background_704.py → 55 passed

### 偏航与契约更新（无 RECON-DEVIATION，均为预期内）

1. **#883 slot 测试按其自述演进**：test_statusline_health_883.py:139-149
   `test_v1_probes_and_slots_present` / `test_slots_never_execute` 自注
   "slots declared but inert until #879/#882 land"——本卡即 #882 落地，两测更新为
   enabled=True + 执行断言；registry 完整性/staleness_budget 守卫测原样保持并继续生效。
2. **kunglao-decide 挂入形态**：文件名含连字符不可常规 import（实测无任何既有
   import 方），策略回溯经 subprocess `kunglao-decide.py <ws> --json` 挂入——
   调用图证据 = heartbeat_tick → backtrack_loop --policy → kunglao-decide。
3. **agenda 文件名**：`runs/retro-agenda-<ts>.md`（避开 `plan-review-*.md` verdict
   glob，plan_stages.py:184；否则盘点史文档扫描会混入议程）。

### 实现级决定（§0.2 允许的 worker 实现自由，WHAT/WHY 记录）

- **微回溯 O(1) 面**：结算面维护 `runs/.retro-index.json`（(scene,operation) →
  最近 K 条滚动条目）+ `runs/.retro-state.json`（回溯滞后计数）。dispatch 前只读
  小索引文件（O(1)-ish 有界），不扫全账本——issue 的"O(1) 查"语义。
- **策略回溯门**：滞后 ≥ N(=5) ∨ `mission_stall.stall_mission().stalled` ∨
  `plan_stages.should_review().due`（三触发即 issue 的每 N 结算 / stall 指纹 /
  plan_review ritual）。
- **四产出**：① 结算行（#880 已落，本卡消费）② `runs/<ts>-retro-<claim>.md`
  （trace 子图局部回放 + 假成功标记）③ 模式报告+假设种子（回放/议程内的
  失败签名统计 + HypothesisStore.create，body marker `retro:<scene>|<operation>`
  幂等）④ 修订提案（plan_reviser.run_checks + drift 报告 + decide 输出 →
  议程 `PROPOSAL:` 行；**不调 --apply，不调 plan_stages.review**）。
- **座舱三字段**：`tuition_curve.cockpit_summary` 增 `backtrack` 段
  {backtrack_lag, unattributed_rate, pending_proposals}；statusline 快照增同名段 +
  两 slot 探针上线（unattributed_rate > 0.30 WARN / backtrack_lag > 8 WARN）。
  提案待审数 = 晚于最近 `plan_review` 账本行的议程文件中 `PROPOSAL:` 行数
  （纯只读推导，review 落判后自然归零，不写消费耦合）。
- **新资产登记**：scripts/backtrack_loop.py → scripts/README.md + deploy_manifest
  --write/--verify（#881 先例）。

## 范围

见任务清单 tasks.md。宪法隔离不变量：本卡所有代码路径**只生成提案/议程/种子，
绝不执行 replan**（不调 plan_reviser --apply / plan_stages.review / 不改
dispatch 决策）。

## Impact

- 触点文件：hooks/dispatch_gate.py（+微回溯注入）、scripts/register_proven_gate.py
  （结算面挂 record+retro）、scripts/heartbeat_tick.py（+策略回溯 step）、
  scripts/tuition_curve.py（cockpit +backtrack）、scripts/statusline_snapshot.py
  （slot 上线 + backtrack 段）、scripts/event_taxonomy.py（+2 词）。
- 新文件：scripts/backtrack_loop.py、tests/test_backtrack_loop_882.py、
  openspec/changes/issue-882-retro-loop/。
- 消费者不受影响：所有新面 fail-open；结算/gate/tick 的 rc 契约逐字节不变。
