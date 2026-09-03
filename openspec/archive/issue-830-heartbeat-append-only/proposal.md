# #830 heartbeat liveness durable anchor — append-only tick sidecar

## Why

`runs/.heartbeat.json` 是唯一 liveness 锚点且可任意删除/重写：豆包事故中
被删后 `--heartbeat-on` 重建即"历史清零"，门变绿；后续 tick 甚至被手写
伪造。心跳缓存可篡改 = 死寂不可判 = 无人值守的地基漏洞（#825 家族）。

## What Changes

1. **专用 append-only 侧车** `runs/.heartbeat.log`（JSONL，一行一 tick：
   `{"ts": "...Z", "actor": "..."}`）——每次 tick（register / touch /
   renew）追加一行。选专用侧车而非 convergence ledger 的理由：
   (a) 事故中 ledger 本身被删两次，锚进 ledger 继承同一弱点；
   (b) kunglao ledger 是当日日期文件（跨午夜分裂）且行 schema 是跨 PR
   契约（#818 刚证明 schema 漂移挂 CI）——专用单文件侧车契约自由、跨午夜稳定。
2. **liveness 判定以 durable 史为准**：`evaluate_tick_continuity` 增
   `log_path` 参数——侧车有 ≥1 可解析 tick 时以侧车为准；state 的
   tick_history 降级为只读缓存。缓存被删/篡改不影响"最近活跃时刻"判定，
   且**删除无法掩盖 cadence gap**（删文件+重建注册的旧缝仍在侧车里）。
3. **三个写入点全接**：heartbeat_register / heartbeat_touch /
   hook_activation renew-tick。gate（worker_budget_sinks）、
   --heartbeat-check、verify_loop 三个消费者全传 log_path。
4. 向后兼容：log_path=None（缺省）时行为 byte-identical。

## Impact

- scripts/heartbeat.py（核心：append_tick_log + evaluate_tick_continuity）
- scripts/heartbeat_touch.py · scripts/hook_activation.py（写入点）
- hooks/worker_budget_sinks.py · scripts/heartbeat_loop_prompt.py（消费侧）
- tests：新增 tests/test_heartbeat_durable_830.py（红→绿）

## Out of scope

- ledger 删除检测的 mtime 断层判据（issue 第三条 What-Changes）——独立小卡
- 心跳 daemon 化（#618/#795，W4）
