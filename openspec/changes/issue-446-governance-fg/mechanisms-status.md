# mechanisms-status.md — SKILL.md MUST 条款 ↔ 实现状态台账(#442 收尾 DoD 输入)

> 目的(#446 G 类 / issue 评论区 2026-08-19):SKILL.md 的 MUST 哪些已
> 生效、哪些是愿景,读者可区分。判定 = 机械 grep 佐证(命令可重跑,
> "我确认过"不是证据)。基准:worktree `v012/issue-446-governance-fg`
> @ GREEN(2026-08-20),基线 origin/dev@59806b9。

图例:**implemented** = 有机械执行器且 grep 命中;**partial** = 执行器
存在但覆盖面/接线不完整;**pending** = 无执行器(grep 空),纯声明。

## Phase 1 Activate / 心跳链

| MUST(出处 skills/kunglao-agent/SKILL.md) | 状态 | 机械佐证 |
|---|---|---|
| `--wire-up` before first dispatch(init 自举) | implemented | `grep -n "wire-up" scripts/kunglao-init.py` → :1451,1469,1491;`hook_activation.py --wire-up` 子命令在位 |
| `--reconcile` every tick(zombie `[active_workers]` 自愈) | implemented | `scripts/heartbeat_tick.py:164` 每 tick 跑 `hook_activation.py --reconcile`;`hook_activation.py:656` GROUND-TRUTH 语义 |
| `--renew` every 30 min(TTL) | implemented | `scripts/hook_activation.py:30,35` + heartbeat_tick renew 步;init :1625-1628 注释声明 |
| `--heartbeat-on` + `heartbeat_loop_prompt.py` before first dispatch;缺/过期 heartbeat 拒绝派发 | implemented | `hooks/worker_budget.py:1349` `check_heartbeat_alive`、:1549 接入 pre_check |
| cron 注册验收 HARD(`heartbeat_loop_prompt.py --verify`) | implemented | `scripts/heartbeat_loop_prompt.py:14,28`(#461);`kunglao-init.py:1476,1497` 调用 |
| oracle backfill(task-oracle.yaml 未回填 → completion gate 无输入) | implemented | `scripts/heartbeat_tick.py:116,130,176`(`oracle_registered` + marker 检测);`scripts/completion_gate.py:23,110` |

## Phase 2 Dispatch Loop / 派发契约

| MUST | 状态 | 机械佐证 |
|---|---|---|
| convergence check first, every turn(决策=命令) | implemented(脚本面) | `scripts/convergence_check.py` 在位;决策表 exit 1-4 语义见 rules/kunglao-convergence-loop.md §3。行为遵守属会话层,无机械执法 — 与 #498 双轨迹重演验收对接 |
| plan-to-execute(`runs/plan-CNN.md` 缺/空壳 → REJECT) | implemented | `hooks/worker_budget.py:826-855` plan gate |
| `facts-snapshot:` 必带(§1c) | implemented | `hooks/worker_budget.py:1297-1298,1584` HARD-REQUIRED |
| `tool-catalog:`(命中 tools/_INDEX.yaml 必须) | implemented | `hooks/worker_budget.py:891-1017` toolfirst gate |
| specialist-first(route_capability + `agent-reasoning:` 偏差) | implemented | `scripts/route_capability.py`(`def main` :458);`hooks/worker_budget.py:1027,1098,1124` |
| ≤3 并发 / promotion_attempts<3 / intended_tools⊆constraints / deadline / tier gate | implemented | `hooks/worker_budget.py:27`(MAX_WORKERS=3)、:648-649;budget 检查族 |
| VM-ONLY 动态工具(HOST_FORBIDDEN_TOOLS,硬禁 #5) | implemented | `hooks/worker_budget.py:45`(常量)、:687(pre_check 拒绝) |
| self-cap-safe 派发(时间帽措辞拒绝) | implemented | `hooks/worker_budget.py:306` `detect_self_cap`、:758 接入 |
| 隔离 first(禁 agent teams) | implemented | `scripts/env_check.py:60`(FLAG_NAME,① HARD 语义) |
| `resume` 子命令(idempotent continue) | **pending(#466)** | `grep -n "resume" scripts/kunglao.py skills/subcommands.yaml` → 0 命中;SKILL.md :93 已声明。#466 在 v0.1.2 泳道波 5 |
| 动态派发需 static-gap 清单(five-layer ③) | partial | hooks/worker_budget tier gate 拦 T2/T3,但 "static-gap list in prompt" 无显式 marker 检查(grep static-gap → 0) |

## Verify / 完成交易

| MUST | 状态 | 机械佐证 |
|---|---|---|
| L1 机械复现(kunglao-verify.py)先于 L2 | implemented | `scripts/kunglao-verify.py` 在位(malware-veri-notes 域) |
| L2 redteam BLIND,无 sign-off 不 PROVEN | implemented | `scripts/blind_gate.py` + agents/kunglao-redteam(BLIND 输入契约) |
| expected-anchor 溯源(F3 禁自算) | implemented | `check_expected_anchor_source` lint(`scripts/kunglao_verify.py`;回归 tests/test_issue238_role_contracts.py) |
| cross_workflow 采样(F6) | implemented | redteam_verdict / lint WARN(SKILL.md :222 声明,lint_facts/kunglao-verify 链) |
| CONVERGED 两段式(零矛盾/零未消费发现/PROVEN 溯源) | implemented | `scripts/convergence_check.py` + `scripts/completion_gate.py`(重算,非自报) |
| calibration gate 交付前 | implemented | `scripts/calibration_gate.py` 在位 |
| §6.3 closeout checklist(5 items)机械执行器 | **pending(口径:prose-only)** | grep closeout/checklist 于 scripts/ → 仅 heartbeat_loop_prompt.py 文本;无 checklist 脚本。列入 #498 收尾候选 |
| handoff-check PASS 判交付 | **pending(部分)** | `grep -rn handoff scripts/*.py` → 无 executor;最接近 = completion_gate(CONVERGED 事务面)。SKILL.md :137,:252 依赖它 — **声明了不存在的门**,#442 收尾必须处置(补 executor 或改口径) |
| teardown `--heartbeat-off`(未收敛 teardown 拒绝) | implemented | `hook_activation.py --heartbeat-off` + heartbeat alive 检查复用 |
| release receipt + downstream 契约 | implemented | `scripts/release_receipt.py` 在位;`.github/workflows/release-check.yml` 调用 `--check` |

## 遇阻决策面(F 类对照,本件只锚不合并)

| MUST | 状态 | 机械佐证 |
|---|---|---|
| 三态宪法为唯一引用源(硬禁 #1) | implemented | `references/agent-three-state-charter.md`(v2 #497);`scripts/ask_for_direction_gate.py` Type A/B/D/E/S + plan-stall(:39,182);**本件加机器锚**:`tests/test_decision_surface_anchor.py` 锁 `error_response.py._CHARTER_STATE` ↔ charter 互指 |
| 错误响应分类taxonomy 四响应 | implemented | `scripts/error_response.py`(9 类 × 5 表)+ `references/error-response-taxonomy.md`;类名锁步入 test_decision_surface_anchor |
| 判死/搁浅陈述句门(Type E / plan-stall) | implemented | ask_for_direction_gate.py:182(#497) |
| 失败转导三产物(#495) | implemented | `scripts/failure_analysis_gate.py`(validated_capability / identified_obstacle / 升格 claim) |
| 失败教训库检索自动跑 | implemented | `failure_analysis_gate.py:350` method-ladder rung 1 自动 similar_lessons;**本件补文档面**(_INDEX.md lessons/ 行 + SKILL.md pointer) |

## 治理面(本件新增)

| MUST | 状态 | 机械佐证 |
|---|---|---|
| 门数派生不复制(写作层) | implemented(本件) | Gate 7 `devkit/doc_sync.py`;`tests/test_doc_sync.py`(计数声明扫描 + 模板门列表 == 注册表-{2}) |
| references 编辑必须同 commit 重钉 | implemented(本件) | doc_sync 子检查;RED/GREEN 见 tasks.md §3-4 |
| 新机制三件套登记 | partial(本件:WARN 前哨) | doc_sync 子检查 WARN;**硬门 + mechanisms.md 总账 = pending**,挂 #498 收尾(issue #446 验收第一条) |
| 行号引用清零(验收第二条) | pending | 本件零新增(锚全符号化);存量清零未做(grep `\.py:[0-9]+` 于注释/docstring 仍有命中,如 recall_inject.py 头注)— 另立 PR |
| 合并/退役样板 PR(验收第三条) | pending | 未见退役 PR;活性单源台账已建(design.md §D7),合并 PR 排 #498 后 |

## 汇总(由上表逐行机械派生 — 改表后必须重算;两处数字不相等即缺陷)

- implemented:30 项;partial:2 项(static-gap marker、三件套 WARN 前哨 — 其硬门与 mechanisms.md 总账挂 #498,见该行佐证列);pending:5 项(resume #466、§6.3 机械 checklist、handoff-check executor、行号引用存量清零、退役样板 PR 合并)。
  复算:`grep -n "^|" mechanisms-status.md` 按状态列计数 = 30 implemented / 2 partial / 5 pending(2026-08-20 F2 修正:原汇总 24/3/5 手写失同步,所列 partial 第三项 smart-ping 无对应表格行 — smart-ping 协议归 Phase 1 心跳链行(implemented),不再单列)。
- **给 #442 的三个硬缺口**:handoff-check(声明不存在的门)> resume(#466 在途)> §6.3 checklist(prose-only)。
