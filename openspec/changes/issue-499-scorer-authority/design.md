# Design — scorer authority (#499)

## 问题边界

"Next-claim 评分权威" = live 循环里决定 **WHICH claim next**(decision-rights 第 2 行)
的 scorer 唯一性。判据不是口味,是 spec 血统:specs/phase-4/contract.md §1
landing map 把 DECIDE action ranking 落在 `scripts/priority_ratio.py`(issue #2
VoI-proxy 终版),kunglao-decide.decide() 已在用。**声明的权威 = priority_ratio**;
本变更把 live 消费面与声明对齐。

**不是**本变更范围:
- priority.py 的删除(#446 退役流程,需要 external_kicker/test_rank_claims 迁移);
- golden 冻结面刷新(convergence_check.py:600 DISPATCH action 文本被
  F-01/F-06 golden stdout 钉死,contract 宣告 decide() 输出冻结;改文本=改 golden,
  属于有意的 golden-refresh,放 #446 或 #443 后续);
- #496 top-1 强制(上牙强度);
- #495 三产物类型对接(仅 R6 评估)。

## D1. 权威切换的落点(live 面 = 2 hooks)

live 循环有两个消费排名的面,必须同源,否则同轮矛盾:

| 面 | 现状 | 切换后 |
|---|---|---|
| `worker_pulse._build_pulse` next-up 注入 | subprocess `priority.py --json`,读 `dispatchable[0].{id,score,statement}` | subprocess `priority_ratio.py --json`,读 `[0].{claim_id,score,action}`;caller 侧过滤(见 D2) |
| `worker_budget.check_priority` deviation 审计 | `from priority import rank_claims,_weights` | `from priority_ratio import priority_ratio,EvidenceView`(+retract_claim.TERMINAL_WITH_RETRACTED 预过滤) |

只切 pulse 不切 budget 会出现:pulse 注入 "next up: B"(VoI),orchestrator 派 B,
budget 审计却说 B 偏离了加权 #1 A,要求 reasoning —— 自己的两个 hook 打架,
声明只做了一半。故两处同源切换,一次到位。

**选择直接调 priority_ratio 而非 kunglao-decide CLI 的理由**:pulse 的
decision/flags(W-15、active_blockers、partial)来自 convergence_check 的完整
JSON;kunglao-decide 的组合输出缺 done_artifact_violations/active_blockers,
换 DECIDE CLI 会丢 #444 的 W-15 面与 blockers 面(回退不可接受),且 double-run
cc.decide(ledger 双写)。故保留 cc 调用,仅换 scorer 子进程 —— 与 contract 的
组件语义一致(DECIDE 的 ranker 就是 priority_ratio)。

## D2. caller 侧过滤(contract 明文责任)

contract §1:"failure-blocked filtering is the caller's job(kunglao-decide;
the signature has no ws)"。priority_ratio 纯函数不含该过滤,直接消费会推荐
failure-blocked claim,与 convergence_check 同框输出自相矛盾(v1.9.6 不变量:
"so the two tools never contradict")。两个 caller 各自补:

- **worker_pulse**:cc 输出已有 `failure_blocked`(id 集合)与 `open_claims`
  (register-status 口径的 open 集合)。next-up 取 ratio 队列中第一个
  (不在 failure_blocked)且(在 cc open 集)的 action。后者同时消掉
  RETRACTED 分歧:ratio 的 `is_open` 用 status_defs.TERMINAL(不含 RETRACTED),
  cc 的 `_open_claims` 用 TERMINAL_WITH_RETRACTED — 以 cc(收敛真相面)为准。
- **worker_budget.check_priority**:签名加 `ws=None`;ws 给定时
  (a) `failure_analysis_gate.scan_workspace(ws)` BLOCKED 的 claim_id 剔除
  (与旧 rank_claims 内部行为逐条对齐);(b) `EvidenceView.from_workspace(ws)`
  供 N 项;(c) TERMINAL_WITH_RETRACTED 状态预剔除(对齐 cc 口径)。
  ws 缺省 None → 退化为 EvidenceView() 空(N=1,证据中性),hook 保持可用。

## D3. priority.py 降级 = 声明面,不是行为面

"Deprecated shim" 的机械含义(受"保 import 兼容"约束):

1. docstring:删除 "SINGLE SANCTIONED dispatch ranker" 自我宣告,改为
   DEPRECATED(#499)+ 权威指向 `scripts/priority_ratio.py` + #446 退役流程;
2. 模块常量 `DEPRECATED = True` / `AUTHORITY = 'scripts/priority_ratio.py'`
   (机械可断言面,供防回归测试);
3. **API 逐字节不变**:`rank_claims`/`gate_allows`/`_weights`/
   `DEFAULT_WEIGHTS`/`NEXT_TIER_CHEAP`/`_leverage_v2` 原样保留 —
   external_kicker.py(off-loop)、tests/test_rank_claims.py、
   tests/test_orchestration_priority_cost.py、tests/test_v1_8_enforcement_gates.py
   继续绿。**不做委托改写**(rank_claims 的 row shape{id,score,value,leverage,
   cheapness,novelty,next_tier,outcome,...}与 Action{claim_id,action,score,skill,
   tier,attempts,leverage,discriminator,novelty,cost} 不同构,委托=换语义=
   打破全部既有消费者,属 #446 删除时的迁移,不是本 issue 的"降级")。

不加 runtime DeprecationWarning:worker_budget/测试在 hook 进程内 import 该模块,
warning 走 stderr 会污染 hook 输出通道;声明走 docstring+常量+README/references。

## D4. 指示文本翻面(live 面,additive/一行级)

翻 `priority.py` → `priority_ratio.py`(仅名词替换,句式不动,SKILL.md 冲突热点
纪律 — #461 同波但编辑区不重叠):

- skills/kunglao-agent/SKILL.md:149,159,193,269,272,284,298(193 行的公式
  描述同步换 VoI 口径);
- rules/kunglao-convergence-loop.md:11,31,84(部署面 setup 脚本下次部署生效);
- scripts/heartbeat_loop_prompt.py:20(docstring),53(prompt 文本)+
  tests/test_heartbeat_off.py:133 同步;
- tests/test_convergence_rules_file.py:ALLOWED_VOCABULARY +"priority_ratio.py"
  (distill-≠-copy 掩码,翻面后必需);
- references/:decision-rights.md:10(并列 ✅ → 单一)、guardrails.md:7,435、
  search-policy.md:13,38(公式块换 VoI,权重冻结说明)、failure-modes.md:29、
  failure-modes-lifecycle.md:27、_INDEX.md:74、tool-inventory.md:17(行改
  deprecated + 指向);
- scripts/README.md:43(行标记 deprecated)。

**语义变化显式声明**:加权 scorer 的 `task_spec.priority_weights` /
env `PRIORITY_WEIGHTS` 覆盖机制在 live 面失效(VoI 权重是 spec 冻结值,
0.45/0.30/0.25)。这是权威切换的固有代价,记 RUNBOOK 风险 + issue 评论。

**不翻**(记录为残留,归 #446):convergence_check.py:600(golden 钉死)、
tests/fixtures/golden/{F-01,F-06}、tests/fixtures/claudemd-golden/×3、
external_kicker.py(off-loop)、convergence_check.py docstring 6,17 **会翻**
(非 golden 面)。另:state-mapping.md:77 是 #331 域描述非指示,不翻。

## D5. 防回归测试(tests/test_scorer_authority.py)

判别性 fixture(ws 工厂):加权 #1 ≠ VoI #1,证明测试网不是恒真:

| claim | 字段 | 加权分 | VoI 分 |
|---|---|---|---|
| C-A | answers_question=q1 | **0.65(#1)** | 0.40 |
| C-B | competitor_group=g1 | 0.49 | **0.55(#1)** |
| C-B2 | g1, tier_attempted=1 | 0.39 | 0.18 |
| C-R | RETRACTED + 下游 C-D | (terminal 剔除) | 0.85(原始 #1,须被过滤) |

competitor_groups: {g1: [C-B, C-B2]}(≥2 OPEN → live → C-B 的 D=1.0)。

1. `test_pulse_next_up_scores_via_priority_ratio` — e2e(镜像
   test_dispatch_contract._run_pulse:stdin payload + 激活态 + dispatch 前缀),
   断言 `next up: C-B` 出现且 `next up: C-A` 不出现(若仍调 priority.py
   则输出 C-A → 红);
2. `test_pulse_filters_failure_blocked_and_terminal` — 加 C-F
   (promotion_attempts=1 无 analysis → cc failure_blocked;原始 VoI #1),
   断言 next-up 跳过 C-F 与 C-R;
3. `test_check_priority_audits_against_priority_ratio` — 派 C-B →
   (True,'',False) 非偏离;派 C-A → deviated=True 且 advisory 点名 C-B 为 #1;
4. `test_priority_module_deprecated_surface` — DEPRECATED/AUTHORITY 常量 +
   docstring 声明 + import 兼容(rank_claims/gate_allows 可调用,
   DEFAULT_WEIGHTS 键齐);
5. `test_live_path_prescribes_authority_only` — 静态接线断言(live 面文件集)
   不再含 `priority.py` 子串(priority_ratio.py 不含该子串,判别干净);
6. `test_worker_pulse_wiring_subprocess_target` — worker_pulse 源含
   `priority_ratio.py` 构造的 subprocess 目标。

RED 判据:1/2 因 pulse 仍推荐 C-A(pulse 的 cc 输出无 C-A 过滤语义)而红;
3 因 check_priority 仍按加权(C-A #1)方向反;4 因常量不存在红;5/6 因旧文本红。

## R1-R6(risks / 显式决策)

- **R1 权重覆盖失效**:PRIORITY_WEIGHTS/task_spec.priority_weights 在 live 面
  失效(D4);已知代价,权威权重是 spec 冻结值。
- **R2 依赖门槛口径差**:ratio 的 depends_on 终判用 facts/_INDEX(证据层),
  旧 ranker 用 register status。父 claim register-PROVEN 但无 fact 引用时,
  ratio 视其子为不可派 → check_priority 走 "not in dispatchable set" ADVISORY
  (非阻断,要求 reasoning)。M1 语义如此(evidence-driven),记录不改。
- **R3 evidence 缺失时 N=1**:无 facts/_INDEX 的 ws,N 项全员 1.0(退化为
  L/D/cost 排序),仍优于尝试计数 novelty;explore 模式属 kunglao-decide 职责,
  pulse 是 advisory,不复制 explore 逻辑(D1)。
- **R4 golden 残留**:convergence_check.py:600 + claudemd-golden 仍写
  priority.py(冻结面),首次部署后 orchestrator 可能看到 cc 文本指旧名、
  pulse 注入新排名 — 排名以 pulse/hook 为准;#446 golden-refresh 清账。
- **R5 rules 部署滞后**:rules/kunglao-convergence-loop.md 是源,部署副本
  (~/.claude/rules/common/)由 setup 脚本刷新,两次部署间新旧文本并存。
- **R6 #495 对接评估(不实施)**:priority_ratio.EvidenceView 消费
  facts/_INDEX 的 terminal/verified 计数;#495 三产物(identified_obstacle /
  validated_capability)落 claim+fact 后,天然进 N(同类 terminal facts 饱和)
  与 D(answers_question/competitor_group)—— 无需改 ratio 本体,对接点在
  产物写 claim-register/facts 的形状,属 #495/#496 联动。
