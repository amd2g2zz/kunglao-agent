# env-drift spec delta — #475

## ADDED Requirements

### Requirement: env-state SHALL be written by the heartbeat tick via a liveness-subset probe

`runs/env-state.json` SHALL be the single source of truth for environment
capability freshness. It SHALL be written by `scripts/env_state_probe.py`
(invoked as heartbeat_tick step 8) with schema
`{per_capability: {status, last_probe_ts, detail}, written_by, ts}` where
`written_by` names the writer module. Probes SHALL be limited to the
presence/liveness subset of the #474 tier ladder (TCP connect, adb forward +
recv, port reachability) — capability-tier probes SHALL NOT run on the
periodic path. Writing SHALL be idempotent: two consecutive runs yield the
same per-capability statuses (timestamps may differ) and the same
`written_by`. A probe failure SHALL record status "fail" with honest detail
and SHALL NOT crash the tick; a workspace with no env (no VM host, no adb)
SHALL produce a no-op result rather than fabricated failures.

#### Scenario: tick writes env-state with the schema

- GIVEN a workspace with a claim-register
- WHEN heartbeat_tick.py runs
- THEN runs/env-state.json exists with written_by=env_state_probe, ts, and a per_capability map whose entries each have status + last_probe_ts + detail

#### Scenario: idempotent double tick

- GIVEN env-state.json from one tick
- WHEN the tick runs again
- THEN the per_capability key set and statuses are identical and written_by is unchanged

### Requirement: check_env_fresh SHALL implement the three-state gate

`hooks/worker_budget.py check_env_fresh` SHALL be a pure file read (no
subprocess, no network): missing env-state.json → allow (FAIL_OPEN) with a
stderr hint; an explicit per-capability "fail" that intersects the dispatch's
needs (tool requires vm_detonation, or tier ≥ 2 in a VM-channel workspace)
→ REJECT with drift guidance including the L1 repair script; entries older
than ENV_STATE_TTL × 2 → REJECT with the self-heal hint "run one
heartbeat_tick to refresh". Corrupt JSON SHALL fail open.

#### Scenario: missing file fails open

- GIVEN a workspace with no runs/env-state.json
- WHEN check_env_fresh runs
- THEN the check allows the dispatch and prints a one-time hint to stderr

#### Scenario: explicit FAIL intersecting the tier rejects

- GIVEN env-state.json with vm_reachable: fail and fresh timestamps
- WHEN a [T2 tools=vmr-shell] dispatch is pre-checked
- THEN pre_check returns 2 with 'REJECT envfresh' and the guidance names the L1 repair script

#### Scenario: stale beyond 2x TTL rejects with self-heal hint

- GIVEN env-state.json whose last_probe_ts is older than 2 × ENV_STATE_TTL
- WHEN any tier-2 dispatch is pre-checked
- THEN the REJECT message tells the dispatcher to run one heartbeat_tick to refresh

### Requirement: monitor SHALL surface env drift as an advisory ENV_DRIFT decision

`scripts/kunglao-monitor.py` SHALL read env-state.json in its tick and emit
an `env_drift` field: OK when all entries are fresh and passing; DRIFT with
the drifted capability list and ages otherwise. Missing file → NO_DATA. The
field SHALL be advisory only — monitor output SHALL NOT gate any tick action
(#88 contract preserved). Existing TickOutput required fields SHALL remain
unchanged.

#### Scenario: drifted VM surfaces ENV_DRIFT

- GIVEN env-state.json with vm_reachable: fail
- WHEN the monitor tick runs with --json
- THEN the output contains env_drift.status=DRIFT naming vm_reachable, and the tick exits 0 (not blocked)

#### Scenario: healthy env-state is OK; absent file is NO_DATA

- GIVEN all-fresh passing entries
- THEN env_drift.status is OK; and with no file at all env_drift.status is NO_DATA

### Requirement: tool_error_policy SHALL have a mechanical consumer

`hooks/worker_budget.py post_check` SHALL count consecutive failing
invocations per tool (persisted in runs/tool-errors.json), apply
`tool_error_policy.evaluate_streak`, and emit: ok → silent; warn → stderr
advisory naming the streak; disable_escalate → stderr escalation with the
blocker note and the env-state entry for that capability marked failed. A
successing invocation SHALL reset the streak to 0.

#### Scenario: three consecutive failures warn

- GIVEN a worker transcript result where one tool failed 3 times in a row
- WHEN post_check runs
- THEN runs/tool-errors.json has streak=3 and stderr carries the warn message

#### Scenario: five consecutive failures disable

- GIVEN 5 consecutive failures of one tool
- THEN the action is disable_escalate with a blocker_note and the capability's env-state entry (if any) is marked failed

### Requirement: L1 repair SHALL be idempotent and safe without a device

`scripts/env_repair_l1.py` SHALL provide bounded deterministic repairs as
subcommands (adb-reconnect, vm-rediscover, mcp-rehandshake). Each SHALL be
idempotent (two consecutive runs produce identical reported states) and a
no-op with an honest skip result when its substrate is absent (no adb, no
VM tooling, no MCP registry). A successful repair SHALL rewrite the matching
env-state entry as fresh+pass.

#### Scenario: repair without substrate is a safe no-op

- GIVEN a machine with no adb on PATH and no KUNGLAO_VM_HOST
- WHEN env_repair_l1.py runs all subcommands
- THEN exit is 0 with skip statuses, and env-state.json (if present) is not corrupted

#### Scenario: double repair is stable

- GIVEN any substrate state
- WHEN the same subcommand runs twice
- THEN both runs report the same capability status
