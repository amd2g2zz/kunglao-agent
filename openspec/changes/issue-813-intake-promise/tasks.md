# Tasks: issue-813-intake-promise

- [x] 1. SDD proposal + tasks（本文件）
- [ ] 2. TDD 红：tests/test_intake_promise_813.py
  - [ ] 2a. apkid 缺失 → promise.prescan.apkid.state=missing + fix 提示（显式 WARN）
  - [ ] 2b. evidence/apkid.json 存在 → obfuscation_prior.obfuscators 提取
  - [ ] 2c. static-only + 无 java 前端 → unreachable + #807 警示
  - [ ] 2d. jadx 在 → reachable/degraded 判定
  - [ ] 2e. task_spec 存在 → 合并 promise 键，用户键不动
  - [ ] 2f. task_spec 缺失 → runs/intake-promise.yaml 降级落盘
  - [ ] 2g. task_spec 不可解析 → PromiseError（fail-closed）
  - [ ] 2h. 探针层不在 project_type 集内 → not_probed 显式记录
- [ ] 3. 实现 scripts/intake_promise.py（build/apply/PromiseError/CLI）
- [ ] 4. kunglao-init 接线（门后一处，失败 env_incident 落账不卡 init）
- [ ] 5. 本地质量门：pytest 全量 + ext-scan + deploy_manifest
- [ ] 6. push + PR（base=dev）
