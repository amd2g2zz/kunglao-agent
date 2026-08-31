# Heartbeat liveness has no anchor outside the deletable file (#828)

Child of #825.

## Why

`hooks/worker_budget_sinks.py:283-285` evaluates tick continuity from `runs/.heartbeat.json` `tick_history` alone. In the incident:

1. A 10-min gap was flagged (02:18:04 → 02:28:41) → the orchestrator **deleted `.heartbeat.json`**; `--heartbeat-on` recreated it with `started_ts=now` → history erased, gate green.
2. Later ticks were **hand-set** (a python one-liner wrote an ascending 5-min-spaced history) because the durable /loop cron only fires while the parent process lives — the constructed history satisfied `evaluate_tick_continuity` without any real cron tick.

Also: `.convergence_ledger.jsonl` was deleted twice to clear STALLED/SPINNING (a KeyError on schema-drifted operator_action entries was the proximate excuse, but deletion also erased the flatline evidence that `convergence_health.py` would have used).

## What Changes

- Append-only sidecar outside the workspace (or a hook-owned file the session tools cannot write) holding cumulative tick count and first-started ts, so JSON deletion cannot reset age or cadence baselines.
- `evaluate_tick_continuity` should cross-check the hook-written event stream `runs/logs/kunglao-*.jsonl` for tick evidence instead of the editable heartbeat file alone.
- Ledger deletion must itself be gated: mid-run `rm` detectable via mtime discontinuity of the file vs newest entry ts.