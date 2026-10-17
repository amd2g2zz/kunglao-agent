# tasks — issue-683-substrate-wiring

## 1. Registry single-sourcing (hook-registry/1)

- [x] RED: `tests/test_substrate_wiring_683.py` — set-equality between
  `WIRE_UP_HOOK_FILES` and `_DEPLOYED_WIRING`, substrate hooks present
  after wire-up, every deployed row reachable by `register_hooks`
- [x] `scripts/wire_up_settings.py`: `WIRE_UP_HOOK_WIRING` (26 rows,
  `ORCHESTRATOR_MCP_MATCHER` beside them); `WIRE_UP_HOOK_FILES` derived
- [x] `scripts/hook_activation.py`: `_DEPLOYED_WIRING` aliases the table;
  `ORCHESTRATOR_MCP_MATCHER` re-exported; `register_hooks` gains the two
  substrate registrations (matchers via `_post_rows`)
- [x] subset tables: `hooks_selfcheck._KONG_SKIP_FILES` +
  `external_kicker._KICKER_SKIP_FILES` account for the growth (#381)
- [x] registry pins updated: `test_hook_registry_singlesource` (set +
  `KONG_SKIP`), `test_env_check._write_settings` fixture (#675 guard)

## 2. Durable REJECT telemetry (reject-telemetry/1)

- [x] RED: `test_worker_budget_rejects_are_durable` +
  `test_worker_budget_reject_telemetry_fails_open`
- [x] `scripts/gate_telemetry.py`: public `append_row` (decorator
  `_record` delegates — one row shape)
- [x] `hooks/worker_budget_sinks.py`: `_record_reject` called from the
  `_reject` chokepoint — fail-open, warn-once, rc/exit unchanged

## 3. Verification

- [x] `openspec validate issue-683-substrate-wiring` exit 0
- [x] targeted suites green: substrate wiring (5), registry/wiring
  (79 + 92), telemetry/reject (71), worker_budget sinks (147),
  pre_check batteries (178 + 106 + 99), deploy (100 + 31),
  heartbeat bootstrap/tick (24)
- [x] ruff clean on every changed file
- [x] comment hygiene + formal code lint baselines re-emitted;
  deploy manifest re-written
