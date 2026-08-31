# Environment drift detection + bounded repair ladder — env-state bound to heartbeat (#475)

## Why

The toolchain matrix is verified ONCE at init (`kunglao-init.py` → `toolchain.py`).
Between init and the T2/T3 dynamic phases (hours later), the environment drifts
silently: the VM lease IP rotates, adb drops the device, the frida forward
dies, the MCP bridge restarts. The first signal is a worker failing mid-claim
— tokens burned on a dispatch that was dead on arrival. The v1.9.28 lesson
(`worker_budget.py:1346-48`, "heartbeat MUST be alive before any dispatch"):
soft constraints lose to context-forgetting; only a mechanically-enforced
periodic survives. But #475's design argument (accepted, do not re-litigate)
rules out every alternative channel:

1. monitor cannot be a forcing channel — `kunglao-monitor.py:8-12` is the #88
   advisory contract (output never gates a tick);
2. no out-of-session periodicity exists — `external_kicker.py` OS registration
   is one-shot manual;
3. per-dispatch probing violates the hook contract — `env_check_gate` is
   "narrow + low-IO" and `adb devices` alone can take 10s worst-case;
4. **heartbeat is the only mechanically-enforced periodic** — so env-state
   freshness is bound to it by construction, not by a new timer.

The same debt payment as #294/#310: `tool_error_policy.py` (WARN=3/DISABLE=5
hysteresis, #309) has ZERO consumers repo-wide. The repair ladder is only
safe against flapping if hysteresis exists — wire the existing policy before
building the first ladder rung.

## What Changes

- **New `scripts/env_state_probe.py`** — liveness-subset env probe (reuses
  toolchain #474 probe primitives: `_tcp_connect`, `_adb_forward_probe`,
  port env conventions). Writes `runs/env-state.json` —
  `{per_capability: {status, last_probe_ts, detail}, written_by, ts}`.
  Capability-tier probes NEVER run here (#474 contract: periodic path is
  presence/liveness only). Fail-open: probe failure records status "fail"
  honestly but never crashes; no workspace/device → no-op.
- **`scripts/heartbeat_tick.py` step 9** — runs the env probe, report gains
  an `env_state` step entry. Same idempotent style as steps 0/1/6/7. Probe
  failure never fails the tick (env drift is monitor-visible, not
  tick-fatal).
- **`hooks/worker_budget.py check_env_fresh`** — pure file read (<5ms):
  - env-state.json missing → FAIL_OPEN + one-time stderr hint (re-init or
    run a tick), aligned with the drift/health FAIL_OPEN precedent
    (`worker_budget.py:1350-52`);
  - explicit FAIL ∩ this dispatch's tier/tools (a tool that requires
    `vm_detonation`, or tier ≥2 needing VM channel) → REJECT with drift
    guidance;
  - stale beyond ENV_STATE_TTL × 2 → REJECT + self-heal hint ("run one
    heartbeat_tick to refresh").
  New `REJECT_FIXES['envfresh']` entry.
- **`scripts/kunglao-monitor.py env_drift_watch`** — reads env-state.json,
  emits `env_drift` advisory field in TickOutput (drifted capability list +
  ages). Tick output schema stays frozen-required-compatible (new field is
  additive; #88 contract untouched — advisory only, never gates).
- **`scripts/env_repair_l1.py`** — bounded L1 deterministic repair (orchestrator-run,
  idempotent, subcommands): `adb-reconnect` (reconnect + re-forward), `vm-rediscover`
  (vmrun list → probe ports; no VM found = safe no-op), `mcp-rehandshake`
  (registry re-read + bridge port probe). Successful repair rewrites the
  env-state entry. L2/L3 are out of scope.
- **`tool_error_policy` wiring** — `worker_budget.post_check` counts
  consecutive errors per tool in the worker transcript result
  (`runs/tool-errors.json` persistence) and applies the policy: WARN feeds
  the stderr advisory, DISABLE rewrites the env-state entry for that
  capability. Consumer count 0 → ≥1, mechanically.
- Scripts README registration for both new scripts; CHANGELOG Unreleased.

## Non-goals

- L2 env-fix worker / L3 ask-a-human (later batches)
- capability-tier probes on any periodic path (#474 contract)
- gating monitor output (advisory stays advisory)
