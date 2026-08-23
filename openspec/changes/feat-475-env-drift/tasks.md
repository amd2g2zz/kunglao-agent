# Tasks — env-state bound to heartbeat + tool_error_policy wiring (#475)

## 1. OpenSpec (SDD)

- [x] 1.1 proposal.md (drift problem + why-heartbeat design argument + debt payment)
- [x] 1.2 specs/env-drift/spec.md (5 REQ: probe-write / three-state gate / advisory watch / hysteresis consumer / L1 repair)
- [x] 1.3 `openspec validate feat-475-env-drift` PASS

## 2. RED tests (`tests/test_env_drift_475.py`, written first, must fail)

- [x] 2.1 (a) tick → env-state.json exists, schema (per_capability status/last_probe_ts/detail, written_by, ts) + idempotent double-tick
- [x] 2.2 (b) check_env_fresh three states: missing FAIL_OPEN / FAIL∩tier REJECT / stale>2×TTL self-heal hint
- [x] 2.3 (c) monitor env_drift DRIFT/OK/NO_DATA + tick not blocked (exit 0)
- [x] 2.4 (d) tool_error_policy mechanical consumer: 3→warn, 5→disable_escalate + env-state fail writeback, success resets
- [x] 2.5 (e) env_repair_l1 idempotent no-op without substrate + double-run stability
- [x] 2.6 RED witnessed (assertion/attr failures on old code), recorded in report

## 3. GREEN

- [x] 3.1 scripts/env_state_probe.py (liveness subset via toolchain primitives, fail-open, no-op empty env)
- [x] 3.2 heartbeat_tick step 9 (idempotent style of steps 0/1/6/7; probe failure never fails tick)
- [x] 3.3 worker_budget.check_env_fresh (pure read <5ms) + REJECT_FIXES['envfresh'] + pre_check list entry
- [x] 3.4 kunglao-monitor env_drift_watch (advisory field; schema-frozen fields untouched)
- [x] 3.5 worker_budget.post_check streak persistence + policy application + env-state fail writeback
- [x] 3.6 scripts/env_repair_l1.py (adb-reconnect / vm-rediscover / mcp-rehandshake; idempotent; safe no-op)
- [x] 3.7 scripts/README.md registration (2 scripts) + CHANGELOG Unreleased
- [x] 3.8 schemas/tick-output.json: additive env_drift optional property (required set unchanged)

## 4. Gate

- [x] 4.1 `uv run python -m pytest -q -m "not load_sensitive"` green
- [x] 4.2 `uv run python scripts/release_receipt.py --check` green
- [x] 4.3 staged (no commit — orchestrator mints)
