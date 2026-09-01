# Tasks

- [x] 1. SDD proposal/tasks（含 Recon：锚点表 + 镜像样例 + 基线）
- [x] 2. 测试（RED）：两态 dormant 测试（无 obstacle_for → 恰好一次 WARN；有 → 零告警）
- [x] 3. 实现（GREEN）：EMIT_ACTIONS 加 `capability_dormant`；guard 入口一次性 dormant 告警（sentinel `runs/.capability-dormant-warned`；畸形 claim isinstance 防御）
- [x] 4. 验收：两态绿 + `pytest tests/ -k capability -q` 全绿（88 passed；1 失败为 test_probe_tiers_474 Windows 本地环境失败，基线同败，CI Linux 面 green）
- [x] 5. 本地门：release_receipt --check exit 0；deploy_manifest --write→--verify 360 entries OK；全量 pytest 后台跑（慢套件 ~20min）
- [ ] 6. push + PR（--base dev）+ CI 绿（不 merge）
