# Spec Delta — heartbeat-activity-gate
## MODIFIED Requirements
### Requirement: Heartbeat liveness gate
The dispatch heartbeat gate determines liveness from the most recent of (cron tick timestamp, tool activity timestamp), not from cron tick alone. A workspace with active tool calls (activity_ts fresh) is alive even if the cron /loop is not ticking. The heartbeat file is written atomically (tmp→replace) to prevent concurrent-write corruption.
#### Scenario: tool activity keeps gate alive without cron
- WHEN last_tick_ts is stale (>35min, cron not ticking) but activity_ts is fresh (<35min, tool calls happening)
- THEN check_heartbeat_alive returns alive (liveness = max of both)
#### Scenario: both stale rejected
- WHEN both last_tick_ts and activity_ts are stale (>35min)
- THEN dispatch is REJECTED (true death detected)
#### Scenario: legacy heartbeat without activity_ts
- WHEN .heartbeat.json has only last_tick_ts (no activity_ts field)
- THEN gate judges by last_tick_ts alone (backward compatible)
