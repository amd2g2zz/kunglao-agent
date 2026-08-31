# Tasks: issue-831-secondstop-anchor

- [ ] T1 tests/test_secondstop_anchor_831.py — 6 用例（红）：
      首次锚定 / 重复放行不重复锚 / 改写回填 BLOCK / 零引用仍 BLOCK /
      ledger 写失败 BLOCK / 无制裁回归守卫
- [ ] T2 hooks/completion_gate.py — _secondstop_record_sha + _secondstop_anchor
      + _append_anchor + stop_hook_active 分支接线
- [ ] T3 回归：tests/test_completion_gate.py 全绿（#147/#199/#200 语义不回退）
- [ ] T4 质量门：pytest 全量 + ext-scan + deploy_manifest --write（completion_gate
      sha 变更）+ --verify
- [ ] T5 push + PR(base=dev，含回填攻击复现命令)，不合入
