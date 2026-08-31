# Tasks: #823-P1 mission_ledger

- [ ] 1. SDD：本 proposal + tasks 提交
- [ ] 2. TDD 红：tests/test_mission_ledger_823.py —— init 三态/解析形状（canonical id + legacy one-key + 纯 string）/防傻断言×3/blocked 合法性/A_t 历史/emit 快照字段（glob 全 ledger 断言）
- [ ] 3. 实现 scripts/mission_ledger.py（init/update/mark_blocked/load/value_m/emit_snapshot）
- [ ] 4. event_taxonomy EMIT_ACTIONS 注册 mission_snapshot（sorted 位置）；README catalog 行
- [ ] 5. 本地质量门：pytest 全量 + ext-scan + deploy_manifest --verify（sha 变了 --write）
- [ ] 6. push + PR(base=dev)
