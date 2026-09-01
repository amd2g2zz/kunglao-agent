# issue-878 — 机制调度器：注册表 + 单宿主 tick + 账本事件总线 + 座舱健康段

## Why

机制增殖 = 工具发现面病（#866）的机制层投影：8 个机制入口触发逻辑各自手搓、
无统一"什么在什么时候跑"的答案、无统一健康面。本卡交付 mechanisms.yaml 注册表
（trigger/cost_class/cockpit_signal 三项上线前置，缺一即拒）+ heartbeat_tick 单宿主
调度遍历（廉价门先行、贵机制排队、单 tick time cap）+ 账本事件总线
（settlement/stall/plan_review 事件即触发器）+ statusline mechanisms 健康段。

**宪法约束（全程保持）**：scheduler 只调度**提案类**机制（节奏器，不是新权力中心）；
决策类（replan 应用 / PROVEN 晋升 / 预算豁免）仍走各自既有门。hooks 通道不迁移
（PreToolUse/PostToolUse 是宿主生命周期）；不做分布式/多机调度；不改任何决策权归属。

## Recon（前置探索产出，2026-09-02，基线 57f088f = dev，feat/878-mechanism-scheduler）

### 锚点表（计划锚点 vs 实测）

| 目标 | 计划锚点 | 实测锚点（本分支 57f088f） |
|---|---|---|
| tick 单宿主改造点 | heartbeat_tick 遍历注册表 | scripts/heartbeat_tick.py `main()` :196-365；**advisory 手搓段 = :239-286**（env_state :239 / monitor :244 / feedback :249 / verify_watch :255 / rollup_sweep :264 / think :271-277 / backtrack #882 挂点 :286）；liveness 核心不属机制调度（selfcheck :217 / reconcile :218 / renew :225 / heartbeat-check :226 / oracle :230-232，rc 计权 :288-300+:361-365）；noop breaker :312-331；#873 cockpit :335-344；#883 快照 :348-353 |
| tick 执行 seam | 注入式 runner | scripts/heartbeat_tick.py `run(script, ws, *extra)` :89-102（subprocess timeout=60 + stdout/stderr 尾 300 字符）；三套测试 monkeypatch 此函数钉契约：test_notes_closure_762.py:165-200（"rollup.py"+"--sweep-terminal" 调用必须发生 + report["rollup_sweep"]["rc"]==-1）、test_monitor_wiring_620c.py:31-73（report["monitor"]["rc"]==1 透传 + 不入 rc/alert）、test_cognition_759.py:118-155（think_seat 崩溃不改 action_taken/rc）→ **scheduler 必须接受 runner=run 注入，逐脚本调用名+argv 不变，tick 报告 legacy key 原样保留** |
| #882 策略回溯挂点（迁移源） | backtrack_loop --policy | scripts/heartbeat_tick.py:286 `report["backtrack"] = run("backtrack_loop.py", ws, "--policy")`；门 = scripts/backtrack_loop.py `policy_due(ws)` :340-360（lag>=N ∨ mission_stall ∨ plan_stages.should_review）；内部 kunglao-decide 子进程 :563；--policy CLI :683-711（自带门控，非 due 时 rc0 零噪声） |
| 账本尾部消费惯例 | #883 byte-offset 增量读可镜像 | scripts/statusline_snapshot.py `_ledger_activity` :432-465——`LEDGER_TAIL_BYTES=65_536` :68 + `f.seek(0, SEEK_END)` 定容 + 末 64KB 有界读 :440-444 + 丢弃首条可能截断行 :447-449 + 逐行 json.loads 容错 :452-456；无持久 offset 先例 → 本卡新增有界+持久 offset 混合式（state 文件记 {file, offset}，只读增量完成行，文件截断/换日回退全量重读） |
| 账本行 schema | kunglao_log 事件流 | scripts/kunglao_log.py `emit()` :134-187（ts/actor/action/claim/tool/artifact/duration_ms/exit/detail/trace_id…）；`_all_rows` :190-212（全量读容错）；`log_path` :123-126（runs/logs/kunglao-<UTC 日期>.jsonl 按日分文件）；actor 词表 :57-95（新字面量必须走严格形或 LEGACY_ACTORS——**"mechanism_scheduler" 不入 legacy，emit 用 actor="orchestrator"**，机制调度是 orchestrator tick 循环的机械延伸） |
| 触发事件词 | settlement/stall/plan_review | EMIT_ACTIONS 实证发射者：`claim_settled`（#880 write_guard register 面）→ settlement；`mission_stall`（#634）/`plan_stall` → stall；`plan_review`（#822 裁决面，test_backtrack_loop_882.py:403 实证 emit）→ plan_review；词表注册处 scripts/event_taxonomy.py EMIT_ACTIONS :154-244（sorted+unique，tests/test_event_stream_adoption.py :18 锚定） |
| 机制注册表文件惯例 | mechanisms.yaml 位置+schema 校验 | 数据文件贴 loader 先例 = scripts/tool_tiers.yaml + scripts/tool_tiers.py:25 `_DATA = Path(__file__).parent / "tool_tiers.yaml"`（**不入 deploy-manifest**：manifest 174 条 = scripts/*.py 全镜像，非 py 数据文件不部署，yaml.safe_load 读取）；注册表+守卫测镜像 = scripts/wire_up_settings.py `WIRE_UP_HOOK_FILES` :57-71（registry 为唯一声明源，tests 钉集合等价使漂移变红）+ statusline_snapshot.py `PROBES` :112-152（"不入册不显示；无 staleness_budget 不许上线"守卫测 test_statusline_health_883.py:126-146） |
| 快照段挂法 | #882/#883 镜像 | scripts/statusline_snapshot.py `build_snapshot` :550-626（fail-open try/except 段挂法 :574-580 backtrack 先例；返回 dict additive 字段安全——test_statusline_health_883.py:409 `test_schema_shape` 只 assert 必须 keys ⊆）；探针注册表驱动执行器 `_make_run_probe` :344-371（声明即接入）；PROBES 无数量钉死（:134 只钉结构守卫）→ 新增 mechanisms 段 + mechanism_health 探针零测试破坏 |
| cockpit 健康段数据源 | 每机制 {last_run, next_eligible, drops} | 新 state 文件 runs/.mechanisms-state.json（原子写镜像 backtrack_loop.py `_write_json_atomic` :102-107 tmp+replace）；派生 state dotfile 惯例（recall_metrics/backtrack_loop 同类） |
| 手搓 tick 子进程清单（迁入对象） | 8 入口 + tick 既有 advisory 子步骤 | monitor=kunglao-monitor.py --json（DRIFT_LEDGER 落盘 :44+:93）；feedback=feedback.py --check-stale（**stdout-only，无落盘** :183）；verify_watch=verify_status_watch.py --json（witness 词表 :43）；rollup=rollup.py --sweep-terminal（emit rollup_sweep :310）；think=think_seat.py（等待期自裁决，artifact runs/.think-*.md）；env=env_state_probe.py（runs/env-state.json :56） |
| session_dead 门数据源 | external_kicker 判死函数 | scripts/external_kicker.py `session_is_dead(heartbeat, now, stale_minutes)` :191-209（缺文件=dead；双陈旧=dead）——调度器 --plan 展示面直接 import 复用（D1 判定零重写） |
| loop_unregistered 门数据源 | heartbeat 状态文件 | scripts/heartbeat_loop_prompt.py `verify_loop` :78-136（runs/.heartbeat.json + loop_registered 标记 :101）；heartbeat.py #754 E2 `evaluate_tick_continuity`（连续 tick 判活共享函数） |

### 8 机制入口逐个裁定表（迁移/废弃）

| # | 入口 | 现触发 | 裁定 | 注册表条目（name / channel / trigger{type,gate} / cost / depth） |
|---|---|---|---|---|
| 1 | heartbeat.py | 人工/链式 CLI（register/verify/stop） | **迁入**（声明面；CLI 通道保持） | `heartbeat_register` / cli / manual,always / cheap / session |
| 2 | heartbeat_loop_prompt.py | init/人工（loop 出生） | **迁入**（声明面） | `loop_birth` / cli / manual,loop_unregistered / cheap / session |
| 3 | heartbeat_tick.py | /loop cron 5min | **迁入**（即单宿主本体，host 标记，调度器永不派发自身） | `tick_host` / host / tick,always(host:true) / cheap / session |
| 4 | heartbeat_touch.py | PreToolUse/Bash hook 每次工具调用 | **迁入声明、执行面留在 hooks 通道**（issue 明确排除：hooks 通道不迁移） | `liveness_touch` / hooks / event,always / cheap / session |
| 5 | external_kicker.py | OS schtasks/cron 周期 + 判死门 | **迁入**（声明面；OS 通道保持——会话外机制，宿主=os，D5 注册仍人工一次性） | `dead_session_kicker` / os / tick,session_dead / cheap / os |
| 6 | kunglao-decide.py | #882 起经 backtrack_loop --policy 子进程；人工 CLI | **迁入**（自动调用面已随 `policy_retro` 入调度器；独立 CLI 保持人工） | `decide_cli` / cli / manual,policy_due / expensive / workspace |
| 7 | kunglao-monitor.py | heartbeat_tick :244 手搓（每 tick） | **迁入**（调度器 tick 面） | `workspace_monitor` / tick / tick,always / cheap / workspace |
| 8 | verify_status_watch.py | heartbeat_tick :255 手搓（每 tick） | **迁入**（调度器 tick 面） | `verify_watch` / tick / tick,always / cheap / workspace |

废弃候选：**0 个**——8 入口各有活体消费者（#754 连续 tick 判活 / #461 loop 标记 /
#39 死会话恢复 / #882 DECIDE 悬空复活 / #620 monitor 消费者 / #718 对账），无一是
僵尸机制；裁定全部为迁入（其中 4/5/6 仅声明面入册、执行通道按 issue 排除项保持）。

tick 既有其余手搓 advisory 子步骤同帧迁入（单宿主诚实性：遍历注册表后 tick 内不得
残留机制级手搓触发）：`env_probe`（env_state_probe.py，tick,always，cheap）、
`stale_feedback`（feedback.py --check-stale，tick,always，cheap）、
`notes_rollup`（rollup.py --sweep-terminal，tick,always，cheap）、
`think_seat`（tick,always——等待期自裁决在 seat 内部，门无法廉价外置，
**medium**）、`policy_retro`（backtrack_loop.py --policy，settlement 触发类
events:[settlement,stall,plan_review]，gate policy_due，**expensive**，mission）。

### tick 预算设计确认（time cap + cost_class 排队）

- cost 阶 `cheap < medium < expensive`（yaml `cost_classes` 声明次序即排队优先级）。
- 每 tick：注册表按 cost 升序遍历；gate 廉价评估（状态小文件/事件集判定，零子进程）；
  gate 过 → 预算内则跑（runner 注入，沿用 tick `run()` 60s/步上限），预算尽 → drop
  （reason=budget，drops 计数++，下 tick 仍 eligible）。
- time cap：调度段整体墙钟预算，默认 90s（env `KUNGLAO_MECH_BUDGET_S` 覆盖）——
  廉价六机制常态 <5s 全跑完，expensive（policy_retro 内含 drift+decide 双 30s 子进程
  上限）排尾、预算紧张时最先被牺牲，tick rc 契约零影响（调度段全程 advisory fail-open）。
- gate→runner 双检：policy_retro 过调度器廉价门后才 spawn 子进程（子进程内部门自检
  幂等保留）——"廉价门先行，贵机制门控排队"。

### 镜像样例（file:line + 关键片段）

- 原子写：backtrack_loop.py:102-107 `_write_json_atomic`（tmp + replace）。
- 有界账本读：statusline_snapshot.py:440-444（SEEK_END 定容 → 尾窗读 → 首条截断行丢弃）。
- 快照 fail-open 段挂：statusline_snapshot.py:574-580（backtrack 三字段 try/except 进快照）。
- 注册表守卫测：test_statusline_health_883.py:126-146（enabled 探针必须有 staleness_budget；
  声明即接入）+ test_hook_registry_singlesource（WIRE_UP_HOOK_FILES 集合钉）。
- advisory tick 步：heartbeat_tick.py:264（`report["rollup_sweep"] = run(...)`，recorded
  never weighed into rc）。

### 基线测试绿（变更前）

tests/test_heartbeat_tick.py + test_backtrack_loop_882.py + test_statusline_health_883.py
+ test_event_stream_adoption.py + test_external_kicker.py → **122 passed**（16.4s）。

### 偏航与实现级决定（§0.2 允许，WHAT/WHY）

无 RECON-DEVIATION。实现级决定：

1. **legacy tick 报告 key 原样保留**（monitor/feedback/verify_watch/rollup_sweep/think/
   backtrack/env_state）——三套既有测试以 monkeypatch(run) 钉 key+rc 透传契约，loop
   prompt 消费 action_taken 契约不变；调度器结果按映射回填 legacy key，另加
   `report["mechanisms"]` 完整调度面。WHY：报文契约是既有消费面，迁移的是触发权不是报文格式。
2. **runner 注入**：`run_due(ws, runner=heartbeat_tick.run)`——monkeypatch seam 保留
   （test_notes_closure_762/monitor_wiring_620c/cognition_759 三套钉死调用名+argv）。
3. **失败不叫 drop**：drops 只计"候选未跑"（budget 尽）；rc!=0 是"跑了但失败"
   （last_rc 落 state，mechanism_health 探针可见）。
4. **注册表失效 = fail-closed**：schema 校验失败时调度器整轮拒绝执行任何机制
   （stderr + `mech_reject` emit + report["mechanisms"]["error"]）——"不入册不许跑"的
   反面即"册坏不许跑"。
5. **mechanisms.yaml 不入 deploy-manifest**（tool_tiers.yaml 先例：scripts/ 非 py
   数据文件不部署，随安装树走）；mechanism_scheduler.py 经 --write 全镜像自动入册。
6. **路由器不加子命令**：一条命令 = `python scripts/mechanism_scheduler.py <ws> --plan`
   （--check / --status / --run 同文件），不动 kunglao.py 路由面（blast radius 控制）。

## 明确不做（issue 自身排除项）

- 不迁移 hooks 通道（liveness_touch 执行面保持 PreToolUse/Bash）
- 不做分布式/多机调度
- 不改变任何决策权归属（scheduler 只调度提案类机制；replan/PROVEN/预算豁免各回各门）

## 验收（issue 四条）

- [ ] 8 个既有机制入口全部迁入注册表（或明确废弃）——裁定表见上，13 条目全注册
- [ ] `python scripts/mechanism_scheduler.py <ws> --plan` 一条命令答"什么机制在什么时候跑"
- [ ] statusline 出现 mechanisms 健康段（快照 mechanisms 段 + [mech] 探针码）
- [ ] 新机制上线必须过注册表 schema 门（机械化：validate_registry + 守卫测试，
      trigger/cost_class/cockpit_signal 缺一即拒；调度器只遍历注册表，不入册物理上不可跑）
