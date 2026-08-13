## Why

a2b5e25c 客户 2026-08-11 反馈**问题 2**: F040 (routing 结论) 的 BLIND verifier 把「环境负证据」(`0 hits` + 沙箱卡死/未重连) 当成路由事实, 且与 F035 (前一路由结论) **两个 PROVEN fact 同主题并存、互相矛盾、无 supersedes 关系** — 收敛机制不拦, 下游报告按 F040 单口径写死, 把错误路由结论固化。

根因: 事实层只有「单 fact 校验」(BLIND / byte-exact), **没有「跨 fact 一致性」**: 同一 claim/同一证据范围 (sample_refs/cites) 下多个 PROVEN fact 结论互相矛盾时, 没有任何门禁要求 `supersedes:`/`superseded_by:` 链接或显式 CONFLICT 标记 — 矛盾事实静默并存, 直到客户指正。

## What Changes

- **新 `scripts/fact_contradiction_gate.py`**: 扫描 `facts/_INDEX.md` + fact frontmatter, 对同主题 (同 `claim_id` 或 `sample_refs` 重叠) 的 PROVEN fact 对做矛盾检测 — 结论不同 (归一化后) 且双方都无 `supersedes:`/`superseded_by:` 链接 → 判 CONFLICT (needs-resolution)。
- **`scripts/kunglao_record.py::claim_migrator`**: claim 提升 PROVEN 时先过矛盾门 (与 BLIND gate 同构); 检出 CONFLICT → effective_status 降为 STAMP, reason 列出矛盾 fact 对。
- **`hooks/worker_budget.py::compare_register_change_proven_gate`**: orchestrator 直接写 register 的 backstop 补矛盾检测 (绕过 claim_migrator 的路径也拦)。
- **tests (RED1-RED4 + 回测)**: RED1 同主题双 PROVEN 无 supersedes → CONFLICT 拦; RED2 有 supersedes 链接 → 过; RED3 不同主题 → 过; RED4 空目录/无 index → 不崩; a2b5e25c 回测 F035/F040 同主题矛盾应被拦, 补 supersedes 后通过。

## Capabilities

### New Capabilities

- `fact-contradiction-convergence`: 同主题多 PROVEN fact 必须带 `supersedes:`/`superseded_by:` 关系或显式 CONFLICT, 否则禁止提升/保持 PROVEN (effective=STAMP needs-resolution)。矛盾检测 = 同主题 (claim_id 相同或 sample_refs 交集非空) + 双方 PROVEN + 结论不同 + 无 supersedes 链接。

### Modified Capabilities

- `claim-promotion-gate`: `claim_migrator` 的 PROVEN 提升路径新增跨 fact 一致性检查 (与 BLIND gate 并列, 任一不过即降 STAMP)。
- `register-write-backstop`: `compare_register_change_proven_gate` 新增矛盾 backstop (与 BLIND backstop 并列)。

## Impact

- `scripts/fact_contradiction_gate.py` (新, 纯函数): `scan_conflicts` / `check_proven_contradiction` + `_topic_key` 解析 (sample_refs/cites/supersedes/superseded_by 从 fact 文本 yaml 块或行级提取)
- `scripts/kunglao_record.py::claim_migrator` (PROVEN 分支, ~10 行): 调用矛盾门, CONFLICT → STAMP
- `hooks/worker_budget.py::compare_register_change_proven_gate` (~15 行): 新增 fact 矛盾 backstop
- `tests/test_fact_contradiction_gate.py` (新): RED1-RED4 + F035/F040 回测 + 边角 (无 supersedes 字段、结论相同、单 fact、claim 缺失)
- `references/schema.md`: fact frontmatter 增补 `supersedes:`/`superseded_by:`/CONFLICT 约定 (一行文档)
- 既有 fact 不受 BREAKING 影响 (门禁只拦「已 PROVEN 且再提升/写 register」的动作; 存量矛盾由 scan 输出, 需人工补 supersedes)
- 关联 issues (互补): #49 fact-expected-value-binding (fact 内容层) · #48 inference-claim-blind-scope (BLIND 推断范围) · 本 change = **跨 fact 一致性层**
- 客户事故锚点: a2b5e25c 问题 2; RCA `D:/works/samples/2026-07-28/report_work/verify-customer-feedback/RCA-customer-feedback.md`
