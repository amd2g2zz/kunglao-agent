# issue-881 — 工具价值聚合器与消费接线：tool_value.py + β-Bernoulli 档位 + recall rerank

## Why

RC3：反馈环零件 ~70% 已在（#880 刚落：结算行 emit_settlements / lessons 计数器 /
operation label / toolfirst 双面），唯一缺口 = **聚合器**——无物把既有数据面 join 成
计数写进消费面读的表。聚合器与消费接线（tool_tiers + recall）必须**同 PR**落地——
否则聚合器就是下一个 lessons_telemetry（造完、测完、零调用方）。

## Recon（前置探索产出，2026-09-02，基线 a20b701 = dev，feat/881-tool-value）

### 锚点表（计划锚点 vs 实测）

| 目标 | 计划锚点 | 实测锚点（本分支 a20b701） |
|---|---|---|
| 输入 A：tool-catalog 标记 → 结构化落盘 | dispatch 文本 | hooks/worker_budget_gates.py:757-796 `_toolfirst_evaluate`（返回 {mode, keywords, tool}）；pass 面 `toolfirst_pass` 行（detail=JSON，含 claim）:963-975 `toolfirst_pass_record`；reject 面 `toolfirst_reject` 行（**无 claim 字段**，:926-940 `_toolfirst_emit`）；`none` optout=结构化弃用但 **payload 不带被弃工具名**（keywords=[]，:781-784） |
| 输入 B：facts `steps:` per-step tool 条目 | facts F*.md | agents/kunglao-worker.md:182（"hit a candidate but decide not to use it → record the reason in steps:"）+ :185（"per step: tool + command/breakpoint + expected output"）；事实文件 frontmatter 带 `claim_id:`（tests/test_outcome_capture.py:41 既有形状 `---\nclaim_id: C-1\n...`）；计划模板 `goal:/preflight:/steps:/fallback:`（hooks/worker_budget_gates.py:545） |
| 输入 C：结算/outcome | `_runs_outcomes` | scripts/register_proven_gate.py:54-72 `_runs_outcomes`（runs/*.md，`-verify-`/`verify-redteam` 命名约定，走 outcome_capture._parse_run）；行 {claim_id, result, checker}；result ∈ passes/partial/fails（verify）与 CONFIRMED/REFUTED/UNVERIFIED(-WITH-GAP)（redteam），scripts/outcome_capture.py:45-51；结算行 `claim_settled`（register_proven_gate.py:273-333，detail=JSON {"from","to","tools","outcome"}，仅 to∈TERMINAL，scripts/status_defs.py:72） |
| 输入 D：operation label | #880 claim 属性 | hooks/worker_budget_gates.py:884-931 `set_claim_operation`（`operation: kw,kw` + `operation_tool: <tool|none>` 两行，text-surgical 块内插入）；读取面=claim-register.yaml 直接解析 |
| 消费面①签名 | tool_tiers.chain_for/inject | scripts/tool_tiers.py:58-67 `chain_for(scene_key) -> list[str]`（**生产调用方 0，仅 tests/test_tool_tiers_812.py**）；:81-117 `inject_block(scene_key)`（调用方=dispatch_context.py:278-281 经 `inject_for_workspace` :120-125，**该路径已持有 ws**）；链语义=降级链 full→targeted→structured→text（scripts/tool_tiers.yaml:16,74） |
| 消费面②签名 | recall_files | hooks/recall_inject.py:207-218 `recall_files(query, cwd=None, recall_runner=None)`；调用方全集：recall_inject.evaluate :288（带 cwd=ws）+ failure_analysis_gate.py:895-900 `_failure_modes_recall`（**cwd=None**——rerank 天然不影响）；文件行形状 `<path> \| <category> \| ...`（:173-186 `_parse_files`） |
| 工具全量（零使用可见） | tools/_INDEX.yaml | tools/_INDEX.yaml `tools:` 列表（name/category/capability/tier），hooks/worker_budget_gates.py:687-718 `_load_tool_index_keywords` 既有解析先例 |
| 输出表位置/锁惯例 | workspace 文件 | 追加式遥测在 runs/ 隐藏 dotfile：scripts/recall_metrics.py:13 `.recall-metrics.jsonl`（derived 数据不入 workspace manifest 的先例）；锁=进程内 per-path threading.Lock（scripts/kunglao_record.py:156-168）；本表为派生缓存（可整体重算），原子写 tmp+os.replace 即可，无跨进程锁需求 |
| β-Bernoulli 参数 | 蓝图 §8 bandit | 仓库内既有 utility 先例=lessons_telemetry（burn/(citation+1)，#526）——本卡按 issue 明示改 β-Bernoulli（先验=静态 tier），参数 α0=k·p0 / β0=k·(1−p0)，k=4，p0=(T−rank)/(T+1)（chain 内 rank），链外工具 p0=0.5 中性 |

### 四输入可解析性确认（达标要求：各 ≥1 样本过解析）

- A：`toolfirst_pass` 行 detail=JSON {mode:"matched", keywords:[...], tool:"crypto-tool"}——构造样本按 tests/test_observability_birth_880.py:77-95 的 emit 形状落 ledger。**边界（记录）**：`toolfirst_reject` 行无 claim 字段（join 不了）；`optout` 行 tool=None（弃用计数改由输入 B 的 steps 弃用条目承担）。
- B：`---\nclaim_id: C-1\n---\n` + 正文 `steps:` 块（至 `fallback:`/下一顶格键止），步骤行含工具名=选中；含弃用标记词（not used/skipped/放弃/不采用…）=reject。构造样本按 agents/kunglao-worker.md:182/185 文档形状。
- C：runs/2026-...-verify-C-1.md（`## Overall verdict\npasses`，frontmatter claim_id）+ verify-redteam 文件（`RED-TEAM VERDICT: REFUTED`）——复用 outcome_capture._parse_run 实测解析通过（tests/test_outcome_capture.py 既有形状）。
- D：claim-register.yaml claim 块 `operation: xor,crypto` + `operation_tool: crypto-tool`——形状由 tests/test_observability_birth_880.py:169-197 round-trip 钉死。

### 调用方影响面清单

- `chain_for`：生产调用方 **0**；tests/test_tool_tiers_812.py D5 钉 fallback。加可选 `ws=None` kwarg，非破坏。
- `inject_block`：dispatch_context.build_dispatch_context（经 inject_for_workspace，已持 ws）+ tests C1。加可选 `ws=None` kwarg，无表时渲染**逐字节等价现状**（C1 既有断言不回退）。
- `recall_files`：evaluate（cwd=ws → rerank 生效）+ `_failure_modes_recall`（cwd=None → 完全不受影响）。无表/损坏表 → 原序 fail-open；test_recall_inject 既有顺序断言不回退。
- 新资产 scripts/tool_value.py → deploy-manifest 需 `--write` 后 `--verify`。

### 计数模型（utility 口径声明）

- cite=正样本（选中 ∧ claim 存活：verify passes / redteam CONFIRMED / 结算 PROVEN|VERIFIED）；burn=负样本（选中 ∧ 红team 拒/verify fails/结算 REFUTED|NEGATIVE|DEAD）；未结算（partial/UNVERIFIED/OPEN）不计。reject=弃用（steps 弃用条目），**不入后验**（"未选用"≠"失败"，混入即口径污染），只进报表（对接 #866-b retirement）。
- utility=(cite+α0)/(cite+burn+α0+β0)，α0=k·p0，β0=k·(1−p0)，k=4，p0 按静态链 rank=(T−rank)/(T+1)，链外 0.5。零数据 = 纯静态先验（现状语义），计数累积后翻转（bandit 形态）。
- 零使用工具：计数字面全 0、报表显式列出并沉底（有证据工具之后），标 retirement-candidate。

### 偏航

无规格级偏航。实现级选择（WHAT/WHY，§0.2 第 4 条）：
1. 输出表落 `runs/.tool-value.json`（派生缓存，recall_metrics 隐藏 dotfile 先例），消费方只读表（recall 5s 预算内 O(1)），表由 `tool_value.py`（默认/--write）重算——消费面不扫全量源（账本日文件可增长）。
2. reject 不入 β 后验只进报表——issue 的三计数各自独立呈现，utility 只由 cite/burn 驱动（口径可复算）。
3. `_failure_modes_recall` 的 cwd=None 路径零改动——rerank 挂 cwd-aware 槽位，共享路径行为不变。

## What

1. **聚合器 `scripts/tool_value.py`**：`aggregate(ws)`（join 键=claim id；归因=(scene, operation)，scene=tool_tiers.scene_for，operation=claim 属性 `operation:` → toolfirst_pass keywords → "(unlabeled)"）→ (scene,operation,tool) cite/burn/reject + β-Bernoulli utility；`write_table/load_table`（runs/.tool-value.json，schema kunglao.tool-value/1）；CLI：默认重算写表+摘要，`--report`（可 `--operation` 过滤）一条命令回答"该 (scene,operation) 下哪些工具 utility 最高"，`--json` 机器可读。
2. **接线① tool_tiers**：`chain_for(scene_key, ws=None)` = 静态链 + tier 池化计数的 β 后验稳定重排（无表=静态原序）；`inject_block(scene_key, ws=None)` 链序随 chain_for、档内工具按 utility 稳定重排（无表=逐字节现状）；`inject_for_workspace` 透传 ws（生产消费路径=每次 dispatch 契约构建）。
3. **接线② recall_inject.recall_files**：cwd≠None 时读表 rerank（文件路径含注册工具名 → 该工具池化 utility 为排序键；未命中工具的文件中性值、稳定排序保原相对序；任何异常/无表 → 原序 fail-open）。
4. **测试 tests/test_tool_value_881.py**：三输入 join 计数/utility 数值断言、chain 排序随计数翻转、档内工具重排、recall rerank 高 utility 前置、--report 可答+零使用沉底可见、无表/坏表 fail-open。

## 纪律

- 聚合器与接线①②**同 PR**（commit 历史可证）；本地三门绿；CI 绿后停手不 merge。

## Out of scope

- heartbeat_tick 自动重算表（消费面读的是最近一次 `tool_value.py` 落表；自动化宿主归 #878/#882 回溯环卡）。
- lessons_telemetry.utility 公式变更（#880 已声明归本卡消费语义——本卡用独立 cite/burn，不消费该公式）。
- 执行包装器（timeout 硬杀）、Q 表全量消费（#823-P3）。
