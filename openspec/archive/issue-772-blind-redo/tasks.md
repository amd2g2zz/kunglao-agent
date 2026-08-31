# Tasks — issue #772 重做方向的盲性缺口

## 1. SDD

- [x] 1.1 `openspec/changes/issue-772-blind-redo/proposal.md` — 缺口取证 + 用户裁决
- [x] 1.2 `design.md` — D1 裁决 / D2 取证 / D3 REDO slice / D4 契约三处 / D5 泄露 WARN
- [x] 1.3 `tasks.md`（本文件）

## 2. T1 = L1+L2 REDO slice 机械过滤

- [ ] 2.1 RED `tests/test_blind_redo_772.py`：含 'actual anchor 3446' 的 DIFF →
      slice 无 '3446' 字面量且含 anchor mismatch 形态；independent derivation 正文
      与 machine_check fence 内容不进 slice；0x/hex/十进制 token 清洗 + claim/fact
      id 引用保留；divergence_class 三类关键词归类；challenged 假设抽取；缺文件
      FAIL_OPEN；CLI --redo-diff 冒烟
- [ ] 2.2 GREEN scripts/dispatch_context.py（build_redo_context + 常量 + CLI）

## 3. T2 = L3 契约三处

- [ ] 3.1 RED：SKILL.md §1b GAP-ONLY 条款 / kunglao-worker GAP 不是答案条款 /
      kunglao-redteam 裁决层读者条款 文本断言
- [ ] 3.2 GREEN skills/kunglao-agent/SKILL.md + agents/kunglao-worker.md +
      agents/kunglao-redteam.md

## 4. T3 = L4 泄露启发式检测

- [ ] 4.1 RED：泄漏 prompt（redo 标记 + DIFF 数值）→ stderr/additionalContext
      WARN 且 rc=0；干净 GAP prompt → 无 WARN；fail-open 双路径；EMIT_ACTIONS
      注册 redo_leak_warn
- [ ] 4.2 GREEN hooks/dispatch_gate.py（_redo_leak_check + 走廊挂点）+
      scripts/event_taxonomy.py

## 5. Close-out

- [ ] 5.1 守门 grep 全扫（BLIND/dispatch_context 测试面）+ 定向套件 +
      净化 PATH 全套 + receipt --check + devkit/quality_gates + ruff
- [ ] 5.2 staged-ready：自证 evidence `.review-gate/evidence-772-r1.md`
      （self-review 披露）——commit/mint 由 orchestrator 补（同 #760 先例）
