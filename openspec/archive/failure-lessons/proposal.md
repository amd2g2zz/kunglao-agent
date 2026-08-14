# Proposal — failure-lessons (#41)

## Why

failure_analysis 的产出不留痕: 失败分析的 `analyses/failure-*.yaml` 记录了
method_assumption / assumption_validity / next_method, 但 (a) 没有 outcome 字段 —
claim 关闭后没人知道"那个 next_method 到底有没有用", 同方法重试违规
(re-dispatch-after-failure case book) 只能靠人记; (b) 分析文件散在各自
workspace, 跨样本复用不到 — 下一个样本遇到同样的失败签名, orchestrator 仍从零
开始猜方法。

根因链:

- `failure_analysis_gate --record` 写 entry 无 outcome/结果回填字段 → claim 关闭
  时无法把"方法到底成功没有"挂在失败签名上。
- 没有聚合入口把多 workspace 的失败签名归并成可检索语料 → 检索退化为"我记得
  之前遇到过"。
- 闭环(outcome 已被验证)与未闭环(outcome 缺失/被证伪/未过 red-team)混在一起,
  库会被垃圾结论污染。

## What Changes

- **`--record` 增加 `--outcome` 与 `--what-happened`**(可选): claim 关闭时回填
  `next_method` 的最终结果 — `PROVEN|VERIFIED|REFUTED|NEGATIVE` + 自由文本
  "what actually happened"。`analyses/failure-<claim>.yaml` 新增两个可选字段,
  旧文件无字段仍可解析 — `_failure_blocked` / `_analysis_covers` 解析零改动
  (向后兼容)。
- **聚合模式 `--lessons`**: 扫 `analyses/failure-*.yaml`, 按失败签名
  (method_assumption + next_method + claim topic) 分组, 输出
  `lessons/lesson-<slug>.md`(每个签名一份, 幂等 — 同签名不重复写)。
- **闭环门禁**: 只入库 `PROVEN`/`VERIFIED` 以及**幸存 red-team 的 NEGATIVE**
  (ledger 中有该 claim 的 `checker=red-team, result=CONFIRMED` OUTCOME 行,
  来自 #35 的 outcome_capture)。其余(`REFUTED` / 无 outcome /
  NEGATIVE 未过 red-team)追加到 **/reflect 人类队列**(claude-reflect 的
  `learnings-queue.json` 格式: JSON 数组, 带 reason)。
- **库位置**: 全局 `~/.claude/skills/kunglao-agent/references/lessons/`
  (跨样本, 不存 workspace), `--library` 参数可覆盖(测试写 tmp)。
- **检索从小起步**: `--search <keywords>` 关键词/claim-tag 匹配(无 embedding);
  同时 BLOCKED 输出附 top-3 相似 lesson, 指导 orchestrator 换方法。

## Non-goals

- 不做 embedding / 向量检索(语料几十条, 关键词足够)。
- 不改 `_failure_blocked` 解析契约(analyses/ 格式向后兼容)。
- 不自动写回 claim-register 状态; outcome 由 orchestrator 在 claim 关闭时显式回填。

## Capabilities

- `failure-lessons`(spec: `openspec/changes/failure-lessons/specs/failure-lessons/spec.md`)

## Dependencies

- #35 outcome-capture(ledger OUTCOME 行) — 已合入 dev, 本变更消费
  `outcome_capture.read_outcome_rows` 判定 NEGATIVE 是否幸存 red-team。
