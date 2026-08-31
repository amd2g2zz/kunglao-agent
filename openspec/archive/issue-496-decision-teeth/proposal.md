# Decision-Loop Value Teeth — top-1 enforcement + typed-fact consumption (#496)

## Why

Issue #496 (milestone v0.1.2, #498 架构脊柱 C 类 "决策无牙"): 价值算法
(`scripts/priority_ratio.py`, #499 裁决后的唯一权威 scorer)计算正确,但
牙齿全在咨询层:

- `worker_pulse` 的 next-up 是注入(ADVISORY);`worker_budget.check_priority`
  的偏差审计要求 `reasoning:` 字段 — 但两者都要求 orchestrator 主动跑
  worker_budget 所在的那条 hook 链。`hooks/dispatch_gate.py` 的文档自己承认
  (#496 引文): "convergence_check / priority.py / failure_analysis_gate
  are all agent-invoked — an orchestrator that skips them is unconstrained",
  该门此前只补了 failure-blocked 切片(#495)与 must-stop 切片(#447)。
- #495 落地的三产物(`validated_capability` / `identified_obstacle` /
  升格 claim)只进 `analyses/failure-*.yaml` 与 claim-register,**没有任何
  决策输入消费它** — "手里的牌不进决策输入"(v0.1.1 轨迹1: frida✓ 在手,
  6 次无信息换工具转向无一道闸)。
- 价值函数只有 claim 粒度;任务内打法(attempt 级)无任何价值表示。

## What Changes

- **① top-1 强制**(`hooks/dispatch_gate.py` 扩一条,精确复制既有
  agenttype-deviation 模式 #310): 派发目标 != `worker_budget.check_priority`
  (即 priority_ratio 权威排名)的 top-1、且派发 prompt 无 `agent-reasoning:`
  前缀理由 → REJECT(stderr `REJECT top1` + hookSpecificOutput 修正指引 +
  exit 2);带理由 → 放行留痕(`kunglao_log.emit` 统一日志
  `runs/logs/kunglao-*.jsonl`,action=`priority_deviation`)。FAIL_OPEN: scorer
  不可用 / register 缺失 / rank-None(不在可派发集,含 failure-blocked 切
  片 — 该切片由 #495 的注入路径继续负责)时静默或仅 stderr ADVISORY。
- **② priority 消费类型化事实**(`scripts/priority_ratio.py` EvidenceView
  输入侧扩展 — 只读 #495 的记录面,不改它):
  - (a) 能力看牌: `capability_switch_violation(claim_ids, tools, prompt,
    evidence)` 纯函数 — 派发声明工具族与目标 claim(含 obstacle_for 父链)
    最新 analysis 的 `validated_capability` 工具族**不相交**且 prompt 无
    `capability-disproof: <family>` 逃逸标记 → dispatch_gate REJECT
    (轨迹1 反调试例: frida✓ 在手换 xposed,需出示 frida✗)。
  - (b) 障碍 leverage: #495 升格写出的 `depends_on[obstacle] = [failed]`
    真边已被 ratio 的 `rev_deps` **自然消费**(父 claim L 上升、解锁后障碍
    claim 的继承 `answers_question` 进 D) — 本变更写测试钉住,不动评分核。
- **③ 策略级价值节点**(最小接口,不建 attempt 树): 派发 prompt 含
  `[strategy <id>]` 标记 → dispatch_gate 在放行路径追加
  `runs/strategy-log.jsonl` dispatch 行(带 attempts_at_snapshot);
  `EvidenceView.from_workspace` 据此推导 `claim_strategy` 与
  `strategy_failures`(同 strategy 历史失败 = 该 claim 后续 analysis
  covers_attempt 超过派发时快照),`priority_ratio` 的 novelty 消费:
  `N = 1 − min(1, (category_facts + strategy_failures) / NOVELTY_BASE)`。
  机制留接口,不强制使用(无标记 = 行为不变)。
- **文档**: `references/dispatch-protocol.md` 增补三个 prompt 标记
  (`agent-reasoning:` / `capability-disproof:` / `[strategy <id>]`)的
  声明语义(additive;SKILL.md 不动 — 波间冲突热点)。

## Impact

- **代码**: `hooks/dispatch_gate.py`(三条新检查 + main 接线)、
  `scripts/priority_ratio.py`(EvidenceView 四个新字段 + 纯函数
  `capability_switch_violation` + novelty 的 strategy 项)。**不改**
  `scripts/failure_analysis_gate.py`(记录面 #495 已定,只消费)、
  **不改** `hooks/worker_budget.py`(check_priority 保持原签名与语义,
  dispatch_gate 直接复用它 = 单一排名源)。
- **测试**: 新增 `tests/test_decision_teeth.py`;②(b) 为钉住测试
  (green-on-arrival,钉的是既有自然消费)。
- **不做**: 完整 attempt 价值树、priority.py 复活、worker_budget devreason
  语义变更(`reasoning:` vs `agent-reasoning:` 并存 — 前者是 worker_budget
  链的既有标记,后者是 dispatch_gate 链的新标记,双链各自一致)。

需求源: issue #496 (github.com/amd2g2zz/kunglao-agent/issues/496);
架构约束: #498;前置裁决: #499(priority_ratio 是唯一权威 scorer)。
