# issue-873-cockpit-persist — tasks

- [x] T0 writer：hooks/cost_input_capture.py（PostToolUse COST WARNING 解析→cost_events.jsonl 追加，fail-open）
- [x] T1 cockpit_sample：heartbeat_tick 挂 cockpit_summary→ledger 落账（mission_ledger 缺失跳过）
- [x] T2 rho_pair cost 字段（cost_events 最新 amount；缺失 None）
- [x] T3 tuition_curve 读真实 cost（duration 代理删除）
- [x] T4 EMIT_ACTIONS 注册 cockpit_sample（字母序）
- [x] T5 测试：writer 捕获/不匹配不写/fail-open；cockpit_sample 字段齐；rho_pair cost；
      tuition 真实 cost；无 mission_ledger 零噪声
- [x] T6 质量门：pytest 全量 + ext-scan + deploy_manifest + catalog + 注册表
