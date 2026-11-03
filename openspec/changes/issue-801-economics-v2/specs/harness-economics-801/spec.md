# harness-economics-801 delta — issue-801-economics-v2

## ADDED Requirements

### Requirement: The wake gate spends zero tokens on a quiet workspace

The tick host SHALL compute a wake verdict host-side: wake iff the
watchdog fired, OR this pass consumed fresh wake-class bus events
(settlement/stall/plan_review), OR the park has held >=
KUNGLAO_PARK_EXPIRY_TICKS consecutive passes (park-expiry re-proof). In
`--wake-gate` mode a quiet verdict SHALL exit 0 with a `QUIET:` marker and
inject no prompt guidance; a wake verdict SHALL exit 3 with a `WAKE:`
marker naming the reasons. The liveness core (selfcheck/reconcile/renew/
heartbeat-check) stays armed on every pass, quiet or not.

#### Scenario: quiet-hour fixture injects zero prompts

- **WHEN** the tick runs `--wake-gate` on a workspace with no watchdog
  reason, no bus events, and a park below expiry
- **THEN** rc=0, stdout carries `QUIET:`, the `*** WATCHDOG` banner is
  absent, and `report.wake.needed` is false

#### Scenario: each wake reason fires

- **WHEN** the watchdog fires (stale heartbeat), or a settlement event
  lands, or the persisted quiet-tick counter reaches expiry
- **THEN** rc=3, stdout carries `WAKE:`, and the report names the reason

### Requirement: Format-class and self-health gates warn, never block

A gate rejection whose class is `format` or `self_health` SHALL NOT exit
2 / block the tool call: it SHALL emit a stderr WARN, append ONE
telemetry sidecar row to `runs/gate-rejections.jsonl`
(`gate_class` set, `exit_code: 0`), emit a `gate_warn` ledger row, and
return rc 0. Exactly five classes stay HARD: corruption,
reward_integrity, termination_budget, evidence, execution_surface.

#### Scenario: format-invalid dispatch demotes

- **WHEN** a dispatch hits a format-class rejection face
- **THEN** the tool call proceeds (rc 0), the sidecar row lands with
  `gate_class: format`, and no rc=2 is returned

#### Scenario: the five hard classes still block

- **WHEN** any face of the five hard classes fires (must-stop dispatch,
  register write-contract refusal, budget/termination rc, evidence-pin
  refusal, MCP/tool-surface rejection)
- **THEN** the gate still blocks (rc 2 family) unchanged

#### Scenario: self-health failure never blocks analysis

- **WHEN** a gate checker crashes mid-adjudication (the 51job
  ModuleNotFoundError shape) and the crash arms route through the
  self-health class
- **THEN** the write/tool call proceeds, a WARN + sidecar row with
  `gate_class: self_health` lands, and no rc=2 is returned

### Requirement: The cockpit ratio is live with an alarm at >1

The cost-input capture SHALL compute machine-overhead input tokens ÷
analysis-output tokens from the session transcript (incremental,
byte-offset cached), persist `{ts, machine_input_tokens,
analysis_output_tokens, ratio}` to `ws/runs/.cockpit-ratio.json`, and
when ratio > 1 emit a stderr WARN + a `cockpit_ratio_alarm` ledger row.
The tick report carries the latest ratio as `report.cockpit_ratio` when
present. Fail-open: any read/parse trouble writes nothing and alarms
nothing.

#### Scenario: alarm fires when overhead out-competes analysis

- **WHEN** the fixture transcript carries machine input 5000 / analysis
  output 1000
- **THEN** ratio == 5.0, the alarm row lands, and the persisted file
  says ratio > 1

#### Scenario: healthy ratio stays silent

- **WHEN** the fixture carries machine 500 / analysis 5000
- **THEN** ratio == 0.1 and no alarm row lands

### Requirement: The rc1 audit queries replay as a regression runner

A committed runner SHALL replay the rc1 economics audit over a transcript
JSONL: hourly machine:analysis ratio series + flagged alarm hours. It
SHALL use DuckDB when importable (canonical SQL embedded) and fall back
to a documented stdlib fold with the same output schema otherwise.

#### Scenario: fixture replay

- **WHEN** the runner executes against the synthetic rc1-shaped fixture
- **THEN** it exits 0, prints a JSON series whose hourly ratio matches
  the fixture arithmetic, and flags the >1 hours

### Requirement: Demoted warns are bounded per family with a named owner

The gate layering SHALL count demoted WARN emissions per normalized family
(gate + class + message shape). When one family exceeds a bounded session
threshold, the harness SHALL take EXACTLY ONE ownership action for that
family — operator escalation, circuit-break (suppress further same-family
emissions), or an explicit documented downgrade — persist the choice, and
surface the tripped families in the tick report (the heartbeat face). The
default action is circuit-break. Production basis (rc1): 540/593 warns were
verbatim repeats of six pathologies, and a completion_gate leg hung 41h
with nobody called — unbounded repeat warns are unowned.

#### Scenario: a 392-warn replay trips the breaker

- **WHEN** a synthetic sequence of 392 same-family demoted warns replays
  through the layering authority
- **THEN** the family trips exactly once at the bound, the breaker state
  lands (`runs/.warn-breaker.json`) with action `circuit-break`, further
  same-family warns are suppressed (sidecar row stops growing), and the
  tick report names the tripped family

#### Scenario: below-bound families stay observable

- **WHEN** a family has fewer warns than the bound
- **THEN** every demotion keeps its stderr WARN + sidecar row (no
  suppression, no escalation)

### Requirement: Incremental telemetry emits only on value change

The high-frequency telemetry faces (statusline snapshot, detector_eval)
SHALL emit only when the emitted VALUE changed since that face's last
emission; an unchanged value is silent (the production shape: 76
consecutive dead rho=0.0 detector_eval rows at 6-9% analysis progress —
telemetry was ~57-63% of event volume). Suppression state is ONE durable
per-face digest; a changed value emits and refreshes the digest.
rank_feeds is DELIBERATELY OUT of scope: the #157 replay spine (the
ranking is exactly replayable from the event tail) and the #218
last-attempt health bit pin the per-run emit attempt itself, so
suppressing an identical ranking would erase the round-advance marker
the replay needs.

#### Scenario: unchanged rho stays silent

- **WHEN** the same rho value is evaluated repeatedly with no change
- **THEN** only the first evaluation emits detector_eval and every
  identical repeat is silent

#### Scenario: a changed value emits and re-arms

- **WHEN** the value changes after a suppression streak
- **THEN** the changed value emits a fresh row and the digest updates

#### Scenario: rank_feeds keeps its per-run emission

- **WHEN** two ranking runs produce the identical ranked order
- **THEN** both runs still attempt the rank_feeds emit (the #157 replay
  spine and #218 health bit stay intact)

### Requirement: Unactuated detector evaluations are billed consumption

detector_eval rows with no actuator face (no subsequent detector_fired for
the same detector) SHALL be counted as machine consumption in the
economics faces: the live cockpit face carries eval/fire/unactuated counts
next to the ratio, and the rc1 replay reports the same accounting (the
production shapes: 62:1 and 142:1 eval:fire — detection without action is
billed, invisible cost today).

#### Scenario: replay reports unactuated consumption

- **WHEN** the fixture ledger carries 62 detector_eval rows and 1
  detector_fired for the same detector
- **THEN** the replay output reports unactuated = 61 and the cockpit face
  carries the same consumption accounting
