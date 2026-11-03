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

## Amendments (2026-10-19 — spec text synced to the as-built code per the §8.2 audit, docs/architecture/kunglao-technical-doc.md)

The two amendments below record owner rulings the frozen proposal text
predates. The frozen ①/③ text above is preserved verbatim as the
change-of-record; the semantics BELOW are the operative ones.

### Amendment 1 — ③ the strategy log is an always-on recorder (§8.2 M1.4)

**Frozen text**: ③ "机制留接口,不强制使用(无标记 = 行为不变)" — the
`[strategy <id>]` marker was opt-in and a markerless pass wrote nothing.

**Owner ruling (review 2026-10-10)**, as recorded in the implementing
docstring: "the marker was an OPT-IN gate with no emitting side — the
orchestrator was never told to carry `[strategy <id>]`, so the log stayed
empty, round-strategy's compose had no input, and the strand cycled in
degraded mode."

**New semantics**: every PASSING dispatch writes one
`runs/strategy-log.jsonl` row. A markerless pass lands
`strategy: "default", declared: false` (honest: no strategy was declared);
a marker keeps its richer row (`strategy: <id>, declared: true`). The
write stays fail-open (an unreadable register snapshots 0; an unwritable
log warns on stderr and never blocks the dispatch). Row shape is the
frozen one plus the additive `declared` key: `{ts, event: "dispatch",
strategy, declared, claim, attempts_at_snapshot}`.

**Implementing code**: `hooks/dispatch_gate.py:975-1023`
(`_log_strategy_dispatch`; ruling comment at 981-985, the default-row face
at 989-999, the capped write at 1009-1023).

**Invariant**: INV-001 (`loop-sampler-exit`) — "default strategy rows are
anomalies, never the norm". The default row is the anomaly *signal* the
invariant speaks of: with the #773 W2 sampler exit (see the issue-691 W2
amendment) a markerless dispatch is rejected once and retried with the
sampled family, so a healthy loop shows default rows only at the
rejection-retry seam, never as the steady state.

**Integration contract**: caller = the dispatch ALLOW tail of
`hooks/dispatch_gate.py` main (after the #496 teeth, before the worker
starts); trigger = every passing kunglao dispatch; firing fingerprint =
one `runs/strategy-log.jsonl` dispatch row per pass (`event: "dispatch"`),
consumed by the `rl-sampler-exit` liveness fingerprint
(devkit/liveness_fingerprints.json).

### Amendment 2 — ① the teeth are FAIL_CLOSED (§8.2 M1.5)

**Frozen text**: ① "FAIL_OPEN: scorer 不可用 / register 缺失 / rank-None
… 时静默或仅 stderr ADVISORY" and design D1 key-decision 4 ("check_priority
不可 import、register 缺失、actions 为空 → 静默放行").

**Owner ruling (2026-09-28)**, verbatim: "a gate that cannot see must not
wave the dispatch through."

**New semantics**: scorer/audit ERRORS reject instead of waving through.
In `_top1_enforcement`, an unimportable `worker_budget.check_priority` or
a raised audit returns `_gate_error_reject` (REJECT `top1`, exit 2, repair
guidance, trace event) — rank-None on a HEALTHY audit still does not
reject (that face of the frozen text stands; the failure-blocked slice
keeps its #495 injection path). `_capability_guard` follows the same
ruling: scorer/card errors reject, while an unreadable register only
narrows the card scope to the claim (best-effort scope, kept). The same
2026-09-28 ruling is cited at the method-family gate's registry-unavailable
reject (`hooks/worker_budget_sinks.py:854-862`), making fail-closed the
shared doctrine of every dispatch-ranking gate.

**Implementing code**: `hooks/dispatch_gate.py:544-585`
(`_top1_enforcement`; ruling docstring 555-557; the two FAIL_CLOSED
returns at 563-566 and 573-576; `_gate_error_reject` at 426-471);
`hooks/dispatch_gate.py:736-791` (`_capability_guard`; ruling at 745;
error rejects at 759-762, 769-772, 788-791).

**Invariant**: no registered invariant owns the top-1/capability teeth
directly; the amendment is recorded under INV-001's gate posture (the
2026-09-28 fail-closed ruling that INV-001's method-family exit also
cites) so the ruling is traceable from the registry namespace.

**Integration contract**: caller = `hooks/dispatch_gate.py` PreToolUse
main chain (order: must-stop → failure-blocked → top1 → capability →
strategy-log); trigger = every Agent-tool dispatch inside the activation
TTL; firing fingerprint = `REJECT top1` / `REJECT capability` stderr +
exit 2 + the `top1_reject` / `gate_error` trace events in
`runs/logs/kunglao-*.jsonl`.
