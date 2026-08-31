## Tasks: issue-618-heartbeat-daemon

- [x] 1. 读既有实现（heartbeat.py / heartbeat_touch.py 双面 / hook_activation 注册面 / #830 侧车 / #634 breaker）
- [x] 2. SDD proposal（含 daemon 取舍记录）
- [ ] 3. TDD 红测：test_heartbeat_pulse_618.py
  - [ ] 3a. hook pulse 触达 durable 侧车（actor="hook"）
  - [ ] 3b. 60s 去重：窗口内二次 pulse 不追加侧车行
  - [ ] 3c. Stop 面注册：register_hooks_deployed 产物含 heartbeat_touch 的 Stop 槽
  - [ ] 3d. gap_alarm：侧车 newest 超阈 → (alarm, gap_min, ts)；无侧车 → (None,…)
  - [ ] 3e. decide() 标注：旧侧车 → decision["heartbeat_gap"] + heartbeat_gap 事件落账
  - [ ] 3f. 无 agent 参与全链可跑（假 payload 直接调 hook 模块）
- [ ] 4. 实现：hook durable 触达+去重 / Stop 槽 / gap_alarm / decide 标注 / EMIT_ACTIONS
- [ ] 5. 本地质量门：pytest 全量 + ext-scan + deploy_manifest --verify（sha 变 --write）
- [ ] 6. push + PR（body 含"无 agent 参与全链可跑"复现命令）
