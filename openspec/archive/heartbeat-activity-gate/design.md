# Design — heartbeat-activity-gate
F1: liveness = 最近时间戳 = max(last_tick_ts, activity_ts)。tool 活跃(activity_ts, hook bump)即使 cron 不 tick(last_tick_ts stale)也算 alive。向后兼容(无 activity_ts 字段的 legacy .heartbeat.json 按 last_tick_ts 判)。
F2: tmp→replace 原子写,消除 orchestrator + N worker 并发 read-modify-write 竞态。
