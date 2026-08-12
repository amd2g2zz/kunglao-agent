## Why

`schemas/decide-output.json` declares `required: [decision, exit_code, top_actions, blocked, failure_blocked, stale, drifts, explore_mode, selfcheck]` — these fields match `kunglao-decide.decide()` (the M1 composite CLI). However `convergence_check.decide()` (the 5-branch state machine) outputs a different shape: `action`, `open_claims`, `unblocked_open_count`, `blocked_open_count`, `partial_facts`, `active_workers`, `worker_cap`, `stuck_workers`, `active_blockers`, `orphan_claims`, `unverified_primary_qs`, `note_layer_gaps`, `pq_parse_error` — none of which are in the schema, and it does NOT produce `top_actions`, `blocked`, `stale`, `drifts`, `explore_mode`, or `selfcheck`.

The `conftest.py::contract_validator` is a generic loader keyed by schema name; there is no routing logic. If any test calls `contract_validator("decide-output", cc_decide_output)` it will fail on missing required fields (`top_actions`, `blocked`, `stale`, `drifts`, `explore_mode`, `selfcheck`); if it calls `contract_validator("decide-output", kd_decide_output)` it passes.

Currently no test invokes `contract_validator("decide-output", ...)`, so the mismatch is latent. Issue #97 (F2) requests schema-contract correctness before it bites.

Reference: absorption-research-round2.md F2.

## What Changes

- **New schema `schemas/convergence-check-output.json`**: reflects `convergence_check.decide()` actual output fields (required: decision, exit_code, action, open_claims, open_count, unblocked_open_count, blocked_open_count, failure_blocked, partial_facts, partial_count, active_workers, free_slots, worker_cap, stuck_workers, active_blockers, orphan_claims, unverified_primary_qs, note_layer_gaps, pq_parse_error). M2 completeness diagnostics included.
- **Existing schema `schemas/decide-output.json`** unchanged — it already matches `kunglao-decide.decide()` composite output.
- **`tests/conftest.py::contract_validator`**: add a routing helper `contract_validate_decide(source, obj)` that picks the correct schema based on `source` ("convergence_check" vs "kunglao-decide"). The raw `_validate(name, obj)` stays available for direct use.
- **New test `tests/test_decide_schema_routing.py`**: RED phase proves `cc --json` fails against decide-output.json and passes against convergence-check-output.json; `kunglao-decide --json` passes against decide-output.json.

## Capabilities

### New Capabilities

- `convergence-check-output-schema`: JSON Schema contract for `convergence_check.decide()` raw output (5-branch state machine). Keyed as `convergence-check-output` in the contract_validator registry.

### Modified Capabilities

- `contract-validator`: `conftest.py::contract_validator` gains an optional routing wrapper that maps producer name to schema name. Existing `_validate(name, obj)` API unchanged.

## Impact

- `schemas/convergence-check-output.json`: new file, ~80 lines JSON Schema.
- `schemas/decide-output.json`: no change.
- `tests/conftest.py`: +15 lines (routing dict + wrapper function).
- `tests/test_decide_schema_routing.py`: new test file, ~80 lines.
- No changes to `convergence_check.decide()` logic or `kunglao-decide.decide()` logic.
- No changes to `kunglao.py` decide path (F3 independent).
