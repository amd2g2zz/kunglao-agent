## Design

### Field Mapping (issue #97 F2 reconnaissance)

Two producers, two schemas:

| Producer | Schema | CLI |
|----------|--------|-----|
| `convergence_check.decide()` (L523-544) | `convergence-check-output.json` (NEW) | `cc --json` |
| `kunglao-decide.decide()` (L115-147) | `decide-output.json` (EXISTING, unchanged) | `kunglao-decide --json` |

`convergence_check.decide()` is the raw 5-branch state machine. `kunglao-decide.decide()` wraps it with explore_gate, priority_ratio, and selfcheck, producing composite fields (`top_actions`, `blocked`, `stale`, `drifts`, `explore_mode`, `selfcheck`) that the raw output does not have.

### Schema Split Strategy

1. **New `schemas/convergence-check-output.json`**: mirrors the exact dict returned by `convergence_check.decide()` at L523-544. All 19 fields are required. `additionalProperties: true` to allow future extension without schema bumps.

2. **Existing `schemas/decide-output.json`**: no change. It already matches `kunglao-decide.decide()` output. The `INVALID` decision enum value is NOT in this schema because `kunglao-decide` catches exceptions and returns conservative BLOCKED, never INVALID.

3. **conftest.py routing**: no routing code needed. The `contract_validator` fixture accepts any schema name by key. Tests call `contract_validator("convergence-check-output", ...)` for cc output and `contract_validator("decide-output", ...)` for kd output. The routing is done at the test call site, not in the infrastructure.

### What We Do NOT Change

- `convergence_check.decide()` logic: untouched
- `kunglao-decide.decide()` logic: untouched
- `kunglao.py` decide path: untouched (F3 independent)
- No new fields introduced in either producer
- `conftest.py::contract_validator` internals: untouched (just a cache + loader)

### Test Strategy

`tests/test_decide_schema_routing.py` covers:
- RED: cc output fails against decide-output.json (proves mismatch exists)
- GREEN: cc output passes against convergence-check-output.json (proves new schema correct)
- GREEN: kd output passes against decide-output.json (proves existing schema still valid)
- Integrity: cc has no composite fields; kd has no raw fields; all required fields present
