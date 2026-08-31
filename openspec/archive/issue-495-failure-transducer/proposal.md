# Failure→Knowledge Transducer — 三产物 + 障碍升格 + method-ladder + provenance (#495)

## Why

Issue #495(父 issue #498 架构声明,B 类"模型贫瘠"落地件)。v0.1.1 现场轨迹1
(补环境)实证:worker 手握分解级证据 — JNI 桥工作(NewByteArray 被调)、
app 启动时以真实 Context 自然调用过 badger.a、spawn 超时只判死 spawn 路径 —
但失败叙事让证据全部蒸发,每次 pivot 从零开始,单点挫败判整路死刑。

机制缺口(代码证据,`scripts/failure_analysis_gate.py` v1.9.3):

- 三问题(assumption/validity/next_method)是 prose:落在
  `analyses/failure-<C-NN>.yaml` 后即死文件,不回流 claim-register /
  claim_deps / 计划;`_analysis_covers` 只数 `covers_attempt`,对内容零要求;
- 障碍(什么挡的)与能力(什么被证明能用)没有类型化字段 — B 类原话
  "失败不产出类型化事实,DAG 不生长";
- lessons 库(#41)有 keyword 检索(`--search` → `_score_lessons`)但记录路径
  零机械调用方 — BLOCKED 时有 similar_lessons 提示,记录时反而不再查;
- next_method 无 provenance:方法从哪来(lesson/reference/web/凭空)不可审计,
  "novel-hypothesis 占预算"没有机械门。

## What Changes

- **失败三产物**:`--record` 扩展 `--validated-capability`(这次证明了什么
  能用)与 `--identified-obstacle`(具体什么挡的),落进 analysis 记录;
  `identified_obstacle` 非空时**自动升格为新 claim** 写入 claim-register.yaml
  (status OPEN、`depends_on` 挂失败 claim、继承 `answers_question` 上下文、
  `origin: failure-obstacle` + `obstacle_for` 标记),同时向 claim_deps.yaml
  写真依赖边 — 平铺 DAG 长出节点。升格幂等:同 claim 重跑不重复建
  (以 `obstacle_for` 标记判重)。
- **BLOCKED 语义收紧(复用现有状态机)**:`_analysis_covers` 在
  `covers_attempt` 之外追加要求 `validated_capability` 与
  `identified_obstacle` 非空 — 任一为空即不覆盖 → `scan_workspace` 判
  BLOCKED → `hooks/dispatch_gate._failure_blocked_ids` 拒绝 re-dispatch。
  不新增门,只加严既有门的内容判据。
- **method-ladder(lessons 级机械接线)**:失败时记录(`--record` 携任一
  三问字段)自动以障碍+假设关键词跑 `_score_lessons`(与 `--search` 同一
  接口,`--library` 透传),命中注入 `candidates` 字段、查询串落
  `method_ladder_query`(留痕可审计);查询失败 **fail-open**(异常 → 空
  candidates,绝不阻塞记录)。
- **next_method 强制 provenance**:`--record` 增 `--source`
  {lesson-hit|reference-hit|web-hit|novel-hypothesis};缺 source 或非法枚举
  → 拒绝记录(recorded=False);`novel-hypothesis` 要求 candidates 非空
  (至少机械查过 lessons 级才允许声明 novel)。

## Impact

- **代码**:`scripts/failure_analysis_gate.py`(record_analysis 扩参 +
  `_promote_obstacle_claim` + `_analysis_covers` 收紧 + CLI 三旗 +
  `_print_blocked` 指引 + docstring v2.0.0)。不改 `priority*.py`(#499 领地),
  不改 convergence_check / dispatch_gate(它们消费 scan_workspace,语义
  自动传播)。
- **行为面(有意收紧)**:既有 analyses(无三产物)对未终结 claim 不再
  构成覆盖 → 回到 BLOCKED,须按新协议重录;`test_failure_lessons.py` 的
  `_record` 助手与 `test_orchestration_event_taxonomy.py` 的 cleared-fixture
  更新到新契约(原断言意图保留)。
- **不做**(见 design.md R1-R5):不做 re-library/WebSearch 的机械执行
  (梯级 2/3 由 orchestrator 声明 source,门只机械校验梯级 1);不动
  NEGATIVE 结论路径(justified-adequate 语义不变);不在 facts/ 层另建
  产物文件(analysis YAML 即事实落点,`--lessons` 聚合已有);不改
  claim_deps 的其它消费者。

需求源: issue #495 (github.com/amd2g2zz/kunglao-agent/issues/495)
架构约束: issue #498 "目标架构"(失败是证据,观察是脊柱)
