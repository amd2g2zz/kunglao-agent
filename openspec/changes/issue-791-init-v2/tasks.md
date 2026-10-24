# issue-791-init-v2 tasks

## 1. Registry + init faces

- [x] 1.1 scripts/lane_profile.py — per-lane profile registry
      (prescan battery / binary faces / obligation artifacts / factor
      set / capability vocabulary incl. device_root; unknown-lane
      fail-open marker)
- [x] 1.2 intake_promise consumes the registry (lane key, out-of-lane
      probes dropped, obligation artifacts registry-sourced, loud
      fallback WARN)
- [x] 1.3 difficulty_calibration factor sets (web map, factor_set in
      the schema, honest UNKNOWN for absent/unvalidated extractors)
- [x] 1.4 env_state_probe device_root (ANDROID_CAPS + su -c id probe,
      honest skip chain)

## 2. Capability axis

- [x] 2.1 dispatch_gate._lane_capability_gate (declared tools -> tool
      families -> registry reverse map -> near-time env-state; REJECT
      evidence class + wake condition; fail-open on state outages)
- [x] 2.2 event_taxonomy: lane_capability_reject registered

## 3. Bounded-intelligent intake

- [x] 3.1 scripts/intake_draft.py (scaffold echo + confirm wall +
      declared_ts stamping + R1/R2/R6 discipline + task_spec PQ merge)
- [x] 3.2 kunglao-init: goal-op scaffold UNSTAMPED + intake-draft
      scaffold written (WARN-tier, never silent)

## 4. Verification

- [x] 4.1 tests/test_lane_profile_791.py (51job replay pins: zero
      binary obligations on web, zero capability-fabricated dispatches)
- [x] 4.2 tests/test_intake_draft_791.py (ordering + wall + R2/R5 pins)
- [x] 4.3 baselines emit (hygiene/formal-code/silent-except) THEN
      deploy_manifest --write LAST; local_gate ALL-PASS
- [x] 4.4 openspec validate + impact/detect-changes + mint chain
