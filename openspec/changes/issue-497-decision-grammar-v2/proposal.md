# 决策语法 v2 — 宪法校准 + 判死/搁浅陈述句门 + 计划白名单与 drift 翻转 (#497)

## Why

Issue #497(父 issue #498 架构声明,E 类"决策语法残缺"落地件)。v0.1.1 现场
同一任务出现两个反向失调极:轨迹1 = 提前宣告失败(瞬态 spawn 超时 ×2 即判
"这条路走不通");轨迹2 = 有方案却停下等人(里程碑总结 + "下一步: ..." 之后
零工具调用)。用户原话:以前说过但又犯了。

机制根因(代码证据):

- **硬错误路由死锁**:三态宪法把"有界授权内新硬错误"路由到 must-ask
  (`references/agent-three-state-charter.md` 授权边界行 + `scripts/
  ask_for_direction_gate.py` TYPE_D 的 `new blocker|encountered blocker`
  tripwire),与硬禁止#1(不 mid-iteration 反问 user,无条件)死锁 — 唯一
  双赢出口是把 blocker 改写成失败宣告:两个门都不响,任务安静死亡。
  **判死宣告 = 绕过门禁的语法**。
- **执法全在问句语法层**:Type A/B 模式、redirect 计数都只看问句;复发的
  两个行为是**陈述句** — "这条路卡死了"(判死)与"下一步: ..."(计划搁浅,
  字母合规精神违规)。
- **白名单方向反**(`rules/kunglao-convergence-loop.md` 与 `skills/
  kunglao-agent/SKILL.md` 硬禁止#4):无新信息的叙事转向(轨迹1 的 6 次)
  该拦没拦;新证据落地后计划不重推导(真 drift)该更新没更新 —
  `scripts/plan_drift_detector.py` 查的是计划与 DAG 形式一致,一份完美
  符合过时 DAG 的计划得满分。

## What Changes

- **宪法校准 v2**:三态表"有界授权内新硬错误"从 must-ask 改为 **allowed +
  强制走梯**(先走 method-ladder / env-ladder);仅"工具/资源耗尽(梯爬完)"
  保留 must-ask。`ask_for_direction_gate` 的 TYPE_D blocker tripwire 加前置:
  分析记录/claim 上须存在**梯耗尽标记**(复用 #495 已落地字段:
  `analyses/failure-<C-NN>.yaml` 记录 `candidates` 为空 且 对应 claim
  `promotion_attempts >= 3`)才 HARD_PAUSE;否则降为 rc=1 指引"走梯后复评"。
- **判死 tripwire(陈述句门,TYPE E)**:"这条路走不通/无法继续/此路不通/
  行不通/卡死/dead end/cannot proceed/no viable path"类宣告(zh+en 双语,
  tripwire 非穷尽声明照旧)→ 无障碍 REFUTED / 能力证伪证据(检查 #495 升格
  obstacle claim 状态或 failure_analysis 记录 outcome)时 rc=1 强制走梯
  复评,不得作为终局;有证据则放行(合法终局)。
- **plan-stall 检测(陈述句门)**:输出含"下一步:"/"next step:"且同一
  self_redirects/事件流里无后续工具动作记录(实现:`plan-stall-decl` /
  `tool-action` 两类事件做轮次窗口)→ 按 Type B 等价处理(rc=1,指引
  "执行该下一步或声明阻塞原因")。
- **白名单与 drift 语义翻转**:硬禁止#4 白名单文本(rules 与 SKILL.md 两处
  载体)加第 4 触发"新能力/障碍事实落地",并把"不因单失败重规划"细化为
  "不因无新信息的转向重规划";`plan_drift_detector` 增
  STALE_PLAN_ON_NEW_EVIDENCE 检测 — 自上次 plan mtime 后有新
  failure_analysis 记录/新升格 obstacle claim 落地而计划未更新 → WARN
  (先观察级,不计入 drift 退出码,不 HARD)。

## Impact

- **代码**:`scripts/ask_for_direction_gate.py`(TYPE_D blocker 拆组 + 梯耗尽
  前置 + TYPE_E + plan-stall)、`scripts/plan_drift_detector.py`(WARN 级新
  漂移类)。不改 failure_analysis_gate(#495 领地,只消费其字段)、不改
  dispatch_gate / kunglao-decide(外部只消费 `find_violations`,不受影响)。
- **文档(单源保持)**:`references/agent-three-state-charter.md` 三态表 v2
  (授权边界行改态 + 新增判死/搁浅两行 + Type E 字母 + 变更记录)——
  charter 仍是唯一"何时问用户"引用源,不新增第六决策面;
  `rules/kunglao-convergence-loop.md` 与 `skills/kunglao-agent/SKILL.md`
  硬禁止#4 白名单文本。
- **行为面(有意收紧,允许面)**:TYPE_D blocker tripwire 触发条件收紧
  (无梯耗尽标记 → rc=1 而非 rc=2);新增两类陈述句拦截。既有 Type A/B/C/D
  (identity/scope)/S 全部原测试不动语义 — `test_authorization_boundary_
  new_hard_error` 仍 rc=2(其文本同时命中 scope-change tripwire,该组未动)。
- **不做**(见 design.md R1-R6):不做判死宣告的语义级 NLU(机械层只做
  tripwire + 结构化证据检查);plan-stall 不接入真实工具调用遥测(以
  self_redirects 事件流为唯一轮次源);drift WARN 不改既有 6 类漂移的
  退出码语义;不动 convergence_check / priority*(其它 issue 领地)。

需求源: issue #497 (github.com/amd2g2zz/kunglao-agent/issues/497)
架构约束: issue #498 "目标架构"(白名单翻转语义:模型没变却偏离才需要理由;
模型变了而不改计划才是 drift)
