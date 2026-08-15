## Why

a2b5e25c 客户 2026-08-11 反馈**问题 2** (与 #47 同事故的不同层面): 报告 3.3「不经过通用 HandleCommand」与二进制不符 — func12 是 HandleCommand 的 Go 闭包字面量, 命令经 HandleCommand 分发。源头是 **F040 的路由推断**: 声称「HandleCommand @0x3809A0 NOT on inject path (0 hits)」并「corrects F034」, 13/13 byte-anchor 验证的只是字符串字节计数, **不是路由结论**; 且 provenance 自述 BP 全部 0 hits 的原因是「debuggee 6500 WSS reconnect goroutine stalled... never reconnected」(环境故障), 却单独把 HandleCommand 的 0 hits 解释为「不在路径上」。

根因: `blind-verify-on-promotion` 只要求 PROVEN 有 BLIND 签字, **不指定签字的内容范围** — 推断/路由/因果类断言 (routing correction / not on path / gate / corrects F / 0 hits 用作路径证据) 可以「orchestrator-captured 证据」或「只覆盖字节锚点」地进 PROVEN。环境性负面证据 (BP 0 hits + 环境故障自述) 被当路由事实。H-C 盲实验证明 neutral 上下文 agent 能正确拒绝该误推 — 这是上下文/心态问题, 机械门禁可拦。

## What Changes

- **`scripts/blind_gate.py`**: 新增 `inferential_claim` 解析 (关键词模式: routing/route/not on .* path/correction/corrects F\d+/gate/0 hits/0 occurrences 用作路径证据) + `check_inference_blind_scope()`。
- **覆盖要求**: 推断类 claim 的 BLIND 签字必须含**独立静态证据 marker** (xref / disasm / decompile / capstone / ghidra / call graph / callsite 等), 且不得含 orchestrator-captured 证据; 否则 PROVEN 降 STAMP。
- **特别规则**: 「0 hits / 0 occurrences」+ provenance 含环境故障自述 (stalled / never reconnected / 未触发 / timeout) → 强制独立静态 xref, 不得仅凭动态未命中下路由结论。
- **`kunglao_record.claim_migrator`**: PROVEN 前过 `check_inference_blind_scope`; 失败 → STAMP (与 BLIND gate / CONFLICT gate 并列组合)。
- **`hooks/worker_budget.py`**: orchestrator 直写 register 的 backstop 补推断范围检查 (双门)。
- **tests (RED1-RED4 + 回测)**: RED1 推断+orchestrator-captured→STAMP; RED2 推断+独立静态 xref→过; RED3 非推断 (纯字节锚点)→过; RED4 0-hits+环境故障+无静态 xref→STAMP; a2b5e25c 回测 F040 应降 STAMP。

## Capabilities

### New Capabilities

- `inference-blind-scope`: BLIND 签字必须覆盖推断/路由/因果类断言, 不止字节锚点。推断类 claim 的签字证据须含独立静态 marker 且非 orchestrator-captured; 「0 hits + 环境故障自述」强制静态 xref。

### Modified Capabilities

- `claim-promotion-gate`: `claim_migrator` PROVEN 分支新增推断范围检查 (与 BLIND / CONFLICT 并列, 任一不过即降 STAMP)。
- `register-write-backstop`: `compare_register_change_proven_gate` 新增推断范围 backstop。

## Impact

- `scripts/blind_gate.py`: `is_inferential_claim` / `_has_zero_hits` / `_has_env_fault` / `_signoff_static_markers` / `check_inference_blind_scope(claim_id, facts_dir, register_text, worker_id)` (~80 行)
- `scripts/kunglao_record.py::claim_migrator`: PROVEN 分支追加推断门 (~10 行, 与 #47 CONFLICT 门并列)
- `hooks/worker_budget.py::compare_register_change_proven_gate`: 追加推断 backstop (~10 行, 复用已读取的 register_text)
- `tests/test_inference_blind_scope.py` (新): RED1-RED4 + F040 回测 + 边角 (无签字/自签/REFUTE/非推断带静态 marker)
- `references/schema.md`: verifier_sign_off 的推断覆盖约定 (一行)
- 存量 fact 无 BREAKING (门禁只作用于提升动作; 存量推断类 PROVEN 由 scan/人工补静态证据)
- 关联 issues: #47 (拦矛盾并存) 与 #48 (拦推断未独立复核) 互补; 同属 a2b5e25c 问题 2
- 客户事故锚点: a2b5e25c 问题 2; RCA `D:/works/samples/2026-07-28/report_work/verify-customer-feedback/RCA-customer-feedback.md`
