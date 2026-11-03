# tasks — issue-801-economics-v2

## 1. The RED contract
- [ ] tests/test_economics_801.py: quiet-hour zero-prompt pin (token-meter);
      wake-on-watchdog / wake-on-event / park-expiry pins; format demotion
      pin (WARN + sidecar, NOT rc=2); five-hard-classes-still-block pins;
      self-health crash pin (51job shape dead); cockpit ratio + alarm pins;
      rc1 regression-runner replay pin
- [ ] confirmed RED (pins fail) before implementing

## 2. The faces
- [ ] `hooks/gate_policy.py` — the five-class HARD allowlist + demotion
      decision + shared telemetry sidecar writer (gate-rejections.jsonl)
- [ ] `scripts/heartbeat_tick.py` — `wake_verdict()` predicate +
      `--wake-gate` face (rc 0 QUIET / rc 3 WAKE) + `report.wake` +
      park-expiry counter (runs/.wake-gate.json) + cockpit_ratio surface
- [ ] `scripts/mechanisms.yaml` — os-channel `wake_gate` entry (declaration)
- [ ] `hooks/dispatch_gate.py` — `_reject_with_guidance` gate_class param
      (format default → demote), `_gate_error_reject` → self-health WARN
      face; mcp_prefix site stays execution_surface
- [ ] `hooks/write_guard.py` — adjudication-crash arms → self-health WARN
      + allow (content-contract refusals stay corruption-HARD)
- [ ] `hooks/cost_input_capture.py` — `compute_ratio` + incremental
      cockpit face + alarm (cockpit_ratio_alarm ledger word)
- [ ] `scripts/event_taxonomy.py` — register `gate_warn`,
      `cockpit_ratio_alarm` (sorted+unique)
- [ ] `scripts/experiments/rc1_econ_replay.py` — DuckDB-first regression
      runner + stdlib fallback
- [ ] registration triple for the new script (README + ext-scan + manifest
      --write LAST)

## 3. Gates
- [ ] pins green; neighbors (heartbeat_tick/write_guard/dispatch_gate
      suites) green — spec-superseded crash pins updated in the same PR;
      ruff; comment-hygiene; manifest --verify
- [ ] liveness: INV-006/007/008 declared; liveness_gate non-degrading
- [ ] review-gate mint; CI green
