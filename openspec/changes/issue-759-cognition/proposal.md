# Proposal: orchestrator 认知层 — THINK 席位 / 价值函数 / 主动触发器 + K3 接线 (#759, #762)

## Why

语义源 #711（现场证据，2026-08-27）：#704 dispatch 后台化之后，

1. **tick 等待期零认知产出** — heartbeat_tick 的 `action_taken` 在等待期是 EMPTY
   （#237 定义的空闲故障信号），整个等待窗口没有任何推理产物落盘。
2. **价值排序靠手改文件 hack** — 用户裁决（"目标是 RCE"）只能靠 orchestrator
   手改排序输入或 SendMessage 中断循环传达，没有结构化通道。
3. **主动检索靠用户两次提示** — 同族先例/新情报的检索不是确定性行为，
   三次关键洞见两次来自红队一次来自用户——orchestrator 自己没有产出。

用户裁决（2026-08-27，原文）：**"调度需要处理规划/价值/下一次部署"**。

## What Changes

- **T1 = H1 THINK 席位**: tick 等待期（无 dispatchable/verify 动作）→
  `runs/.think-<ts>.md` 结构化思考产物（patterns/hypotheses/value 三段固定 schema），
  路径机械写进 tick 的 `action_taken`；SKILL 决策表增 THINK 行。
  脚本只保证席位存在 + 产物落盘 + action_taken 引用；思考内容由 orchestrator LLM 填。
- **T2 = H2 价值函数**: workspace 级 `runs/value-weights.yaml`
  （claim_classes / per-claim overrides）作为 priority_ratio 排序乘子（score × weight）；
  加载 fail-open（无文件 = 全 1 不变）。用户裁决由 orchestrator 结构化写入
  value-weights.yaml —— sanctioned 通道，替代手改文件 hack。
- **T2b = K3 接线**（Closes #762）: `note_supersedes_hypothesis` 实装 ——
  note 标记 supersedes 一个 open hypothesis → hypothesis_store open→superseded
  （指向 note）+ 事件 `hypothesis_superseded`（EMIT_ACTIONS 注册）+
  affected_claims 列表暴露。不做 claim-register 自动改写。
- **T3 = H3 主动触发器**: THINK 产物 value 段增检索建议 ——
  N tick 无进展 → 机械产出 `suggested_searches` 条目（WebSearch / 参考库各一列），
  SKILL 契约：suggested_searches 必须在下一动作执行。

## Out of scope

- sequentialthinking 链的**契约细则**归 #761 J2（agents/worker 契约单一源）；
  本波只在 SKILL.md/orchestrator 面引用概念（"结构化推理走 sequentialthinking 链"），不复制细则。
- T2b 只做机械接线（事件 + 状态迁移 + affected_claims），不自动改 claim-register。
- 不动真实用户 workspace。

## 安全面

- THINK 席位 advisory-only：不进 tick rc/alert 权重；思考内容永远不由脚本生成
  （消除"脚本替 LLM 想"的越权面）。
- 价值权重 fail-open：无文件/损坏/形态错 = 全 1，排序行为与今天逐字节一致。
- K3 沿 #528 状态机语义迁移（open→superseded 终态不可逆）；缺指针/非 open 状态大声报错，
  绝不静默透传（#762 留缝时的原话："silent pass-through here would let a claim closure
  masquerade as a hypothesis rewrite with no chain"）。
