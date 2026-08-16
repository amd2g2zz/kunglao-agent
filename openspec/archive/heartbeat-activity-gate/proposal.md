# heartbeat-activity-gate
## What
check_heartbeat_alive 改读 max(last_tick_ts, activity_ts) (F1); heartbeat_touch 原子写 (F2)。
## Why
v1.9.36 heartbeat_touch bump activity_ts 但 gate 只读 last_tick_ts (语义分裂, fix 没修 gate) → cron 不 tick 时 STALE 假阳性拦所有 dispatch (本会话 STALE=5267 实测)。loop-engineering §6 RC1/RC3。
## Scope
- F1: worker_budget.py::check_heartbeat_alive._age 读 max(last_tick, activity)
- F2: heartbeat_touch.py bare write_text → 原子 tmp→replace
## Acceptance
- test_heartbeat_gate 4/4 (含 F1 核心: cron stale + activity fresh → alive)
- pytest 181 全量绿
