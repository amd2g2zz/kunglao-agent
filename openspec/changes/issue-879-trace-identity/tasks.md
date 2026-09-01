# Tasks: issue-879-trace-identity

## 1. 测试先行（RED）

- [ ] 1.1 `tests/test_trace_identity_879.py`：trace_id 格式钉死（`tr-<mission>-<seq>` 正则 + validate_trace_id 拒绝例）
- [ ] 1.2 actor 词表校验测试（五形态合法例 + 非法例 → validate_actor 失败）
- [ ] 1.3 谱系边 round-trip：register 写 supersedes/superseded_by/derived_from → yaml round-trip → 边可读 + carrier_consistency (g) 校验（dangling/self-loop/cycle 各一）
- [ ] 1.4 join 验收：模拟 dispatch→worker→结算三行 emit 同 trace_id 同值断言
- [ ] 1.5 未归因率函数单测（全 null / 部分归因 / 空账本）
- [ ] 1.6 CI anchor：scripts/hooks actor 字面量扫描（词表 ∪ LEGACY_ACTORS 之外即红）
- [ ] 1.7 dispatch_gate 分配/复用面 subprocess 测试（envelope 带/不带 trace_id）
- [ ] 1.8 worker-status `| trace:` token 解析不破坏 + fact frontmatter trace_id lint 零告警
- [ ] 1.9 plan_review 结构 diff 测试（replan → detail.stages_diff 非空且正确）

## 2. 实现（GREEN）

- [ ] 2.1 kunglao_log：emit trace_id 字段 + validate_trace_id/new_trace_id/allocate_trace_id + validate_actor/LEGACY_ACTORS + unattributed_rate + --check-actors
- [ ] 2.2 event_taxonomy：EMIT_ACTIONS 登记新词（字母序）
- [ ] 2.3 dispatch_gate：trace 解析/分配/复用 + trace_allocated 发射 + _emit_trace 形参
- [ ] 2.4 worker_budget_sinks：#461 linkage dispatch 行补 trace_id（envelope meta 解析）
- [ ] 2.5 plan_stages：plan_review detail.stages_diff
- [ ] 2.6 retract_claim：--superseded-by 双边谱系边写 register
- [ ] 2.7 carrier_consistency：(g) 谱系边校验类
- [ ] 2.8 lint_facts：KNOWN_FRONTMATTER_KEYS 收编 trace_id
- [ ] 2.9 协议/文档：dispatch-protocol.md envelope trace_id 段 + SKILL.md 样例 + kunglao-worker.md 回带协议 + schema.md 谱系字段 + fact-frontmatter.md 扩展层行

## 3. 门与提交

- [ ] 3.1 本地门：pytest tests/ -q 全绿（100% 通过率硬门）
- [ ] 3.2 release_receipt.py --check 绿
- [ ] 3.3 conventional commits（一个逻辑单元一个 commit）
