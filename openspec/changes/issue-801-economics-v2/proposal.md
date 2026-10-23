# issue-801-economics-v2 — the harness stops taxing the analysis

## Why

Owner objective restated (#801): reliable+accurate → speed → tokens, as
RATIOS; the harness must never out-compete the analysis for budget. Three
residual wastes after the rc1 containment:

1. **LLM-mediated no-op wakes (HIGH)** — a quiet 5-min cron wake re-reads
   the whole session context (~60k) to conclude "no-op": ~750k input tok/h,
   zero analysis output.
2. **Format-class admission loops (HIGH)** — ~120k input tok per rc=2
   rejection × 20/session (#741 shape); 19/22 BLOCKED legs are format-class.
   RE-seat FATALs: rc=6 heartbeat-entry refusals needing HUMAN rulings, and
   write_guard locking the claim-register when the harness's own gate
   crashed (ModuleNotFoundError) — self-health stopping the mission.
3. **Machine:analysis ratio unobservable** — the rc1 death shape
   (dispatch:tick ≈1.2:1) was only visible post-mortem via DuckDB over the
   transcripts; nothing alarms while it happens.

## What Changes

1. **Pre-LLM wake gate** (`scripts/heartbeat_tick.py` +
   `scripts/mechanisms.yaml`) — a wake predicate computed host-side, BEFORE
   any LLM sees anything: wake iff `watchdog.fired` OR fresh wake-class bus
   events (settlement/stall/plan_review) OR park-expiry (consecutive quiet
   parked ticks >= KUNGLAO_PARK_EXPIRY_TICKS, default 36). `--wake-gate`
   face: quiet → stdout `QUIET:` + rc 0 (the OS scheduler injects nothing);
   wake → stdout `WAKE:` + rc 3 (inject the loop prompt). Silence is the
   honest idle. Registered as an os-channel mechanism (declaration per
   #878 — out-of-session, never tick-dispatched).
2. **Gate layering** (NEW `hooks/gate_policy.py`; call-site demotions in
   `hooks/dispatch_gate.py` + `hooks/write_guard.py`) — exactly five HARD
   classes keep blocking: **corruption, reward_integrity,
   termination_budget, evidence, execution_surface**. ALL format-class
   rejections and ALL self-health (gate-crash) faces demote to WARN +
   telemetry sidecar (`runs/gate-rejections.jsonl` row, exit_code=0 +
   `gate_warn` ledger row) and return rc 0. This SUPERSEDES the
   2026-09-28 owner ruling (gate error = fail-closed) for the
   format/self-health classes per #801 Face 2; the five hard classes are
   untouched.
3. **Cockpit ratio** (`hooks/cost_input_capture.py` + tick report) —
   machine-overhead input tokens (orchestrator transcript rows) ÷
   analysis-output tokens (sidechain/worker rows), computed live and
   incrementally (byte-offset cached), persisted to
   `ws/runs/.cockpit-ratio.json`, surfaced in the tick report, alarm
   (stderr WARN + `cockpit_ratio_alarm` ledger row) when ratio > 1.
4. **RC1 regression runner** (NEW `scripts/experiments/rc1_econ_replay.py`)
   — the rc1-audit DuckDB queries committed: hourly machine:analysis
   series + alarm hours over a transcript JSONL (duckdb when importable,
   documented stdlib fold as fallback). Fixture-replayable in CI.

## Out of scope (named)

- Hook spawn wall (9→2 processes per Bash) — ranked follow-on, zero-token
  risk, not this card.
- `dispatch_gate.py` claims/compensation block — W0-2's (#800); this card
  touches ONLY the gate-classification/rejection faces.
- tests/ inventory & cleanup — W0-4's (#807).
- `worker_budget_sinks.py` rc faces — termination/budget = HARD, stays.

## Invariants cited (devkit/invariants/registry.json)

- INV-006 — the upgrade iron rule tolerates live appends to the event log:
  the wake gate + telemetry sidecars only APPEND rows (gate-rejections,
  cockpit-ratio, ledger), never rewrite history.
- INV-007 — recall injection opt-in: the wake gate adds no injection
  channel; the loop prompt body is unchanged.
- INV-008 — upgrade order: deploy-manifest regeneration stays the LAST
  step (registration triple).
