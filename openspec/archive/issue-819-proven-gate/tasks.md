# Tasks: issue-819-proven-gate

1. [x] 读 issue body v2 + write_guard/rollup/outcome_capture 源码，确认缺陷面与证据格式
2. [x] SDD：openspec proposal + tasks
3. [ ] TDD 红灯：tests/test_register_proven_gate.py（unit：九个迁移场景）
4. [ ] TDD 红灯：tests/test_write_guard_register_gate_819.py（write_guard subprocess 集成：BLOCK/ALLOW/waiver/REFUTED-blocks）
5. [ ] 实现 scripts/register_proven_gate.py（证据谓词 + waiver）
6. [ ] write_guard CARRIER_REGISTER leg + proven_waiver_used 事件
7. [ ] rollup.py sweep 措辞改记账语义 + 证据引用
8. [ ] 本地质量门：pytest 全量 + ext-scan + deploy_manifest
9. [ ] push + PR(base=dev)，body 含豆包刷 PROVEN 复现被拦命令
