## ADDED Requirements

### Requirement: build_anchor SHALL return a ≤500-char mechanical-state summary and never raise

`hooks/state_anchor.py::build_anchor(workspace) -> str` SHALL read ONLY
mechanical state — the last SNAPSHOT row of
`workspace/.convergence_ledger.jsonl` (`decision`, `open_count`,
`open_ids`, `partial_count`, `active_workers`, `blockers`, `facts_total`),
OPEN / PARTIALLY-VERIFIED claim ids from `claim-register.yaml`, PARTIAL
facts from `facts/_INDEX.md`, and in-progress workers from
`runs/worker-status-*.md` — and return a summary string of at most 500
characters (truncating the open-ids list from the tail when overflowing,
never raising). It SHALL NOT read `progress.txt` or `analysis_state.txt`
(LLM narrative — F4: an LLM saying done is not an event). Any exception
(missing or corrupt ledger, OSError, parse failure) SHALL yield the empty
string `""` (FAIL_OPEN — the hook never raises into the harness).

#### Scenario: Agent completion injects ledger last-row decision + open_count
- **GIVEN** the ledger's last SNAPSHOT row is `{"decision": "DISPATCH", "open_count": 2, "open_ids": ["C-201","C-003"], …}`
- **WHEN** `build_anchor(ws)` is called
- **THEN** the returned string contains `DISPATCH` and `open_count=2` (or the open ids `C-201` / `C-003`)

#### Scenario: missing ledger yields empty string, never raises
- **WHEN** `build_anchor(ws)` is called on a workspace with no `.convergence_ledger.jsonl`
- **THEN** it returns `""` and does NOT raise

#### Scenario: corrupt ledger yields empty string, never raises
- **GIVEN** the ledger contains only a malformed line `not-json{`
- **WHEN** `build_anchor(ws)` is called
- **THEN** it returns `""` and does NOT raise

#### Scenario: narrative files are never read
- **GIVEN** `progress.txt` contains a fake narrative sentence `我正在分析 C-007，接下来准备做 VM detonation`
- **WHEN** `build_anchor(ws)` is called
- **THEN** the returned string does NOT contain `我正在分析 C-007`

#### Scenario: summary is truncated to at most 500 chars
- **GIVEN** a workspace whose open-ids list is long enough to overflow 500 chars
- **WHEN** `build_anchor(ws)` is called
- **THEN** `len(returned) <= 500`

### Requirement: the drift warning SHALL fire on drift_detected and carry the rotation count

`hooks/state_anchor.py::build_anchor(workspace)` SHALL append a prominent
drift warning to the anchor string when `drift_detected(workspace)` is True
(#43: `signature_rotation ≥ ROTATION_WINDOW` AND NOT `workers_progressing`).
The warning SHALL contain the literal `⚠ STATE FLAT` and the rotation count
N (e.g. `⚠ STATE FLAT: 4 identical turns, re-read claim-register`, where
N = `signature_rotation(workspace)`). The drift semantics SHALL be sourced
from `scripts/lib_kunglao.signature_rotation` / `drift_detected` — the SAME
module `external_kicker.should_kick` uses (loaded by explicit importlib path
under the unique name `lib_kunglao_scripts`, so the cure layer and the
recovery layer share one drift definition and cannot fork). When drift is
NOT detected, the warning SHALL be absent.

#### Scenario: rotation 4 with no worker triggers the drift warning
- **GIVEN** the ledger's last 4 SNAPSHOT rows are signature-identical and no in-progress worker status file exists
- **WHEN** `build_anchor(ws)` is called
- **THEN** the returned string contains `⚠ STATE FLAT` and `4`

#### Scenario: rotation below the window does not warn
- **GIVEN** `signature_rotation(ws) < ROTATION_WINDOW`
- **WHEN** `build_anchor(ws)` is called
- **THEN** the returned string does NOT contain `STATE FLAT`

#### Scenario: fresh in-progress worker suppresses the warning
- **GIVEN** `signature_rotation(ws) >= ROTATION_WINDOW` AND a fresh in-progress worker status file
- **WHEN** `build_anchor(ws)` is called
- **THEN** the returned string does NOT contain `STATE FLAT` (a legitimate SATURATED wait is not drift)

### Requirement: the hook SHALL emit only on Agent-tool completion and FAIL_OPEN on any error

`hooks/state_anchor.py::main()` SHALL read the PostToolUse stdin JSON
payload and emit the `hookSpecificOutput.additionalContext` JSON (mirroring
`hooks/worker_pulse.py`'s emission shape) ONLY when `payload["tool_name"]`
lowercased equals `"agent"` AND kunglao-agent is strictly activated
(`.hook_state.json` present and not expired via
`hook_activation.is_active_strict`). For any other `tool_name` (e.g.
`"Bash"`, `"Read"`) or an inactive session, it SHALL SKIP (exit 0, empty
stdout). Any exception during payload parse, workspace resolution,
activation check, or anchor build SHALL result in exit 0 with no output
(FAIL_OPEN — never abort the worker completion).

#### Scenario: Agent-tool completion injects the anchor
- **GIVEN** a strictly-activated workspace and `tool_name: "Agent"`
- **WHEN** the hook runs on a PostToolUse Agent payload
- **THEN** stdout contains a JSON object whose `hookSpecificOutput.additionalContext` includes the anchor summary

#### Scenario: non-agent tool is skipped
- **GIVEN** `tool_name: "Bash"` (or `"Read"`)
- **WHEN** the hook runs
- **THEN** stdout is empty and the exit code is 0

#### Scenario: tool_name is matched case-insensitively
- **GIVEN** `tool_name: "AGENT"` (or `"agent"`)
- **WHEN** the hook runs on an activated workspace
- **THEN** the anchor is injected (the harness lowercases tool names; the match is case-insensitive)

#### Scenario: any exception returns empty output, exit 0
- **GIVEN** a payload that raises during processing (e.g. unparseable stdin, missing workspace)
- **WHEN** the hook runs
- **THEN** it exits 0 with empty stdout (FAIL_OPEN)

### Requirement: wire-up SHALL register state_anchor as PostToolUse(Agent) and list it in ALL_HOOKS

`scripts/wire_up_settings.py::wire_up_settings()` SHALL register
`state_anchor.py` as a PostToolUse hook with matcher `Agent` (a single
`_ensure(post, "Agent", "state_anchor.py")` append mirroring the existing
`worker_pulse.py` registration line, same POSIX-path `_entry()` shape).
`scripts/hook_activation.py::ALL_HOOKS` SHALL include the member
`"state_anchor"` so the activation machinery recognizes the hook name. The
wire-up SHALL be idempotent (re-running on already-wired settings is a
fixed point — no duplicate state_anchor entry) and SHALL preserve every
other settings key.

#### Scenario: wire-up appends the state_anchor PostToolUse(Agent) entry
- **GIVEN** a settings dict with an existing PostToolUse Agent entry for worker_pulse
- **WHEN** the `_ensure` registration runs against it (tested via a temp settings path with `Path.home()` monkeypatched)
- **THEN** the resulting PostToolUse list contains both the worker_pulse entry and a state_anchor entry with matcher `Agent`

#### Scenario: ALL_HOOKS contains state_anchor
- **WHEN** `ALL_HOOKS` is imported from `hook_activation`
- **THEN** `"state_anchor"` is a member of the set

#### Scenario: re-running wire-up is a fixed point
- **GIVEN** settings already wired with state_anchor
- **WHEN** `wire_up_settings()` runs again
- **THEN** no duplicate state_anchor entry is added (idempotent merge)
