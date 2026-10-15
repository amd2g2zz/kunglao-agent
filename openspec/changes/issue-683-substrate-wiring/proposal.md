# issue-683-substrate-wiring — the substrate is deployed but not wired

## Why

Issue #683 (owner-verified 2026-10-14): the #670 shadow experience
substrate shipped its hook files (`step_record_capture.py`,
`cost_input_capture.py`) and its deploy-table rows, but nothing the
CANONICAL writer consults ever registered them. Root cause is registry
drift, not "nobody ran refresh":

- `wire_up_settings.WIRE_UP_HOOK_FILES` (19 files) is what the
  post-write self-check expects (`_wire_up_hook_files()`), so a wiring
  missing the two substrate hooks still passed its own check — a missing
  hook was invisible by construction.
- `hook_activation._DEPLOYED_WIRING` (26 rows / 21 distinct files) was a
  second, hand-kept list that carried both hooks — reachable only by the
  deployed writer, never by `register_hooks`.
- Result in a live workspace: `step-ledger.jsonl` and
  `evidence-credit.jsonl` never produced a row; the escrow lifecycle had
  no producer; and every `worker_budget` gate REJECT (tier / cap /
  liveness / heartbeat / ...) printed to stdout and vanished — gates
  unauditable after the fact.

## What Changes

1. **Registry single-sourcing (`hook-registry/1`)** —
   `WIRE_UP_HOOK_WIRING` (the (event, matcher, file) row table) becomes
   THE list in `wire_up_settings`; `WIRE_UP_HOOK_FILES` derives from it
   and `hook_activation._DEPLOYED_WIRING` aliases it. The canonical
   `register_hooks` gains the two substrate registrations (matchers read
   from the shared table, never re-typed). The two deliberate narrow
   subset tables (`hooks_selfcheck._KONG_SKIP_FILES`,
   `external_kicker._KICKER_SKIP_FILES`) account for the registry growth
   (#381 import-time validator).
2. **Durable REJECT telemetry (`reject-telemetry/1`)** — every
   `worker_budget` gate REJECT appends one row to
   `runs/gate-telemetry.jsonl` at the single emission site (`_reject`),
   through `gate_telemetry.append_row` (same row shape as the decorator
   face). Fail-open: a missing `runs/` or an unwritable ledger never
   changes the verdict.

## Out of scope (S11 pre-wave W2-B annotation)

- Registry slimming and authority hand-off (deferred until S11).
- Live-workspace re-wiring of `rt_read_barrier` + `evidence_pin_guard`
  (operational: `register_hooks` already covers them; a re-wire run is
  the ops half, not this card).
- The #683 proposed-fix items 2–3 (filling the step row's empty fields;
  running the escrow lifecycle in shadow) — substrate content, not
  wiring.

## Impact

- Affected specs: `hook-registry/1` (new), `reject-telemetry/1` (new).
- Affected code: `scripts/wire_up_settings.py`,
  `scripts/hook_activation.py`, `scripts/gate_telemetry.py`,
  `scripts/hooks_selfcheck.py`, `scripts/external_kicker.py`,
  `hooks/worker_budget_sinks.py`.
- Tests: `tests/test_substrate_wiring_683.py` (4 RED-first contracts +
  fail-open), registry pins updated in
  `tests/test_hook_registry_singlesource.py` and
  `tests/test_env_check.py`.
