# Tasks: 心跳自治 (#754)

- [x] T0 openspec scaffold
- [x] T1 E2 连续 tick 判活：evaluate_tick_continuity + 三消费方接入 + append 端改造
      （heartbeat_register/hook_activation.renew/scripts.heartbeat_touch）+ RED 套件
      test_heartbeat_autonomy_754.py 判活四例 + 受影响 healthy fixture 补 history
- [x] T2 E1 durable cron：scripts/loop_scheduler.py upsert/exists/损坏备份 +
      init emit_activation_handoff 接入（--no-hooks/plugin skip）+ #593 红线锚测更新
- [x] T3 E3 analysis 入口：kunglao.py analysis 子命令（stale gate→rebuild→verify, RC=6）
      + SKILL.md 契约段 + monkeypatch verify 失败路径测试
- [x] 守门全扫 `check_heartbeat_alive|last_tick_ts|loop_registered` 命中点核查
- [x] 定向套件 → 净化 PATH 全套 → receipt → quality_gates → ruff

实现记录：commits 2a9bd70 / 8177250 / 9bdb8c6 / 23eeb61 / e9edd31；
独立审查链 r1-r8 全 PASS（r1 F1 nan/inf+非dict、r5 INDEX.yaml re-pin、r7 README/ext-index 注册——全部闭环）；
净化 PATH 全量 4130 passed / 1 failed（android listener 项 origin/dev 既存环境失败）；
全库 ruff ALL-PASS；release_receipt valid @ e9edd31。
